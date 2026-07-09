#!/usr/bin/env python3
"""Throwaway spike for wayfinder ticket #6 — "Validate the geometry pipeline on
a real board".

Question under test: can we parse a real .kicad_pcb with the repo's *own*
S-expression parser and compute reference-plane geometry with Shapely well
enough to detect a plane-gap (return-path split) crossing? Is it fast enough?

Approach:
  1. Parse the board with captouch.sexpr.loads (the parser the repo already
     ships for round-tripping its own emitted footprints).
  2. Build the reference plane on B.Cu = union of the GND zone's filled_polygon
     islands (Shapely).
  3. Build each signal trace on F.Cu as a Shapely LineString (centreline).
  4. A plane-gap crossing = the part of a trace whose centreline is NOT covered
     by the reference plane. `trace.difference(plane)` gives those sub-segments.
  5. Report crossings with their midpoint and length; time the whole thing.

Run:  python spike.py [path/to/board.kicad_pcb]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Reuse the repo's own parser — no kiutils, no new dependency.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from captouch.sexpr import loads, find, find_all, head, children  # noqa: E402

from shapely.geometry import LineString, Polygon, MultiPolygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def _tok(x):
    """Unwrap a bare Sym token (or leave quoted strings/atoms as-is)."""
    return x.name if hasattr(x, "name") else x


def _num(x) -> float:
    return float(_tok(x))


def _pts(node) -> list[tuple[float, float]]:
    """Extract (x, y) pairs from a (pts (xy ..) (xy ..) ...) node."""
    pts_node = find(node, "pts")
    out = []
    for xy in find_all(pts_node, "xy"):
        _, x, y = xy  # (xy X Y)
        out.append((_num(x), _num(y)))
    return out


def _attr(node, name):
    """First atom after a named child head, e.g. (layer "B.Cu") -> "B.Cu"."""
    child = find(node, name)
    return None if child is None else child[1]


def load_board(path: Path):
    return loads(path.read_text())


def reference_plane(board, net_name="GND", layer="B.Cu"):
    """Union of all filled_polygon islands of the given zone/layer."""
    islands = []
    for zone in find_all(board, "zone"):
        if str(_attr(zone, "net_name")) != net_name:
            continue
        for fp in find_all(zone, "filled_polygon"):
            if str(_attr(fp, "layer")) != layer:
                continue
            islands.append(Polygon(_pts(fp)))
    return unary_union(islands) if islands else Polygon()


def signal_traces(board, net_num, layer="F.Cu"):
    lines = []
    for seg in find_all(board, "segment"):
        if str(_attr(seg, "layer")) != layer:
            continue
        net = find(seg, "net")
        if net is None or int(_tok(net[1])) != net_num:
            continue
        start, end = find(seg, "start"), find(seg, "end")
        lines.append(
            LineString(
                [(_num(start[1]), _num(start[2])), (_num(end[1]), _num(end[2]))]
            )
        )
    return lines


def find_crossings(trace: LineString, plane) -> list[LineString]:
    """Sub-segments of the trace not covered by the reference plane."""
    uncovered = trace.difference(plane)
    if uncovered.is_empty:
        return []
    if uncovered.geom_type == "LineString":
        return [uncovered]
    return [g for g in uncovered.geoms if g.geom_type == "LineString"]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name(
        "sample.kicad_pcb"
    )

    t0 = time.perf_counter()
    board = load_board(path)
    t_parse = time.perf_counter()

    plane = reference_plane(board)
    traces = signal_traces(board, net_num=2)
    t_build = time.perf_counter()

    findings = []
    for i, trace in enumerate(traces):
        for gap in find_crossings(trace, plane):
            mid = gap.interpolate(0.5, normalized=True)
            findings.append((i, mid.x, mid.y, gap.length))
    t_check = time.perf_counter()

    area = plane.area if not plane.is_empty else 0.0
    n_islands = len(plane.geoms) if isinstance(plane, MultiPolygon) else 1
    print(f"board:            {path.name}")
    print(f"reference plane:  {area:.1f} mm^2 in {n_islands} island(s) on B.Cu")
    print(f"signal traces:    {len(traces)} segment(s) on net 2 (F.Cu)")
    print(f"plane-gap crossings detected: {len(findings)}")
    for i, x, y, length in findings:
        print(f"  - trace #{i}: crosses split at ({x:.2f}, {y:.2f}) mm, "
              f"span {length:.2f} mm")
    print()
    print("timing:")
    print(f"  parse (own sexpr): {(t_parse - t0) * 1e3:8.3f} ms")
    print(f"  build geometry:    {(t_build - t_parse) * 1e3:8.3f} ms")
    print(f"  crossing check:    {(t_check - t_build) * 1e3:8.3f} ms")
    print(f"  total:             {(t_check - t0) * 1e3:8.3f} ms")


if __name__ == "__main__":
    main()
