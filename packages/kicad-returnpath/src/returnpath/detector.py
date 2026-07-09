"""Detectors — the split-crossing check (§5.1 #1) and the finding record.

The one check in this walking skeleton: for every routed trace, subtract the
reference plane (``trace.difference(plane)``) to get its uncovered spans, drop the
noise (spans below ``min_crossing_span_mm``), then apply the **both-ends-on-plane**
interior predicate (§4.4) to each survivor:

* both endpoints land on reference copper of the same plane → **split-crossing** (the
  trace re-enters copper on the far side; the gap is an internal void/slot). *The defect.*
* a free-ended span (an endpoint off the pour) → **edge-overhang** (the trace simply
  leaves the plane — a benign terminus/antipad over-run).

That interior test is *required*, not optional: on the retest board it dropped 89 of
91 raw spans as benign terminus over-runs.

Reference-plane *identification* proper (stackup adjacency, GND + power, the declared
Track Propagation table) is spec §4 and lands in a later issue. This skeleton uses the
simplest defensible rule: a trace is checked against each reference plane on a layer
*other than its own* (same-layer copper is held back from the trace by clearance, so it
never covers it). Each such plane is reported with its own ``reference_layer``.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from .parser import Board, Trace

# §4.4 default severities for the classes this build emits.
SEVERITY = {"split-crossing": "error", "edge-overhang": "warning"}


@dataclass(frozen=True)
class Finding:
    """The canonical finding record (spec §8.1) — shared by every report format."""

    check: str  # detector that produced it, e.g. "split-crossing"
    net: str
    cls: str  # "split-crossing" | "edge-overhang"
    severity: str  # "error" | "warning" | "info"
    layer: str  # the trace's layer
    reference_layer: str  # the plane layer the span was measured against
    x: float
    y: float
    span_mm: float
    message: str


def _classify_spans(
    trace: Trace,
    plane: BaseGeometry,
    plane_edge: BaseGeometry,
    min_crossing_span_mm: float,
    sliver_ignore_area_mm2: float,
) -> list[tuple[float, float, float, str]]:
    """Return ``(x, y, span_mm, cls)`` for each reportable uncovered span of *trace*.

    A span is dropped when it is shorter than ``min_crossing_span_mm`` or when the
    uncovered copper it represents (``span length × trace width``) is below
    ``sliver_ignore_area_mm2`` — the §5.1 noise floors, applied *before* the §4.4
    both-ends-on-plane predicate labels the survivors.

    ``plane_edge`` is ``plane`` buffered by the sampling tolerance **once** by the
    caller — buffering a ~10k-vertex polygon per span is what made the first cut of
    the spike 25x too slow.
    """
    uncovered = trace.line.difference(plane)
    if uncovered.is_empty:
        return []
    geoms = uncovered.geoms if uncovered.geom_type == "MultiLineString" else [uncovered]

    out: list[tuple[float, float, float, str]] = []
    for g in geoms:
        if g.geom_type != "LineString" or g.length < min_crossing_span_mm:
            continue
        if g.length * trace.width < sliver_ignore_area_mm2:
            continue
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        both_on = plane_edge.contains(a) and plane_edge.contains(b)
        cls = "split-crossing" if both_on else "edge-overhang"
        mid = g.interpolate(0.5, normalized=True)
        out.append((mid.x, mid.y, g.length, cls))
    return out


def check_split_crossing(
    board: Board,
    *,
    reference_nets: tuple[str, ...] = ("GND",),
    min_crossing_span_mm: float = 0.1,
    sliver_ignore_area_mm2: float = 0.0065,
    sampling_tolerance_mm: float = 0.05,
) -> list[Finding]:
    """Run the split-crossing check over every non-reference trace on *board*."""
    findings: list[Finding] = []

    # Buffer + prepare each plane once, not per trace.
    prepared = {layer: prep(plane) for layer, plane in board.planes.items()}
    edges = {layer: plane.buffer(sampling_tolerance_mm) for layer, plane in board.planes.items()}

    for trace in board.traces:
        if trace.net in reference_nets:
            continue
        for ref_layer, plane in board.planes.items():
            if ref_layer == trace.layer:
                continue  # same-layer copper is clearance-held-back; never a reference
            if prepared[ref_layer].covers(trace.line):
                continue  # wholly over copper — solid return path
            for x, y, span, cls in _classify_spans(
                trace, plane, edges[ref_layer], min_crossing_span_mm, sliver_ignore_area_mm2
            ):
                findings.append(
                    Finding(
                        check="split-crossing",
                        net=trace.net,
                        cls=cls,
                        severity=SEVERITY[cls],
                        layer=trace.layer,
                        reference_layer=ref_layer,
                        x=x,
                        y=y,
                        span_mm=span,
                        message=_message(cls, trace.net, ref_layer, span),
                    )
                )
    return findings


def _message(cls: str, net: str, ref_layer: str, span: float) -> str:
    if cls == "split-crossing":
        return (
            f"{net} crosses a {span:.2f} mm void in the {ref_layer} reference plane — "
            f"the return current has no continuous path across the gap"
        )
    return (
        f"{net} runs {span:.2f} mm past the edge of the {ref_layer} reference plane — "
        f"unreferenced over-run (verify it is not a real plane shortfall)"
    )
