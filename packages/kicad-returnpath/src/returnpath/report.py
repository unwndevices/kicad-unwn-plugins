"""Report formats (spec §8.2) — text, JSON, SVG overlay, and HTML.

Every format consumes the same :class:`~returnpath.detector.Finding` record (spec §8.1);
:func:`finding_record` is the single serialization of that record, so no format diverges in
the data it shows. Findings are ordered identically everywhere (errors first, then by net
and location) and numbered from 1 — the numbers on the SVG crosshairs match the HTML list.

* **text** (default) — grouped, severity-iconed console output with an error/warning/info
  tally and a muted ``Waived (N)`` section; never drops a waived finding.
* **JSON** (CI) — a list of canonical finding records; a waived finding additionally
  carries ``waived: true`` + ``reason``.
* **SVG overlay** — findings in board space: copper islands, traces, and numbered
  severity-coloured crosshairs; waived findings drawn muted (hollow/grey).
* **HTML** — a self-contained document embedding the SVG overlay + the finding list.
"""

from __future__ import annotations

import json
from typing import Any

from shapely.geometry.base import BaseGeometry

from .detector import Finding
from .parser import Board

# Severity ordering shared by the report grouping and the CLI exit gate.
SEVERITY_ORDER = {"ignore": 0, "info": 1, "warning": 2, "error": 3}

_ICON = {"error": "✗", "warning": "⚠", "info": "ℹ"}
_LABEL = {"error": "ERROR", "warning": "WARN", "info": "INFO"}

# The report formats the CLI (§10) exposes, in preference order.
REPORT_FORMATS = ("text", "json", "svg", "html")

# Filename extension per format, for ``--out-dir`` (§10).
FORMAT_EXT = {"text": "txt", "json": "json", "svg": "svg", "html": "html"}

# Severity → crosshair colour for the SVG/HTML overlay (waived overrides to grey).
_SEVERITY_COLOR = {"error": "#d23b3b", "warning": "#e08a1e", "info": "#3a80c8"}
_WAIVED_COLOR = "#9aa0a6"


def format_text_report(board_name: str, findings: list[Finding]) -> str:
    """Render *findings* for *board_name* as a grouped, iconed text report.

    Waived findings (``f.waived``) are split into a muted ``Waived (N)`` section and excluded
    from the active tally, mirroring the exit-code rule that counts unwaived findings only.
    """
    active = [f for f in findings if not f.waived]
    waived = [f for f in findings if f.waived]

    lines = [f"return-path check: {board_name}", ""]

    if not active:
        lines.append("  ✓ no return-path findings")
    else:
        for f in _ordered(active):
            lines.extend(_finding_lines(f))

    lines.append("")
    lines.append(f"Summary: {_tally(active)}")

    if waived:
        lines.append("")
        lines.append(f"Waived ({len(waived)}):")
        for f in _ordered(waived):
            lines.append(
                f"  · {f.id}  {f.cls:14s} {f.net}  ({f.x:.2f}, {f.y:.2f}) mm"
                + (f"  — {f.waiver_reason}" if f.waiver_reason else "")
            )

    return "\n".join(lines)


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-SEVERITY_ORDER.get(f.severity, 0), f.net, f.y, f.x))


def _finding_lines(f: Finding) -> list[str]:
    icon = _ICON.get(f.severity, "·")
    label = _LABEL.get(f.severity, f.severity.upper())
    return [
        f"  {icon} {label:5s} {f.cls:14s} {f.net}  "
        f"{f.layer}→{f.reference_layer}  "
        f"({f.x:.2f}, {f.y:.2f}) mm  span {f.span_mm:.2f} mm  [{f.id}]",
        f"      {f.message}",
    ]


def _tally(findings: list[Finding]) -> str:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        if f.severity in counts:
            counts[f.severity] += 1
    parts = [
        f"{counts['error']} error{'s' if counts['error'] != 1 else ''}",
        f"{counts['warning']} warning{'s' if counts['warning'] != 1 else ''}",
    ]
    if counts["info"]:
        parts.append(f"{counts['info']} info")
    return ", ".join(parts)


