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

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union
from shapely.prepared import PreparedGeometry, prep

from .config import Config
from .parser import Board, PlaneRef, Trace, Via

# §4.4 / §5 default severities for the classes this detector emits.
SEVERITY = {
    "split-crossing": "error",
    "reference-change": "info",
    "edge-overhang": "warning",
    "no-reference": "warning",
    "edge-clearance": "warning",
    "missing-return-via": "error",
}

# The 90 mil floor in the §5.2 edge-clearance formula, in millimetres.
EDGE_CLEARANCE_MIL_FLOOR_MM = 90 * 0.0254


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
    # Populated by the waiver layer (spec §7.2); default-inert so the detector never sets
    # them. ``id`` is the content hash (§7.2); ``waived`` + ``waiver_reason`` echo an
    # accepted finding. A waived finding is carried, never dropped (§8.1).
    id: str = ""
    waived: bool = False
    waiver_reason: str = ""


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


# --------------------------------------------------------------------------- #
# plane-edge clearance (§5.1 #2 / §5.2)
# --------------------------------------------------------------------------- #
def _edge_clearance_threshold(
    trace: Trace, ref_layer: str, board: Board, override: float | None
) -> float:
    """The §5.2 edge-clearance threshold for *trace* against *ref_layer*.

    A scalar ``override`` (config ``edge_clearance_mm``) sets a flat floor; otherwise the
    per-trace formula ``max(3H, 90 mil, 1×trace width)``, where ``H`` is the dielectric
    height to the reference plane from the stackup (dropped when the board declares none).
    """
    if override is not None:
        return override
    terms = [EDGE_CLEARANCE_MIL_FLOOR_MM, trace.width]
    h = board.stackup.dielectric_height(trace.layer, ref_layer)
    if h is not None:
        terms.append(3.0 * h)
    return max(terms)


def _edge_clearance(
    trace: Trace,
    candidates: list[PlaneRef],
    prep_by_key: dict[tuple[str, str], PreparedGeometry],
    board: Board,
    override: float | None,
) -> list[Finding]:
    """Flag *trace* if it hugs the edge of its reference plane below threshold (§5.1 #2).

    Only fully-referenced traces are in scope — a trace leaving the pour is an
    edge-overhang the classifier already reports, so this measures distance to the plane
    boundary only for a candidate that *covers* the whole segment. If any covering plane
    keeps the trace at or beyond its clearance threshold the return path is sound (no
    finding); otherwise the least-bad covering plane is reported.
    """
    best: tuple[float, float, PlaneRef] | None = None
    for c in candidates:
        if not prep_by_key[(c.layer, c.net)].covers(trace.line):
            continue
        threshold = _edge_clearance_threshold(trace, c.layer, board, override)
        dist = trace.line.distance(c.geom.boundary)
        if dist >= threshold:
            return []  # a covering plane gives adequate edge clearance
        if best is None or dist > best[0]:
            best = (dist, threshold, c)
    if best is None:
        return []  # no single plane covers the segment → the classifier owns it

    dist, threshold, c = best
    on_trace, _ = nearest_points(trace.line, c.geom.boundary)
    return [
        _finding(
            trace,
            "edge-clearance",
            c.layer,
            on_trace.x,
            on_trace.y,
            dist,
            f"{threshold:.2f}",
        )
    ]


