#!/usr/bin/env python3
"""Throwaway prototype for wayfinder ticket #9 — "Prototype the findings report
and board overlay UX".

Reuses the #6 spike's detection to produce three concrete presentation
artifacts to react to:

  1. a console text report (default CLI output),
  2. a JSON findings file (--format json, for CI),
  3. an SVG board overlay (findings marked in board space).

The in-KiCad overlay is *described* in the ticket resolution, not built here —
it needs a live KiCad 10 IPC session (see #4). This prototype is about the
shapes: the finding record, how a report reads, and what an overlay looks like.

Run:  python report.py            # writes report.txt, findings.json, overlay.svg
"""
from __future__ import annotations

import json
from pathlib import Path

import spike  # the #6 detector, imported as a module

# --- finding record schema (the canonical unit both report + overlay consume) -
# One dict per finding. Class comes from the #7 taxonomy; severity is a
# placeholder here (real values are #12's call).
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def detect(board_path: Path) -> list[dict]:
    board = spike.load_board(board_path)
    plane = spike.reference_plane(board)
    traces = spike.signal_traces(board, net_num=2)
    findings = []
    for i, trace in enumerate(traces):
        for gap in spike.find_crossings(trace, plane):
            mid = gap.interpolate(0.5, normalized=True)
            # crude class split: a span whose ends both sit on plane copper is
            # an internal split; one that touches the plane bbox edge is an
            # overhang. (The real geometric test is #11's job.)
            touches_edge = not plane.buffer(-0.01).contains(
                gap.interpolate(0.0)
            ) and gap.interpolate(0.0).distance(plane) > 0.5
            klass = "edge_overhang" if touches_edge else "split_crossing"
            findings.append({
                "check": "plane_gap_crossing",
                "net": "SIG_FAST",
                "class": klass,
                "severity": "error" if klass == "split_crossing" else "warning",
                "layer": "F.Cu",
                "reference_layer": "B.Cu",
                "location": {"x": round(mid.x, 3), "y": round(mid.y, 3)},
                "span_mm": round(gap.length, 3),
                "message": (
                    f"Trace on net 'SIG_FAST' crosses a split in its B.Cu "
                    f"reference plane ({gap.length:.1f} mm unbacked)."
                    if klass == "split_crossing" else
                    f"Trace on net 'SIG_FAST' runs {gap.length:.1f} mm past the "
                    f"edge of its B.Cu reference pour."
                ),
                "_geom": gap,  # kept for the SVG; stripped from JSON
            })
    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    return findings


# --- 1. console text report -------------------------------------------------
def render_text(findings: list[dict], board_name: str) -> str:
    icon = {"error": "✗", "warning": "▲", "info": "•"}
    n_err = sum(f["severity"] == "error" for f in findings)
    n_warn = sum(f["severity"] == "warning" for f in findings)
    lines = [
        f"return-path check — {board_name}",
        f"{'─' * 52}",
    ]
    for f in findings:
        loc = f["location"]
        lines.append(
            f"  {icon[f['severity']]} [{f['class']}] net {f['net']} "
            f"@ ({loc['x']:.1f}, {loc['y']:.1f}) mm  span {f['span_mm']:.1f} mm"
        )
        lines.append(f"      {f['message']}")
    lines.append(f"{'─' * 52}")
    lines.append(f"  {n_err} error(s), {n_warn} warning(s)")
    return "\n".join(lines)


# --- 2. JSON findings -------------------------------------------------------
def render_json(findings: list[dict], board_name: str) -> str:
    clean = [{k: v for k, v in f.items() if not k.startswith("_")}
             for f in findings]
    return json.dumps(
        {"board": board_name, "tool": "returnpath", "version": "0", "findings": clean},
        indent=2,
    )


# --- 3. SVG board overlay ---------------------------------------------------
def render_svg(board, findings: list[dict]) -> str:
    plane = spike.reference_plane(board)
    traces = spike.signal_traces(board, net_num=2)
    W, H, PAD = 50, 40, 6
    sc = 8  # px per mm

    def X(x): return (x + PAD) * sc
    def Y(y): return (y + PAD) * sc

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{(W + 2 * PAD) * sc}" height="{(H + 2 * PAD) * sc}" '
        f'style="background:#0b0f14;font-family:monospace">',
        f'<rect x="{X(0)}" y="{Y(0)}" width="{W*sc}" height="{H*sc}" '
        f'fill="none" stroke="#3a4655" stroke-width="1"/>',
    ]
    # reference plane islands (copper)
    polys = plane.geoms if plane.geom_type == "MultiPolygon" else [plane]
    for poly in polys:
        pts = " ".join(f"{X(x)},{Y(y)}" for x, y in poly.exterior.coords)
        parts.append(f'<polygon points="{pts}" fill="#173a2a" '
                     f'stroke="#2e6b4e" stroke-width="1"/>')
    # traces
    for t in traces:
        (x0, y0), (x1, y1) = t.coords[0], t.coords[1]
        parts.append(f'<line x1="{X(x0)}" y1="{Y(y0)}" x2="{X(x1)}" '
                     f'y2="{Y(y1)}" stroke="#c9a227" stroke-width="2"/>')
    # finding markers
    color = {"error": "#ff5555", "warning": "#ffb454"}
    for n, f in enumerate(findings, 1):
        loc = f["location"]
        cx, cy = X(loc["x"]), Y(loc["y"])
        c = color[f["severity"]]
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="none" '
                     f'stroke="{c}" stroke-width="2"/>')
        parts.append(f'<line x1="{cx-13}" y1="{cy}" x2="{cx+13}" y2="{cy}" '
                     f'stroke="{c}" stroke-width="1"/>')
        parts.append(f'<line x1="{cx}" y1="{cy-13}" x2="{cx}" y2="{cy+13}" '
                     f'stroke="{c}" stroke-width="1"/>')
        parts.append(f'<text x="{cx+12}" y="{cy-10}" fill="{c}" '
                     f'font-size="13">{n}</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def main() -> None:
    here = Path(__file__).parent
    board_path = here / "sample.kicad_pcb"
    findings = detect(board_path)
    board = spike.load_board(board_path)

    (here / "report.txt").write_text(render_text(findings, board_path.name))
    (here / "findings.json").write_text(render_json(findings, board_path.name))
    (here / "overlay.svg").write_text(render_svg(board, findings))
    print(render_text(findings, board_path.name))
    print(f"\nwrote report.txt, findings.json, overlay.svg to {here}")


if __name__ == "__main__":
    main()
