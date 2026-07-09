"""Pure finding → in-KiCad surface mapping (spec §8.3) — no kipy, fully testable.

The IPC plugin (:mod:`returnpath.kicad_plugin.plugin`) turns a completed
:class:`~returnpath.engine.CheckResult` into three KiCad surfaces. *Which* finding
feeds *which* surface — and how it is drawn — is decided here, in plain data, so the
policy is unit-tested without a live KiCad:

* :func:`drc_marker_findings` — the native DRC panel gets ``error``/``warning`` findings,
  **unwaived only** (``info`` and waived never inject a marker; §8.3). These are the
  transient markers KiCad's own DRC run wipes.
* :func:`overlay_marks` — the durable ``User.*``-layer record: **every** finding
  (including ``info`` and waived, sectioned by the numbering, not dropped), a numbered
  crosshair coloured by severity with waived ones drawn muted. Numbering and colour come
  from :mod:`returnpath.report`, so the overlay matches the SVG/HTML reports exactly.
* :func:`trace_for_finding` — the trace to flash when a finding is clicked
  (``add_to_selection``, the only interaction primitive; §8.3/§9): the routed segment on
  the finding's net + layer nearest its location.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point

from ..detector import Finding
from ..parser import Board, Trace
from ..report import ordered_findings, severity_color

__all__ = [
    "CROSSHAIR_RADIUS_MM",
    "OverlayMark",
    "crosshair_lines",
    "drc_marker_findings",
    "overlay_marks",
    "trace_for_finding",
]

# Half-length of an overlay crosshair's arms, in millimetres (matches the report SVG).
CROSSHAIR_RADIUS_MM = 1.4

# Severities that inject a native DRC marker (spec §8.3: error/warning only).
_DRC_SEVERITIES = frozenset({"error", "warning"})


def drc_marker_findings(findings: list[Finding]) -> list[Finding]:
    """Findings that populate the native DRC panel: ``error``/``warning``, **unwaived** only.

    ``info`` and waived findings are excluded (§8.3) — they live only on the durable
    ``User.*`` overlay and in the panel. Order matches :func:`overlay_marks` so a marker
    and its overlay crosshair carry the same number.
    """
    return [f for f in ordered_findings(findings) if f.severity in _DRC_SEVERITIES and not f.waived]


@dataclass(frozen=True)
class OverlayMark:
    """One durable ``User.*`` overlay glyph (spec §8.3): a numbered, coloured crosshair.

    ``number`` is the shared 1-based index (matches the report/JSON/SVG numbering);
    ``x``/``y`` are board millimetres (KiCad's y-down frame — the report SVG passes them
    through unflipped). ``color`` is the severity colour, overridden to muted grey when
    ``waived``; ``muted`` lets the renderer draw waived marks hollow/greyed.
    """

    number: int
    finding: Finding
    x: float
    y: float
    severity: str
    waived: bool
    muted: bool
    color: str
    label: str


def overlay_marks(findings: list[Finding]) -> list[OverlayMark]:
    """Every finding as a numbered overlay mark (spec §8.3) — ``info`` and waived included.

    Nothing is dropped: the overlay is the persistent record that survives a native DRC
    run. Waived marks carry ``muted=True`` and the muted colour so the renderer greys them.
    The numbering matches :func:`returnpath.report.ordered_findings`, so the overlay,
    the SVG crosshairs, and the panel all agree.
    """
    marks: list[OverlayMark] = []
    for n, f in enumerate(ordered_findings(findings), 1):
        marks.append(
            OverlayMark(
                number=n,
                finding=f,
                x=f.x,
                y=f.y,
                severity=f.severity,
                waived=f.waived,
                muted=f.waived,
                color=severity_color(f.severity, f.waived),
                label=f"{n}. {f.cls} ({f.net})" + (" [waived]" if f.waived else ""),
            )
        )
    return marks


def crosshair_lines(
    mark: OverlayMark, radius: float = CROSSHAIR_RADIUS_MM
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The two crossing arm segments of *mark*'s crosshair, in board millimetres.

    Returned as ``[(start, end), (start, end)]`` (horizontal then vertical), so the kipy
    renderer only converts mm → nm and draws — no geometry logic in the live-KiCad layer.
    """
    x, y = mark.x, mark.y
    return [
        ((x - radius, y), (x + radius, y)),
        ((x, y - radius), (x, y + radius)),
    ]


def trace_for_finding(board: Board, finding: Finding) -> Trace | None:
    """The routed trace a clicked *finding* should flash/select (spec §8.3).

    Prefers a segment on the finding's own net **and** layer nearest its location; falls
    back to the nearest segment merely on the same net (a finding's ``reference_layer`` can
    differ from where the victim trace runs). Returns ``None`` when the net has no routed
    copper (e.g. a via-only net), so the caller simply skips the flash.
    """
    point = Point(finding.x, finding.y)
    on_net = [t for t in board.traces if t.net == finding.net]
    if not on_net:
        return None
    on_layer = [t for t in on_net if t.layer == finding.layer]
    candidates = on_layer or on_net
    return min(candidates, key=lambda t: t.line.distance(point))