# --------------------------------------------------------------------------- #
# return via at layer change (§5.1 #3)
# --------------------------------------------------------------------------- #
def _return_via_finding(
    via: Via, reference_pts: list[tuple[float, float]], distance: float, severity: str
) -> Finding | None:
    """Flag a layer-changing signal *via* with no stitch via within *distance* (§5.1 #3).

    A via that stays on one copper layer is not a reference transition and is skipped.
    Otherwise the nearest reference-net via is measured; a gap greater than *distance* (or
    no reference via at all) means the return current has no local path across the change.
    """
    if len({layer for layer in via.layers if layer.endswith(".Cu")}) < 2:
        return None
    nearest = min(
        (math.hypot(via.x - rx, via.y - ry) for rx, ry in reference_pts),
        default=math.inf,
    )
    if nearest <= distance:
        return None
    span = via.layers[0] if via.layers else "?"
    ref_span = via.layers[-1] if via.layers else "?"
    return Finding(
        check="missing-return-via",
        net=via.net,
        cls="missing-return-via",
        severity=severity,
        layer=span,
        reference_layer=ref_span,
        x=via.x,
        y=via.y,
        span_mm=0.0 if math.isinf(nearest) else nearest,
        message=_return_via_message(via.net, span, ref_span, nearest, distance),
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
    config: Config | None = None,
    net_to_netclass: Mapping[str, str] | None = None,
    min_crossing_span_mm: float = 0.1,
    sliver_ignore_area_mm2: float = 0.0065,
    sampling_tolerance_mm: float = 0.05,
    return_via_distance_mm: float = 2.0,
) -> list[Finding]:
    """Resolve each trace's reference plane(s) and classify it into the four §4.4 buckets.

    When a :class:`~returnpath.config.Config` is passed, per-net thresholds and severities
    are resolved under §6.2 precedence, the §6.1 victim set filters which nets are checked,
    and a class set to ``ignore`` (§7.1) emits nothing. Without one, the explicit threshold
    kwargs apply board-wide (the walking-skeleton path) with the §4.4 default severities.
    """
    net_to_netclass = net_to_netclass or {}
    plane_nets = {pr.net for pr in board.plane_refs}

    # A reference net is never a victim — skip any trace whose net forms a plane on this
    # board, not just those named in `reference_nets`. This keeps the skip set aligned with
    # `board.plane_refs` even when the caller passes a reference_nets that diverges from the
    # one `parse_board` built the planes with (else a power trace could self-reference).
    skip_nets = set(reference_nets) | plane_nets

    victims: set[str] | None = None
    if config is not None:
        # Signal nets span both routed traces and vias — a via-only net (a stub changing
        # layers with no segment on the checked layers) is still a return-via candidate.
        signal_nets = ({t.net for t in board.traces} | {v.net for v in board.vias}) - plane_nets
        victims = config.victims(signal_nets, net_to_netclass)
        # A board-wide geometric tolerance (the buffer below) uses the defaults layer.
        sampling_tolerance_mm = config.for_net().sampling_tolerance_mm

    # Prepare + buffer each plane once (§2 optimisation), keyed by its (layer, net) —
    # unique per plane_ref, so the lookup is self-evidently correct.
    prep_by_key = {(pr.layer, pr.net): prep(pr.geom) for pr in board.plane_refs}
    edge_by_key = {
        (pr.layer, pr.net): pr.geom.buffer(sampling_tolerance_mm) for pr in board.plane_refs
    }

    findings: list[Finding] = []
    for trace in board.traces:
        if trace.net in skip_nets:
            continue
        if victims is not None and trace.net not in victims:
            continue

        span, sliver = min_crossing_span_mm, sliver_ignore_area_mm2
        edge_override: float | None = None
        resolved = None
        if config is not None:
            resolved = config.for_net(trace.net, net_to_netclass.get(trace.net))
            span, sliver = resolved.min_crossing_span_mm, resolved.sliver_ignore_area_mm2
            edge_override = resolved.edge_clearance_mm

        candidates = _candidates(trace, board)
        raw = _classify(
            trace,
            candidates,
            prep_by_key,
            edge_by_key,
            min_crossing_span_mm=span,
            sliver_ignore_area_mm2=sliver,
        )
        raw.extend(_edge_clearance(trace, candidates, prep_by_key, board, edge_override))
        if resolved is not None:
            raw = [replace(f, severity=resolved.severity_for(f.cls)) for f in raw]
            raw = [f for f in raw if f.severity != "ignore"]
        findings.extend(raw)

    findings.extend(
        _check_return_vias(
            board,
            victims=victims,
            skip_nets=skip_nets,
            config=config,
            net_to_netclass=net_to_netclass,
            default_distance=return_via_distance_mm,
        )
    )
    return findings


def _check_return_vias(
    board: Board,
    *,
    victims: set[str] | None,
    skip_nets: set[str],
    config: Config | None,
    net_to_netclass: Mapping[str, str],
    default_distance: float,
) -> list[Finding]:
    """Run the return-via-at-layer-change check across every signal via (§5.1 #3).

    Reference-net vias (GND/power) are the stitch candidates; each signal via that changes
    layers is measured against the nearest one. Per-net ``return_via_distance_mm`` and the
    ``missing_return_via`` severity are resolved under §6 when a config is present.
    """
    reference_pts = [(v.x, v.y) for v in board.vias if v.net in skip_nets]
    findings: list[Finding] = []
    for via in board.vias:
        if via.net in skip_nets:
            continue
        if victims is not None and via.net not in victims:
            continue
        distance, severity = default_distance, SEVERITY["missing-return-via"]
        if config is not None:
            resolved = config.for_net(via.net, net_to_netclass.get(via.net))
            distance = resolved.return_via_distance_mm
            severity = resolved.severity_for("missing-return-via")
        if severity == "ignore":
            continue
        finding = _return_via_finding(via, reference_pts, distance, severity)
        if finding is not None:
            findings.append(finding)
    return findings


# Backwards-compatible alias — the walking skeleton (issue #17) named the entry point
# after its sole check; it now runs the full four-bucket classifier.
check_split_crossing = check_return_path


def _return_via_message(net: str, span: str, ref_span: str, nearest: float, distance: float) -> str:
    where = (
        "no reference-net via anywhere on the board"
        if math.isinf(nearest)
        else f"the nearest stitch via is {nearest:.2f} mm away"
    )
    return (
        f"{net} changes layer ({span}→{ref_span}) with no return/stitch via within "
        f"{distance:.2f} mm ({where}) — the return current has no local path across the change"
    )


def _message(cls: str, net: str, ref_layer: str, span: float, detail: str) -> str:
    if cls == "split-crossing":
        return (
            f"{net} crosses a {span:.2f} mm void in the {ref_layer} reference plane — "
            f"the return current has no continuous path across the gap"
        )
    if cls == "edge-clearance":
        return (
            f"{net} runs {span:.2f} mm from the {ref_layer} reference-plane edge — "
            f"closer than the {detail} mm clearance; the return path is compromised at the edge"
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
