"""Text report (spec §8.2) — the default, human-facing output.

Active findings are grouped by severity (errors first), each rendered as one iconed line
(carrying its content-hash id so a reviewer can ``--waive`` it) plus its message, and
closed with an error/warning/info tally. Waived findings (spec §7.2 / §8.1) are carried in
a muted ``Waived (N)`` section — never silently dropped. JSON/SVG/HTML land in a later
issue.
"""

from __future__ import annotations

from .detector import Finding

# Severity ordering shared by the report grouping and the CLI exit gate.
SEVERITY_ORDER = {"ignore": 0, "info": 1, "warning": 2, "error": 3}

_ICON = {"error": "✗", "warning": "⚠", "info": "ℹ"}
_LABEL = {"error": "ERROR", "warning": "WARN", "info": "INFO"}


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
