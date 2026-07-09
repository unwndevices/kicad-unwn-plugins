"""Reference-plane identification + four-bucket classification (spec §4).

For every routed trace this resolves the **reference plane(s)** carrying its return
current, then classifies the segment into one of the four §4.4 buckets:

* **solid** — one qualifying reference plane covers the whole segment → clean, no finding.
* **split-crossing** — an uncovered span with reference copper on **both** sides (an
  internal void/slot/gap). *The primary defect* → ``error``.
* **reference-change** — the segment is fully referenced, but the covering plane's
  *identity* changes along it (GND → power, or a bottom-reference layer swap) → ``info``.
* **edge-overhang / no-reference** — an uncovered span running off the pour boundary, or
  no qualifying adjacent plane at all → ``warning``.

**Reference resolution (§4.1/§4.3)** is a hybrid: a declared Track-Propagation table
(``board.propagation``) wins where present; otherwise the immediate stackup neighbour(s)
(``board.stackup``) are used — one for a microstrip (outer) layer, two for a stripline
(inner) layer between planes. Where the board carries no stackup at all (minimal
fixtures), it falls back to the skeleton rule: any reference plane on a layer other than
the trace's own. Geometric coverage is **always** re-checked against the real island
geometry, so a void carved in a *declared* plane is still caught (the antipads are baked
in, §3).

The split-crossing vs edge-overhang split reuses the validated **both-ends-on-plane**
predicate (§4.4): a span whose two endpoints both land on the *same* reference plane's
copper re-enters copper on the far side (a real split); a free-ended span merely leaves
the pour (a benign terminus over-run — on the retest board this dropped 89 of 91 raw
spans).
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import PreparedGeometry, prep

from .parser import Board, PlaneRef, Trace

# §4.4 / §5 default severities for the classes this detector emits.
SEVERITY = {
    "split-crossing": "error",
    "reference-change": "info",
    "edge-overhang": "warning",
    "no-reference": "warning",
}


@dataclass(frozen=True)
class Finding:
    """The canonical finding record (spec §8.1) — shared by every report format."""

    check: str  # detector that produced it, e.g. "split-crossing"
    net: str
    cls: str  # "split-crossing" | "reference-change" | "edge-overhang" | "no-reference"
    severity: str  # "error" | "warning" | "info"
    layer: str  # the trace's layer
    reference_layer: str  # the plane layer(s) the segment was measured against
    x: float
    y: float
    span_mm: float
    message: str


# --------------------------------------------------------------------------- #
# reference resolution (§4.1 / §4.3)
# --------------------------------------------------------------------------- #
def _reference_layers(trace: Trace, board: Board) -> tuple[str, ...]:
    """Which layers hold *trace*'s candidate reference plane(s) (§4.1/§4.3).

    Precedence: a declared Track-Propagation entry for the trace's layer wins; else the
    immediate stackup neighbour(s) (below is the primary reference, above added for a
    stripline); else — no stackup for this layer — every other copper layer that carries
    a reference plane (the skeleton fallback). The trace's own layer is never a reference.
    """
    declared = board.propagation.get(trace.layer)
    if declared:
        ref_layers: tuple[str, ...] = declared
    elif trace.layer in board.stackup:
        above, below = board.stackup.neighbours(trace.layer)
        ref_layers = tuple(layer for layer in (below, above) if layer is not None)
    else:
        # No stackup for this layer: any plane on another layer is a candidate.
        seen: list[str] = []
        for pr in board.plane_refs:
            if pr.layer != trace.layer and pr.layer not in seen:
                seen.append(pr.layer)
        ref_layers = tuple(seen)
    return tuple(layer for layer in ref_layers if layer != trace.layer)


def _candidates(trace: Trace, board: Board) -> list[PlaneRef]:
    """The reference planes (any qualifying net) adjacent to *trace*, per §4.3."""
    ref_layers = _reference_layers(trace, board)
    return [pr for pr in board.plane_refs if pr.layer in ref_layers]


def resolve_reference_layers(trace: Trace, board: Board) -> tuple[str, ...]:
    """Distinct reference-plane layers resolved for *trace* — one (microstrip) or two
    (stripline), per §4.3. Public so the adjacency model can be asserted directly."""
    layers: list[str] = []
    for c in _candidates(trace, board):
        if c.layer not in layers:
            layers.append(c.layer)
    return tuple(layers)


# --------------------------------------------------------------------------- #
# classification (§4.4)
# --------------------------------------------------------------------------- #
def _spans(
    line: BaseGeometry, uncovered: BaseGeometry, min_span: float, sliver_area: float, width: float
) -> list[BaseGeometry]:
    """Reportable uncovered sub-spans: drop those below the length and copper floors (§5.1)."""
    if uncovered.is_empty:
        return []
    # difference() may return a bare LineString, a MultiLineString, or — when the trace
    # grazes a plane vertex/boundary — a GeometryCollection mixing Points and LineStrings.
    # Flatten to the LineString parts so a real void inside a collection isn't discarded.
    geoms = list(getattr(uncovered, "geoms", [uncovered]))
    out = []
    for g in geoms:
        if g.geom_type != "LineString" or g.length < min_span:
            continue
        if g.length * width < sliver_area:
            continue
        out.append(g)
    return out


def _classify(
    trace: Trace,
    candidates: list[PlaneRef],
    prep_by_key: dict[tuple[str, str], PreparedGeometry],
    edge_by_key: dict[tuple[str, str], BaseGeometry],
    *,
    min_crossing_span_mm: float,
    sliver_ignore_area_mm2: float,
) -> list[Finding]:
    """Classify *trace* against its *candidates* into §4.4 findings (empty ⇒ solid)."""
    if not candidates:
        mid = trace.line.interpolate(0.5, normalized=True)
        return [
            _finding(trace, "no-reference", "—", mid.x, mid.y, trace.line.length),
        ]

    union = unary_union([c.geom for c in candidates])
    if prep(union).covers(trace.line):
        # Fully referenced: solid unless the covering plane's identity changes (§4.4).
        if any(prep_by_key[(c.layer, c.net)].covers(trace.line) for c in candidates):
            return []  # solid — one plane covers the whole segment
        return [_reference_change(trace, candidates)]

    # Uncovered spans → split-crossing / edge-overhang per the both-ends predicate.
    findings: list[Finding] = []
    for g in _spans(
        trace.line,
        trace.line.difference(union),
        min_crossing_span_mm,
        sliver_ignore_area_mm2,
        trace.width,
    ):
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        ref_layer, both_on = _endpoints_on_plane(a, b, candidates, edge_by_key)
        cls = "split-crossing" if both_on else "edge-overhang"
        mid = g.interpolate(0.5, normalized=True)
        findings.append(_finding(trace, cls, ref_layer, mid.x, mid.y, g.length))
    return findings


def _endpoints_on_plane(
    a: Point, b: Point, candidates: list[PlaneRef], edge_by_key: dict[tuple[str, str], BaseGeometry]
) -> tuple[str, bool]:
    """Return ``(reference_layer, both_ends_on_same_plane)`` for a span's endpoints (§4.4).

    Both endpoints on the *same* plane's copper → split-crossing; report that plane's
    layer. Otherwise edge-overhang — report whichever plane an endpoint touches, else the
    primary candidate.
    """
    for c in candidates:
        edge = edge_by_key[(c.layer, c.net)]
        if edge.contains(a) and edge.contains(b):
            return c.layer, True
    for c in candidates:
        edge = edge_by_key[(c.layer, c.net)]
        if edge.contains(a) or edge.contains(b):
            return c.layer, False
    return candidates[0].layer, False


def _reference_change(trace: Trace, candidates: list[PlaneRef]) -> Finding:
    """Build the reference-change finding, listing the planes crossed, ordered along the
    trace (§4.4)."""
    covering = [c for c in candidates if c.geom.intersects(trace.line)]
    covering.sort(key=lambda c: trace.line.project(c.geom.intersection(trace.line).centroid))
    detail = " → ".join(f"{c.layer}:{c.net}" for c in covering)
    layers: list[str] = []
    for c in covering:
        if c.layer not in layers:
            layers.append(c.layer)
    mid = trace.line.interpolate(0.5, normalized=True)
    return _finding(
        trace, "reference-change", ", ".join(layers), mid.x, mid.y, trace.line.length, detail
    )


def _finding(
    trace: Trace, cls: str, reference_layer: str, x: float, y: float, span: float, detail: str = ""
) -> Finding:
    return Finding(
        check=cls,
        net=trace.net,
        cls=cls,
        severity=SEVERITY[cls],
        layer=trace.layer,
        reference_layer=reference_layer,
        x=x,
        y=y,
        span_mm=span,
        message=_message(cls, trace.net, reference_layer, span, detail),
    )


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def check_return_path(
    board: Board,
    *,
    reference_nets: tuple[str, ...] = ("GND",),
    min_crossing_span_mm: float = 0.1,
    sliver_ignore_area_mm2: float = 0.0065,
    sampling_tolerance_mm: float = 0.05,
) -> list[Finding]:
    """Resolve each trace's reference plane(s) and classify it into the four §4.4 buckets."""
    # Prepare + buffer each plane once (§2 optimisation), keyed by its (layer, net) —
    # unique per plane_ref, so the lookup is self-evidently correct.
    prep_by_key = {(pr.layer, pr.net): prep(pr.geom) for pr in board.plane_refs}
    edge_by_key = {
        (pr.layer, pr.net): pr.geom.buffer(sampling_tolerance_mm) for pr in board.plane_refs
    }

    # A reference net is never a victim — skip any trace whose net forms a plane on this
    # board, not just those named in `reference_nets`. This keeps the skip set aligned with
    # `board.plane_refs` even when the caller passes a reference_nets that diverges from the
    # one `parse_board` built the planes with (else a power trace could self-reference).
    skip_nets = set(reference_nets) | {pr.net for pr in board.plane_refs}

    findings: list[Finding] = []
    for trace in board.traces:
        if trace.net in skip_nets:
            continue
        findings.extend(
            _classify(
                trace,
                _candidates(trace, board),
                prep_by_key,
                edge_by_key,
                min_crossing_span_mm=min_crossing_span_mm,
                sliver_ignore_area_mm2=sliver_ignore_area_mm2,
            )
        )
    return findings


# Backwards-compatible alias — the walking skeleton (issue #17) named the entry point
# after its sole check; it now runs the full four-bucket classifier.
check_split_crossing = check_return_path


def _message(cls: str, net: str, ref_layer: str, span: float, detail: str) -> str:
    if cls == "split-crossing":
        return (
            f"{net} crosses a {span:.2f} mm void in the {ref_layer} reference plane — "
            f"the return current has no continuous path across the gap"
        )
    if cls == "reference-change":
        return (
            f"{net} changes reference plane along the segment ({detail}) — the return "
            f"current must transfer between planes; verify a stitch/decoupling path exists"
        )
    if cls == "no-reference":
        return (
            f"{net} has no qualifying reference plane on an adjacent layer — "
            f"the return current is unreferenced along its {span:.2f} mm run"
        )
    return (
        f"{net} runs {span:.2f} mm past the edge of the {ref_layer} reference plane — "
        f"unreferenced over-run (verify it is not a real plane shortfall)"
    )
