"""Text report (spec §8.2) — the default, human-facing output.

Findings are grouped by severity (errors first), each rendered as one iconed line
plus its message, and closed with an error/warning/info tally. This is the only
format in the walking skeleton; JSON/SVG/HTML land in a later issue.
"""

from __future__ import annotations

from .detector import Finding

# Severity ordering shared by the report grouping and the CLI exit gate.
SEVERITY_ORDER = {"ignore": 0, "info": 1, "warning": 2, "error": 3}

_ICON = {"error": "✗", "warning": "⚠", "info": "ℹ"}
_LABEL = {"error": "ERROR", "warning": "WARN", "info": "INFO"}


def format_text_report(board_name: str, findings: list[Finding]) -> str:
    """Render *findings* for *board_name* as a grouped, iconed text report."""
    lines = [f"return-path check: {board_name}", ""]

    if not findings:
        lines.append("  ✓ no return-path findings")
        lines.append("")
        lines.append("Summary: 0 errors, 0 warnings")
        return "\n".join(lines)

    ordered = sorted(
        findings,
        key=lambda f: (-SEVERITY_ORDER.get(f.severity, 0), f.net, f.y, f.x),
    )
    for f in ordered:
        icon = _ICON.get(f.severity, "·")
        label = _LABEL.get(f.severity, f.severity.upper())
        lines.append(
            f"  {icon} {label:5s} {f.cls:14s} {f.net}  "
            f"{f.layer}→{f.reference_layer}  "
            f"({f.x:.2f}, {f.y:.2f}) mm  span {f.span_mm:.2f} mm"
        )
        lines.append(f"      {f.message}")

    lines.append("")
    lines.append(f"Summary: {_tally(findings)}")
    return "\n".join(lines)


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
