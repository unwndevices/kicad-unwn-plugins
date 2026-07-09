"""The findings-list panel's data model + un-waive write-back (spec §8.3) — pure, tested.

The interactive **findings-list panel** (issue #24) is the fourth in-KiCad surface: it lists
*every* finding — including ``info`` and waived — and drives navigation, since selection is
KiCad's only interaction primitive (§9). Like :mod:`returnpath.kicad_plugin.surfaces`, the
*policy* — which findings become rows, how they are sectioned, and how an un-waive rewrites
the sidecar — lives here in plain data so it is unit-tested without a live KiCad or Qt. The
Qt window that renders these rows and wires clicks to
:func:`returnpath.kicad_plugin.plugin.run_in_kicad`'s selection primitive is the thin,
manual-acceptance layer in :mod:`returnpath.kicad_plugin.panel_window`.

**Hosting (spec §8.3 / §12 open risk — resolved).** An IPC plugin is a separate process and
KiCad's API offers **no docked UI, no events** — the only in-KiCad surface is a toolbar button
(§9, verified against kicad-python 0.7.1 + KiCad 10). A dockable in-app panel is therefore
impossible over IPC; the panel is a **standalone plugin window** the toolbar action opens.

* :func:`panel_rows` — *every* finding as a numbered row in the shared report order (§8.2),
  so a row's number matches the text/JSON/SVG/HTML report list. ``info``, waived, and
  stale-waiver findings are all kept — the panel is the one surface that shows the complete set
  (the DRC panel keeps only unwaived error/warning; the overlay drops location-less stale
  waivers, so its crosshair numbers coincide with the panel's only when no stale waiver sorts
  ahead of a located finding; §8.3).
* :func:`panel_sections` — the same rows split into ``(active, waived)`` so the window can
  section waived findings separately (§8.3), the place a user un-waives from.
* :func:`unwaive` — remove a waiver entry from ``return-path.waivers.toml`` and rewrite it via
  the shared :func:`returnpath.waivers.remove_waivers` (the same write-back ``--prune-waivers``
  uses), so the un-waived finding resurfaces on the next run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..detector import Finding
from ..report import ordered_findings, severity_color
from ..waivers import remove_waivers

__all__ = [
    "PanelRow",
    "panel_rows",
    "panel_sections",
    "unwaive",
]


@dataclass(frozen=True)
class PanelRow:
    """One row of the findings-list panel (spec §8.3).

    ``number`` is the shared 1-based index over :func:`returnpath.report.ordered_findings`, so
    it matches the text/JSON/SVG/HTML report list (and the User-layer overlay crosshairs, which
    coincide unless a location-less stale waiver sorts ahead of a located finding).
    ``finding`` is the record the row selects/flashes on click (via
    :func:`returnpath.kicad_plugin.surfaces.trace_for_finding`) and un-waives by its
    ``finding.id``. ``color`` is the severity colour (muted grey when waived) shared with every
    other surface; ``waived`` sections the row and enables its un-waive action; ``label`` is a
    ready-to-show one-line summary.
    """

    number: int
    finding: Finding
    waived: bool
    color: str
    label: str


def _row_label(number: int, f: Finding) -> str:
    text = f"{number}. [{f.severity}] {f.cls} · {f.net} · ({f.x:.2f}, {f.y:.2f}) mm"
    if f.waived and f.waiver_reason:
        text += f" — {f.waiver_reason}"
    return text


def panel_rows(findings: list[Finding]) -> list[PanelRow]:
    """*Every* finding as a numbered panel row in the shared report order (spec §8.3).

    Numbering follows :func:`returnpath.report.ordered_findings` (errors first, then by net +
    location) so a row's number matches the report formats. Nothing is dropped — ``info``,
    waived, and stale-waiver findings are all listed, since the panel is the single surface that
    shows the complete set (the DRC panel keeps only unwaived error/warning; the overlay drops
    location-less stale waivers; §8.3).
    """
    return [
        PanelRow(
            number=n,
            finding=f,
            waived=f.waived,
            color=severity_color(f.severity, f.waived),
            label=_row_label(n, f),
        )
        for n, f in enumerate(ordered_findings(findings), 1)
    ]


def panel_sections(findings: list[Finding]) -> tuple[list[PanelRow], list[PanelRow]]:
    """Split the panel rows into ``(active, waived)`` — waived sectioned separately (spec §8.3).

    Both lists keep the shared report numbering (a waived row's ``number`` is its position in
    the full ordered list, not within its section), so numbers stay consistent with the report
    and overlay regardless of which section a row is shown in.
    """
    rows = panel_rows(findings)
    active = [r for r in rows if not r.waived]
    waived = [r for r in rows if r.waived]
    return active, waived


def unwaive(waiver_path: Path, waiver_id: str) -> bool:
    """Remove the waiver entry ``waiver_id`` from the sidecar at *waiver_path* and rewrite it.

    The panel's un-waive action writes back through the §7.2 system of record via the shared
    :func:`returnpath.waivers.remove_waivers` (the same read → drop-by-id → rewrite path
    ``--prune-waivers`` uses). Returns ``True`` when the entry was removed, ``False`` when the
    sidecar is missing or holds no such id (so the caller can report a no-op rather than silently
    succeeding). The finding itself resurfaces — active again — on the next run.
    """
    return remove_waivers(waiver_path, {waiver_id}) > 0