# --------------------------------------------------------------------------- #
# canonical record (spec §8.1) — the one serialization every format shares
# --------------------------------------------------------------------------- #
def finding_record(f: Finding) -> dict[str, object]:
    """The canonical finding record (spec §8.1) as a plain dict.

    ``check · net · class · severity · layer · reference_layer · location{x,y} · span_mm ·
    message`` — plus the content-hash ``id`` (so a reviewer can ``--waive`` it from JSON).
    A waived finding additionally carries ``waived: true`` + ``reason`` and is **never
    silently dropped** (§8.1).
    """
    record: dict[str, object] = {
        "check": f.check,
        "net": f.net,
        "class": f.cls,
        "severity": f.severity,
        "layer": f.layer,
        "reference_layer": f.reference_layer,
        "location": {"x": f.x, "y": f.y},
        "span_mm": f.span_mm,
        "message": f.message,
    }
    if f.id:
        record["id"] = f.id
    if f.waived:
        record["waived"] = True
        record["reason"] = f.waiver_reason
    return record


def format_json_report(board_name: str, findings: list[Finding]) -> str:
    """Render *findings* as a JSON list of canonical records (spec §8.2, CI format).

    Waived findings stay in the list carrying ``waived: true`` + ``reason`` (§8.1). Ordering
    matches every other format so the crosshair numbers line up. *board_name* is unused in
    the payload (a bare list per §8.2) but kept for a uniform format signature.
    """
    return json.dumps([finding_record(f) for f in _ordered(findings)], indent=2)


# --------------------------------------------------------------------------- #
# SVG overlay (spec §8.2) — findings in board space
# --------------------------------------------------------------------------- #
def format_svg_report(board_name: str, findings: list[Finding], board: Board) -> str:
    """Render the board's copper + numbered severity-coloured finding crosshairs as SVG.

    Copper islands (the reference planes) and traces are drawn in board millimetres (KiCad
    and SVG share a y-down frame, so coordinates pass through unflipped); each finding gets a
    numbered crosshair coloured by severity, waived ones drawn muted (grey, hollow, dashed).
    The numbers match :func:`format_json_report`/:func:`format_html_report` ordering.
    """
    ordered = _ordered(findings)
    minx, miny, maxx, maxy = _bounds(board, ordered)
    pad = 2.0
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    w, h = maxx - minx, maxy - miny

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.3f}mm" height="{h:.3f}mm" '
        f'viewBox="{minx:.3f} {miny:.3f} {w:.3f} {h:.3f}">',
        f"  <title>return-path overlay: {_esc(board_name)}</title>",
        f'  <rect x="{minx:.3f}" y="{miny:.3f}" width="{w:.3f}" height="{h:.3f}" fill="#111417"/>',
    ]

    # copper islands (reference planes) then routed traces, beneath the crosshairs.
    for geom in board.planes.values():
        d = _polygon_path(geom)
        if d:
            parts.append(
                f'  <path d="{d}" fill="#204a2e" fill-rule="evenodd" '
                f'stroke="#3a7d54" stroke-width="0.05"/>'
            )
    for trace in board.traces:
        pts = _line_points(trace.line)
        if pts:
            parts.append(
                f'  <polyline points="{pts}" fill="none" stroke="#c9a227" '
                f'stroke-width="{max(trace.width, 0.05):.3f}" stroke-linecap="round" '
                f'stroke-linejoin="round" opacity="0.85"/>'
            )

    for n, f in enumerate(ordered, 1):
        parts.append(_crosshair(n, f))

    parts.append("</svg>")
    return "\n".join(parts)


def _crosshair(n: int, f: Finding) -> str:
    color = _WAIVED_COLOR if f.waived else _SEVERITY_COLOR.get(f.severity, _WAIVED_COLOR)
    r = 1.4
    dash = ' stroke-dasharray="0.4 0.3"' if f.waived else ""
    fill = "none"
    label = f'<text x="{f.x + r + 0.4:.3f}" y="{f.y + r:.3f}" font-size="2.2" fill="{color}" '
    label += f'font-family="monospace">{n}</text>'
    return (
        f'  <g stroke="{color}" stroke-width="0.18"{dash}>\n'
        f'    <circle cx="{f.x:.3f}" cy="{f.y:.3f}" r="{r:.3f}" fill="{fill}"/>\n'
        f'    <line x1="{f.x - r * 1.6:.3f}" y1="{f.y:.3f}" '
        f'x2="{f.x + r * 1.6:.3f}" y2="{f.y:.3f}"/>\n'
        f'    <line x1="{f.x:.3f}" y1="{f.y - r * 1.6:.3f}" '
        f'x2="{f.x:.3f}" y2="{f.y + r * 1.6:.3f}"/>\n'
        f"    {label}\n"
        f"  </g>"
    )


