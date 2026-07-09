"""The findings-list panel (issue #24): row/section policy, un-waive write-back, parity.

The Qt window (:mod:`returnpath.kicad_plugin.panel_window`) needs a real KiCad + PySide6 (the
manual acceptance step), so these tests pin the headless-testable *policy*, one group per
acceptance criterion:

1. the panel lists **all** findings across every severity — ``info``, waived, and stale-waiver
   included (:func:`panel_rows`);
2. clicking a finding selects/flashes its trace — the reused ``add_to_selection`` primitive
   (:func:`plugin._select_finding`);
3. waived findings are **sectioned** (:func:`panel_sections`) and un-waiving rewrites
   ``return-path.waivers.toml`` (:func:`unwaive`);
4. the dockable-vs-standalone question is resolved (§9: no docked UI over IPC → standalone
   window) and recorded — asserted here against the module + spec + README;
5. the panel reflects the **same findings** as the headless run and the other surfaces
   (numbering shared with :func:`returnpath.report.ordered_findings`).
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString

from returnpath.detector import Finding
from returnpath.engine import check_live_board
from returnpath.kicad_plugin import plugin
from returnpath.kicad_plugin.panel import PanelRow, panel_rows, panel_sections, unwaive
from returnpath.parser import Board, Trace
from returnpath.report import ordered_findings, severity_color
from returnpath.waivers import Waiver, dump_waivers, load_waivers

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "docs" / "return-path-checker-v1-spec.md"
README = REPO / "plugins" / "returnpath" / "README.md"


def _finding(**kw) -> Finding:
    base = dict(
        check="split-crossing",
        net="SIG",
        cls="split-crossing",
        severity="error",
        layer="B.Cu",
        reference_layer="In1.Cu",
        x=10.0,
        y=20.0,
        span_mm=1.0,
        message="msg",
        id="deadbeef",
    )
    base.update(kw)
    return Finding(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# AC1 — lists all findings across every severity, incl. info + waived
# --------------------------------------------------------------------------- #
def test_panel_lists_every_severity_including_info_and_waived():
    findings = [
        _finding(severity="error", id="e1"),
        _finding(severity="warning", id="w1", net="A"),
        _finding(severity="info", id="i1", net="B"),
        _finding(severity="warning", id="wv", net="C", waived=True, waiver_reason="ok"),
    ]
    rows = panel_rows(findings)
    assert {r.finding.id for r in rows} == {"e1", "w1", "i1", "wv"}  # nothing dropped


def test_panel_keeps_stale_waiver_findings_unlike_the_overlay():
    # The overlay drops location-less stale waivers (a (0,0) sentinel); the panel keeps them —
    # it is the one surface showing the complete set (§8.3).
    real = _finding(severity="error", id="e1", x=10.0, y=20.0)
    stale = _finding(
        check="stale-waiver", cls="stale-waiver", severity="info", id="s1", x=0.0, y=0.0
    )
    rows = panel_rows([real, stale])
    assert {r.finding.id for r in rows} == {"e1", "s1"}


def test_panel_row_color_is_the_shared_severity_color():
    active = _finding(severity="error", id="e1")
    waived = _finding(severity="error", id="e2", net="B", waived=True)
    rows = {r.finding.id: r for r in panel_rows([active, waived])}
    assert rows["e1"].color == severity_color("error")
    assert rows["e2"].color == severity_color("error", waived=True)  # muted grey
    assert rows["e2"].waived is True


# --------------------------------------------------------------------------- #
# AC3 — waived sectioned; numbering preserved
# --------------------------------------------------------------------------- #
def test_panel_sections_split_active_from_waived():
    findings = [
        _finding(severity="error", id="e1"),
        _finding(severity="warning", id="wv", net="A", waived=True),
        _finding(severity="info", id="i1", net="B"),
    ]
    active, waived = panel_sections(findings)
    assert {r.finding.id for r in active} == {"e1", "i1"}
    assert {r.finding.id for r in waived} == {"wv"}
    assert all(not r.waived for r in active)
    assert all(r.waived for r in waived)


def test_sectioned_rows_keep_the_shared_report_numbering():
    # A waived row's number is its position in the *full* ordered list, not within its section,
    # so it still lines up with the report/overlay.
    findings = [
        _finding(severity="error", id="e", net="A"),
        _finding(severity="warning", id="wv", net="B", waived=True),
        _finding(severity="info", id="i", net="C"),
    ]
    numbers = {r.finding.id: r.number for r in panel_rows(findings)}
    active, waived = panel_sections(findings)
    for r in (*active, *waived):
        assert r.number == numbers[r.finding.id]
    assert waived[0].number == numbers["wv"]


# --------------------------------------------------------------------------- #
# AC3 — un-waive rewrites the sidecar
# --------------------------------------------------------------------------- #
def _write_sidecar(path: Path, *waivers: Waiver) -> None:
    path.write_text(dump_waivers(list(waivers)), encoding="utf-8")


def test_unwaive_removes_the_entry_and_rewrites(tmp_path):
    sidecar = tmp_path / "return-path.waivers.toml"
    _write_sidecar(
        sidecar,
        Waiver(id="keep1", net="A", check="split-crossing", reason="a"),
        Waiver(id="drop1", net="B", check="split-crossing", reason="b"),
    )
    assert unwaive(sidecar, "drop1") is True
    remaining = {w.id for w in load_waivers(sidecar)}
    assert remaining == {"keep1"}  # only the un-waived entry gone; the rest intact


def test_unwaive_is_a_noop_for_an_absent_id(tmp_path):
    sidecar = tmp_path / "return-path.waivers.toml"
    _write_sidecar(sidecar, Waiver(id="keep1", net="A", reason="a"))
    assert unwaive(sidecar, "nope") is False
    assert {w.id for w in load_waivers(sidecar)} == {"keep1"}  # untouched


def test_unwaive_is_a_noop_when_the_sidecar_is_missing(tmp_path):
    assert unwaive(tmp_path / "return-path.waivers.toml", "any") is False


def test_unwaive_round_trips_through_the_loader(tmp_path):
    sidecar = tmp_path / "return-path.waivers.toml"
    _write_sidecar(
        sidecar,
        Waiver(id="a", net="A", check="split-crossing", reason="one"),
        Waiver(id="b", net="B", check="edge-clearance", reason="two"),
        Waiver(id="c", net="C", check="missing-return-via", reason="three"),
    )
    unwaive(sidecar, "b")
    kept = load_waivers(sidecar)
    assert [w.id for w in kept] == ["a", "c"]
    assert [w.reason for w in kept] == ["one", "three"]  # descriptive fields survive the rewrite


# --------------------------------------------------------------------------- #
# AC2 — clicking a finding flashes its trace (reused selection primitive)
# --------------------------------------------------------------------------- #
class _LiveBoard:
    """A stand-in for the kipy board exposing just the selection API the panel drives."""

    def __init__(self, tracks):
        self._tracks = tracks
        self.selected: list = []

    def get_tracks(self):
        return self._tracks

    def add_to_selection(self, items):
        self.selected.extend(items)


class _Pt:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _LiveTrack:
    def __init__(self, start, end):
        self.start, self.end = start, end


def test_select_finding_flashes_the_matching_live_trace():
    # The panel's on_select callback is plugin._select_finding — the same primitive the overlay
    # tail uses. It resolves the finding's trace, matches the live track, and selects it.
    parsed = Board(
        version="20260206",
        traces=(Trace(net="SIG", layer="B.Cu", width=0.2, line=LineString([(10, 20), (12, 20)])),),
        planes={},
    )
    nm = 1_000_000
    track = _LiveTrack(_Pt(10 * nm, 20 * nm), _Pt(12 * nm, 20 * nm))
    live = _LiveBoard([track])
    f = _finding(net="SIG", layer="B.Cu", x=10.0, y=20.0)
    assert plugin._select_finding(live, parsed, f) is True
    assert live.selected == [track]


def test_select_finding_is_a_noop_when_the_net_has_no_copper():
    parsed = Board(version="20260206", traces=(), planes={})
    live = _LiveBoard([])
    assert plugin._select_finding(live, parsed, _finding(net="SIG")) is False
    assert live.selected == []


# --------------------------------------------------------------------------- #
# AC4 — dockable-vs-standalone resolved to standalone, and recorded
# --------------------------------------------------------------------------- #
def test_hosting_decision_is_recorded_as_standalone():
    # §9: an IPC plugin is a separate process with no docked UI, so the panel is a standalone
    # window. The decision must be recorded (AC4) — in the panel module docstring, the spec, and
    # the bundle README.
    from returnpath.kicad_plugin import panel, panel_window

    assert "standalone" in (panel.__doc__ or "").lower()
    assert "standalone" in (panel_window.__doc__ or "").lower()
    spec = SPEC.read_text(encoding="utf-8").lower()
    assert "standalone" in spec and "resolved" in spec
    assert "standalone" in README.read_text(encoding="utf-8").lower()


def test_panel_window_imports_without_qt():
    # PySide6 is absent in CI; importing the window module (and touching open_findings_panel)
    # must not require Qt — it is imported lazily inside the functions.
    import importlib

    mod = importlib.import_module("returnpath.kicad_plugin.panel_window")
    assert callable(mod.open_findings_panel)


# --------------------------------------------------------------------------- #
# AC5 — same findings as the headless run + shared numbering with other surfaces
# --------------------------------------------------------------------------- #
def test_panel_reflects_the_same_findings_as_the_headless_run():
    result = check_live_board(SPLIT_BOARD.read_text(), SPLIT_BOARD)
    rows = panel_rows(result.findings)
    assert [r.finding.id for r in rows] == [f.id for f in result.findings] or {
        r.finding.id for r in rows
    } == {f.id for f in result.findings}
    # every reported finding appears exactly once
    assert {r.finding.id for r in rows} == {f.id for f in result.findings}
    assert len(rows) == len(result.findings)


def test_panel_numbering_matches_ordered_findings():
    findings = [
        _finding(severity="info", id="i", net="Z"),
        _finding(severity="error", id="e", net="A"),
        _finding(severity="warning", id="w", net="M"),
    ]
    rows = panel_rows(findings)
    ordered = ordered_findings(findings)
    assert [r.number for r in rows] == [1, 2, 3]
    assert [r.finding.id for r in rows] == [f.id for f in ordered]


def test_panel_row_is_a_frozen_record():
    row = panel_rows([_finding()])[0]
    assert isinstance(row, PanelRow)
    assert row.number == 1
