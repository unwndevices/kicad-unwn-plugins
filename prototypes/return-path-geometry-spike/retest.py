#!/usr/bin/env python3
"""Retest for wayfinder ticket #13 — "Retest the geometry pipeline on a real
exported board".

#6 green-lit the parse->Shapely->detect pipeline on a *hand-authored* 2-net
sample. This retest re-runs it against a **real, pcbnew-exported multi-net
board** (`../hydro_ctrl/hydro_ctrl.kicad_pcb`, KiCad file version 20260206) to
confirm the pipeline holds at real scale and to surface schema drift the toy
sample hid.

Key differences the real board forces us to handle (vs. `spike.py`):
  1. **Name-based nets.** KiCad 10 drops net numbers from the board body:
     `(net "GND")`, not `(net 1)` / `(net_name "GND")`. spike.py filtered on a
     net *number* and a zone `(net_name ...)` child — both absent here, so the
     old code would have silently found an empty plane and zero traces.
  2. **Multi-layer zones.** One GND `(zone)` fills three layers via
     `(layers "F.Cu" "B.Cu" "In2.Cu")`; the reference plane must be selected by
     the `filled_polygon`'s own `(layer ...)`, not the zone's.
  3. **Real fill scale.** Fills carry up to ~17k vertices (thermal reliefs and
     via antipads woven into one ring); the In2.Cu GND plane is ~10.4k verts.
     This is the timing stress the toy sample could not provide.

Return-path scenario under test: **B.Cu signal traces against the In2.Cu GND
plane** — the genuine adjacent reference plane on this 4-layer stackup
(F.Cu / In1.Cu / In2.Cu / B.Cu).

Run:  python retest.py [path/to/board.kicad_pcb]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from captouch.sexpr import loads, find, find_all  # noqa: E402

from shapely.geometry import LineString, Point, Polygon, MultiPolygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402

# #11 default: an uncovered span shorter than this is a fill sliver, not a
# crossing. On this board it drops the sub-antipad noise cleanly.
MIN_CROSSING_SPAN_MM = 0.1

DEFAULT_BOARD = Path(__file__).resolve().parents[2].parent / "hydro_ctrl" / "hydro_ctrl.kicad_pcb"


def _tok(x):
    return x.name if hasattr(x, "name") else x


def _num(x) -> float:
    return float(_tok(x))


def _pts(node) -> list[tuple[float, float]]:
    out = []
    for xy in find_all(find(node, "pts"), "xy"):
        _, x, y = xy
        out.append((_num(x), _num(y)))
    return out


def _named(node, name):
    """The single string/atom net-or-layer name: (net "GND") -> "GND"."""
    child = find(node, name)
    return None if child is None else str(_tok(child[1]))


def reference_plane(board, net_name="GND", layer="In2.Cu"):
    """Union of every GND filled_polygon that sits on `layer`.

    Note: matches the *filled_polygon*'s own layer, because a single zone can
    span several layers (`(layers ...)`).
    """
    islands = []
    for zone in find_all(board, "zone"):
        if _named(zone, "net") != net_name:
            continue
        for fp in find_all(zone, "filled_polygon"):
            if _named(fp, "layer") != layer:
                continue
            islands.append(Polygon(_pts(fp)))
    return unary_union(islands) if islands else Polygon()


def signal_traces(board, net_name, layer):
    lines = []
    for seg in find_all(board, "segment"):
        if _named(seg, "layer") != layer or _named(seg, "net") != net_name:
            continue
        s, e = find(seg, "start"), find(seg, "end")
        lines.append(LineString([(_num(s[1]), _num(s[2])), (_num(e[1]), _num(e[2]))]))
    return lines


def classify(trace, plane, plane_edge, tol=0.05):
    """Split a trace into uncovered spans and label each. A gap whose *both*
    endpoints sit on the plane is an internal split (candidate return-path
    defect); a gap with a free end is a terminus/antipad over-run (the trace
    running off the pour into a pad or via clearance — benign).

    `plane_edge` is the plane buffered by `tol` ONCE by the caller; buffering a
    ~10k-vertex polygon per gap is what made the first cut 25x too slow.
    """
    uncovered = trace.difference(plane)
    if uncovered.is_empty:
        return []
    geoms = uncovered.geoms if uncovered.geom_type == "MultiLineString" else [uncovered]
    out = []
    for g in geoms:
        if g.geom_type != "LineString" or g.length < 1e-6:
            continue
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        both_on = plane_edge.contains(a) and plane_edge.contains(b)
        out.append((g, "internal-split" if both_on else "terminus-overrun"))
    return out


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BOARD

    t0 = time.perf_counter()
    board = loads(path.read_text())
    t_parse = time.perf_counter()

    plane = reference_plane(board, "GND", "In2.Cu")
    plane_edge = plane.buffer(0.05)           # buffered ONCE, reused per gap
    prepared = prep(plane)                     # cheap "fully covered?" reject
    t_build = time.perf_counter()

    # every signal net that has B.Cu copper, excluding GND itself
    bcu_nets = sorted({
        _named(s, "net") for s in find_all(board, "segment")
        if _named(s, "layer") == "B.Cu" and _named(s, "net") not in (None, "GND")
    })
    traces = [(net, tr) for net in bcu_nets for tr in signal_traces(board, net, "B.Cu")]

    n_verts = (sum(len(g.exterior.coords) for g in plane.geoms)
               if isinstance(plane, MultiPolygon)
               else 0 if plane.is_empty else len(plane.exterior.coords))
    n_islands = len(plane.geoms) if isinstance(plane, MultiPolygon) else (0 if plane.is_empty else 1)

    raw, defects = [], []
    t_check0 = time.perf_counter()
    for net, trace in traces:
        if prepared.covers(trace):             # wholly over copper -> skip
            continue
        for gap, kind in classify(trace, plane, plane_edge):
            mid = gap.interpolate(0.5, normalized=True)
            raw.append((net, kind, mid.x, mid.y, gap.length))
            if kind == "internal-split" and gap.length >= MIN_CROSSING_SPAN_MM:
                defects.append((net, mid.x, mid.y, gap.length))
    t_check = time.perf_counter()

    n_split = sum(1 for f in raw if f[1] == "internal-split")
    n_over = sum(1 for f in raw if f[1] == "terminus-overrun")
    n_sub = sum(1 for f in raw if f[4] < MIN_CROSSING_SPAN_MM)
    print(f"board:            {path.name}  (file version {_named(board, 'version')})")
    print(f"reference plane:  {plane.area:.1f} mm^2, {n_islands} island(s), "
          f"{n_verts} vertices on In2.Cu (GND)")
    print(f"B.Cu signal nets: {len(bcu_nets)}, {len(traces)} trace segments")
    print(f"raw uncovered spans: {len(raw)}  "
          f"({n_split} internal-split, {n_over} terminus-overrun; "
          f"{n_sub} below {MIN_CROSSING_SPAN_MM} mm sliver floor)")
    print(f"return-path DEFECTS (internal-split >= {MIN_CROSSING_SPAN_MM} mm): {len(defects)}")
    for net, x, y, length in defects:
        print(f"  - {net:20s} split at ({x:.2f}, {y:.2f}) mm  span {length:.2f} mm")
    print()
    print("timing:")
    print(f"  parse (own sexpr):      {(t_parse - t0) * 1e3:9.3f} ms")
    print(f"  build + prep plane:     {(t_build - t_parse) * 1e3:9.3f} ms")
    print(f"  crossing check (all):   {(t_check - t_check0) * 1e3:9.3f} ms")
    print(f"  total:                  {(t_check - t0) * 1e3:9.3f} ms")


if __name__ == "__main__":
    main()