def _bounds(board: Board, findings: list[Finding]) -> tuple[float, float, float, float]:
    """Union bounding box of copper, traces and finding crosshairs (a 1 mm default box)."""
    xs: list[float] = []
    ys: list[float] = []
    for geom in board.planes.values():
        if not geom.is_empty:
            gx0, gy0, gx1, gy1 = geom.bounds
            xs += [gx0, gx1]
            ys += [gy0, gy1]
    for trace in board.traces:
        if not trace.line.is_empty:
            tx0, ty0, tx1, ty1 = trace.line.bounds
            xs += [tx0, tx1]
            ys += [ty0, ty1]
    for f in findings:
        xs.append(f.x)
        ys.append(f.y)
    if not xs or not ys:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_path(geom: BaseGeometry) -> str:
    """An SVG path ``d`` (exterior + holes, even-odd) for a Polygon/MultiPolygon."""
    if geom.is_empty:
        return ""
    polys: list[Any] = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    rings: list[str] = []
    for poly in polys:
        if poly.is_empty or not hasattr(poly, "exterior"):
            continue
        rings.append(_ring_path(poly.exterior.coords))
        for interior in poly.interiors:
            rings.append(_ring_path(interior.coords))
    return " ".join(r for r in rings if r)


def _ring_path(coords: Any) -> str:
    pts = list(coords)
    if not pts:
        return ""
    head = f"M {pts[0][0]:.3f} {pts[0][1]:.3f}"
    body = " ".join(f"L {x:.3f} {y:.3f}" for x, y in pts[1:])
    return f"{head} {body} Z".strip()


def _line_points(line: BaseGeometry) -> str:
    coords: Any = line.coords
    return " ".join(f"{x:.3f},{y:.3f}" for x, y in coords)


# --------------------------------------------------------------------------- #
# HTML (spec §8.2) — self-contained overlay + finding list
# --------------------------------------------------------------------------- #
def format_html_report(board_name: str, findings: list[Finding], board: Board) -> str:
    """A self-contained HTML document embedding the SVG overlay + numbered finding list."""
    ordered = _ordered(findings)
    svg = format_svg_report(board_name, findings, board)
    rows = "\n".join(_html_row(n, f) for n, f in enumerate(ordered, 1))
    active = [f for f in ordered if not f.waived]
    waived = [f for f in ordered if f.waived]
    summary = _tally(active)
    waived_note = f" · {len(waived)} waived" if waived else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>return-path report: {_esc(board_name)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.2rem; }}
  .summary {{ color: #555; margin-bottom: 1rem; }}
  svg {{ max-width: 100%; height: auto; border: 1px solid #ccc; }}
  table {{ border-collapse: collapse; margin-top: 1rem; width: 100%; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 0.3rem 0.6rem; border-bottom: 1px solid #eee; }}
  .error {{ color: #d23b3b; }}
  .warning {{ color: #b8730f; }}
  .info {{ color: #3a80c8; }}
  tr.waived {{ color: #9aa0a6; }}
</style>
</head>
<body>
<h1>return-path report: {_esc(board_name)}</h1>
<div class="summary">Summary: {_esc(summary)}{_esc(waived_note)}</div>
{svg}
<table>
<thead><tr><th>#</th><th>severity</th><th>class</th><th>net</th><th>layer</th>
<th>location (mm)</th><th>span (mm)</th><th>message</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def _html_row(n: int, f: Finding) -> str:
    cls_attr = "waived" if f.waived else ""
    sev_cls = "waived" if f.waived else f.severity
    msg = _esc(f.message)
    if f.waived and f.waiver_reason:
        msg += f" <em>(waived: {_esc(f.waiver_reason)})</em>"
    return (
        f'<tr class="{cls_attr}">'
        f"<td>{n}</td>"
        f'<td class="{sev_cls}">{_esc(f.severity)}</td>'
        f"<td>{_esc(f.cls)}</td>"
        f"<td>{_esc(f.net)}</td>"
        f"<td>{_esc(f.layer)}→{_esc(f.reference_layer)}</td>"
        f"<td>({f.x:.2f}, {f.y:.2f})</td>"
        f"<td>{f.span_mm:.2f}</td>"
        f"<td>{msg}</td>"
        f"</tr>"
    )


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# --------------------------------------------------------------------------- #
# dispatch (used by the CLI §10)
# --------------------------------------------------------------------------- #
def render_report(fmt: str, board_name: str, findings: list[Finding], board: Board) -> str:
    """Render *findings* in *fmt* (one of :data:`REPORT_FORMATS`)."""
    if fmt == "text":
        return format_text_report(board_name, findings)
    if fmt == "json":
        return format_json_report(board_name, findings)
    if fmt == "svg":
        return format_svg_report(board_name, findings, board)
    if fmt == "html":
        return format_html_report(board_name, findings, board)
    raise ValueError(f"unknown report format: {fmt}")
