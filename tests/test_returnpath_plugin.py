"""The in-KiCad IPC plugin (issue #23): manifest, shared analysis, and surface policy.

The live kipy connection + drawing need a real KiCad (the manual acceptance step), so
these tests pin the parts that *are* headless-testable, one per acceptance criterion:

1. the ``plugin.json`` manifest loads (valid api/schemas/v1 shape, toolbar button, a
   pcb-scoped action) and every referenced file exists → the plugin loads in KiCad;
2. the plugin runs the board through the *same* engine as a headless CLI run → identical
   findings;
3. ``drc_marker_findings`` selects unwaived ``error``/``warning`` only (``info`` + waived
   never inject a marker);
4. ``overlay_marks`` covers *every* finding (``info`` + waived included), numbered to match
   the report, with waived marks muted → the durable User-layer overlay;
5. ``trace_for_finding`` picks the offending trace to flash on click;
6. kicad-python is pinned to 0.7.1 and the broken kipy imports are avoided (and importing
   the plugin never needs kipy).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from shapely.geometry import LineString

from returnpath.config import build_config
from returnpath.detector import Finding
from returnpath.engine import analyze_board, check_live_board
from returnpath.kicad_plugin import plugin
from returnpath.kicad_plugin.surfaces import (
    crosshair_lines,
    drc_marker_findings,
    overlay_marks,
    trace_for_finding,
)
from returnpath.parser import Board, Trace
from returnpath.report import ordered_findings, severity_color

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"

BUNDLE = Path(__file__).resolve().parent.parent / "plugins" / "returnpath"
MANIFEST = BUNDLE / "plugin.json"

# KiCad's api.v1 schema vocabulary (mirrors tests/test_plugin_manifest.py for captouch).
_VALID_SCOPES = {"pcb", "schematic", "footprint", "symbol", "project_manager"}
_PLUGIN_REQUIRED = {"identifier", "name", "description", "runtime", "actions"}
_ACTION_REQUIRED = {"identifier", "name", "description", "entrypoint"}
# The stricter KiCad loader identifier rule (API_PLUGIN::IsValidIdentifier): a
# word.word.word reverse-DNS run; \w excludes '-', so a hyphen may sit only in a
# trailing segment.
_KICAD_IDENTIFIER_RULE = re.compile(r"[\w\d]{2,}\.[\w\d]+\.[\w\d]+")


def _finding(**kw) -> Finding:
    """A minimal Finding with sensible defaults, overridable per test."""
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
# AC1 — manifest loads / toolbar button
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_valid_json_and_present():
    assert MANIFEST.exists()
    assert isinstance(json.loads(MANIFEST.read_text(encoding="utf-8")), dict)


def test_manifest_has_required_fields_and_python_runtime(manifest):
    assert _PLUGIN_REQUIRED <= set(manifest)
    assert manifest["runtime"]["type"] == "python"
    assert manifest["actions"], "at least one action"


def test_action_is_pcb_scoped_with_toolbar_button(manifest):
    action = manifest["actions"][0]
    assert _ACTION_REQUIRED <= set(action)
    assert set(action["scopes"]) <= _VALID_SCOPES
    assert "pcb" in action["scopes"]
    assert action["show-button"] is True  # the toolbar button (AC1)


def test_identifier_meets_kicad_loader_requirements(manifest):
    assert manifest["identifier"] == "com.github.unwndevices.kicad-returnpath"
    assert _KICAD_IDENTIFIER_RULE.search(manifest["identifier"]), manifest["identifier"]


def test_referenced_files_exist(manifest):
    action = manifest["actions"][0]
    assert (BUNDLE / action["entrypoint"]).exists()
    for key in ("icons-light", "icons-dark"):
        for icon in action.get(key, []):
            assert (BUNDLE / icon).exists(), icon
            assert icon.endswith(".png")
    assert (BUNDLE / "entry.py").exists()
    assert (BUNDLE / "requirements.txt").exists()


# --------------------------------------------------------------------------- #
# AC2 — same findings as a headless run
# --------------------------------------------------------------------------- #
def test_check_live_board_matches_headless_cli():
    text = SPLIT_BOARD.read_text()
    result = check_live_board(text, SPLIT_BOARD)
    # the CLI path: build config from the board dir, analyze the same text.
    _, cli_findings = analyze_board(text, config=build_config(SPLIT_BOARD))
    assert [f.id for f in result.findings] == [f.id for f in cli_findings]
    assert any(f.severity == "error" for f in result.findings)


def test_run_board_file_reports_and_exits_zero(capsys):
    rc = plugin.run_board_file(SPLIT_BOARD)
    out = capsys.readouterr().out
    assert rc == 0
    assert "return-path check" in out
    assert "DRC marker(s)" in out and "overlay mark(s)" in out


def test_main_board_file_missing_exits_two(capsys):
    rc = plugin.main(["--board-file", "/no/such/board.kicad_pcb"])
    assert rc == 2
    assert "board not found" in capsys.readouterr().err


def test_main_dispatches_board_file(monkeypatch, tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    seen = {}

    def fake_run(p):
        seen["path"] = p
        return 0

    monkeypatch.setattr(plugin, "run_board_file", fake_run)
    assert plugin.main(["--board-file", str(board)]) == 0
    assert seen["path"] == board


def test_main_reports_connection_failure(monkeypatch, capsys):
    def boom():
        raise RuntimeError("no socket")

    monkeypatch.setattr(plugin, "_connect_board", boom)
    rc = plugin.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "could not reach KiCad over the IPC API" in err
    assert "--board-file" in err  # the offered fallback


def test_main_analysis_failure_is_not_mislabelled_as_connection(monkeypatch, capsys):
    # A connected board that fails to analyze must NOT be reported as an IPC failure.
    class _Board:
        name = "live"

        def get_as_string(self):
            return "(kicad_pcb)"

    monkeypatch.setattr(plugin, "_connect_board", lambda: _Board())
    monkeypatch.setattr(plugin, "_board_disk_path", lambda b: Path("/tmp/x.kicad_pcb"))

    def boom(text, path):
        raise ValueError("bad board")

    monkeypatch.setattr(plugin, "check_live_board", boom)
    rc = plugin.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "could not check the live board" in err
    assert "IPC API" not in err  # not the connection message


# --------------------------------------------------------------------------- #
# AC3 — DRC markers: unwaived error/warning only
# --------------------------------------------------------------------------- #
def test_drc_markers_are_unwaived_error_and_warning_only():
    findings = [
        _finding(cls="split-crossing", severity="error", id="e1"),
        _finding(cls="edge-overhang", severity="warning", id="w1", net="A"),
        _finding(cls="reference-change", severity="info", id="i1", net="B"),
        _finding(cls="split-crossing", severity="error", id="e2", net="C", waived=True),
    ]
    markers = drc_marker_findings(findings)
    ids = {f.id for f in markers}
    assert ids == {"e1", "w1"}  # info excluded, waived excluded


def test_drc_markers_order_matches_report():
    findings = [
        _finding(severity="warning", cls="edge-overhang", id="w", net="Z"),
        _finding(severity="error", cls="split-crossing", id="e", net="A"),
    ]
    markers = drc_marker_findings(findings)
    # errors sort before warnings, exactly as the report/overlay numbering does.
    assert [f.id for f in markers] == [f.id for f in ordered_findings(findings) if not f.waived]
    assert markers[0].id == "e"


# --------------------------------------------------------------------------- #
# AC4 — durable overlay: every finding, numbered, waived muted
# --------------------------------------------------------------------------- #
def test_overlay_includes_info_and_waived_findings():
    findings = [
        _finding(severity="error", id="e1"),
        _finding(severity="info", id="i1", net="B"),
        _finding(severity="warning", id="w1", net="C", waived=True, waiver_reason="ok"),
    ]
    marks = overlay_marks(findings)
    assert len(marks) == 3  # nothing dropped — the persistent record
    assert {m.finding.id for m in marks} == {"e1", "i1", "w1"}


def test_overlay_numbering_matches_report_order():
    findings = [
        _finding(severity="info", id="i", net="Z"),
        _finding(severity="error", id="e", net="A"),
    ]
    marks = overlay_marks(findings)
    ordered = ordered_findings(findings)
    assert [m.number for m in marks] == [1, 2]
    assert [m.finding.id for m in marks] == [f.id for f in ordered]


def test_overlay_waived_marks_are_muted():
    active = _finding(severity="error", id="e1")
    waived = _finding(severity="error", id="e2", net="B", waived=True)
    marks = {m.finding.id: m for m in overlay_marks([active, waived])}
    assert marks["e2"].muted is True and marks["e2"].waived is True
    assert marks["e2"].color == severity_color("error", waived=True)  # muted grey
    assert marks["e1"].muted is False
    assert marks["e1"].color == severity_color("error") != marks["e2"].color
    assert "[waived]" in marks["e2"].label


def test_overlay_excludes_locationless_stale_waivers():
    # A stale-waiver meta-finding has no board location (a (0,0) sentinel); drawing a
    # crosshair at the board origin for it would be spurious, so it gets no overlay mark.
    real = _finding(severity="error", id="e1", x=10.0, y=20.0)
    stale = _finding(
        check="stale-waiver", cls="stale-waiver", severity="info", id="s1", x=0.0, y=0.0
    )
    marks = overlay_marks([real, stale])
    assert [m.finding.id for m in marks] == ["e1"]  # stale-waiver dropped, real kept
    assert marks[0].number == 1


def test_crosshair_lines_center_on_the_finding():
    mark = overlay_marks([_finding(x=5.0, y=7.0)])[0]
    (h0, h1), (v0, v1) = crosshair_lines(mark, radius=2.0)
    assert h0 == (3.0, 7.0) and h1 == (7.0, 7.0)  # horizontal arm
    assert v0 == (5.0, 5.0) and v1 == (5.0, 9.0)  # vertical arm


# --------------------------------------------------------------------------- #
# AC5 — click flashes the offending trace
# --------------------------------------------------------------------------- #
def _board_with_traces(*traces: Trace) -> Board:
    return Board(version="20260206", traces=tuple(traces), planes={})


def test_trace_for_finding_prefers_net_and_layer_nearest():
    near = Trace(net="SIG", layer="B.Cu", width=0.2, line=LineString([(9, 20), (11, 20)]))
    far = Trace(net="SIG", layer="B.Cu", width=0.2, line=LineString([(90, 90), (91, 90)]))
    other_layer = Trace(net="SIG", layer="F.Cu", width=0.2, line=LineString([(10, 20), (10, 21)]))
    board = _board_with_traces(far, other_layer, near)
    f = _finding(net="SIG", layer="B.Cu", x=10.0, y=20.0)
    assert trace_for_finding(board, f) is near


def test_trace_for_finding_falls_back_to_net_when_layer_absent():
    only = Trace(net="SIG", layer="F.Cu", width=0.2, line=LineString([(10, 20), (12, 20)]))
    board = _board_with_traces(only)
    f = _finding(net="SIG", layer="B.Cu", x=10.0, y=20.0)
    assert trace_for_finding(board, f) is only  # different layer, same net


def test_trace_for_finding_none_when_net_has_no_copper():
    board = _board_with_traces(
        Trace(net="OTHER", layer="B.Cu", width=0.2, line=LineString([(0, 0), (1, 0)]))
    )
    assert trace_for_finding(board, _finding(net="SIG")) is None


# --------------------------------------------------------------------------- #
# AC6 — kicad-python pinned to 0.7.1, broken imports avoided, lazy kipy
# --------------------------------------------------------------------------- #
def test_requirements_pin_kicad_python_0_7_1():
    reqs = (BUNDLE / "requirements.txt").read_text(encoding="utf-8")
    assert "kicad-python==0.7.1" in reqs
    assert "kicad-returnpath @" in reqs  # the checker core is a plugin-venv dependency


def test_plugin_avoids_the_broken_kipy_imports():
    # The §9 gotcha: the 0.7.1 wheel ships broken kipy.board_rules / kipy.schematic_types.
    # Guard against an *import* of them (prose in a docstring naming them is fine).
    src = Path(plugin.__file__).read_text(encoding="utf-8") + (
        Path(plugin.__file__).parent / "surfaces.py"
    ).read_text(encoding="utf-8")
    import_lines = [ln for ln in src.splitlines() if re.match(r"\s*(from|import)\s+kipy", ln)]
    joined = "\n".join(import_lines)
    assert "board_rules" not in joined
    assert "schematic_types" not in joined


def test_importing_the_plugin_does_not_require_kipy():
    # kipy is not installed in CI; a top-level import would make the whole package
    # unimportable. The connection uses a lazy import inside the functions instead.
    import importlib

    assert importlib.import_module("returnpath.kicad_plugin") is not None


# --------------------------------------------------------------------------- #
# board-path resolution (config/waiver discovery from kipy)
# --------------------------------------------------------------------------- #
def test_board_path_for_discovery_from_board_file(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    assert plugin.board_path_for_discovery(board).parent == tmp_path.resolve()


def test_board_path_for_discovery_from_directory(tmp_path):
    # A directory collapses to a path *inside* it, so discovery starts in that dir.
    assert plugin.board_path_for_discovery(tmp_path).parent == tmp_path.resolve()


def test_board_path_for_discovery_from_kicad_pro(tmp_path):
    assert plugin.board_path_for_discovery(tmp_path / "p.kicad_pro").parent == tmp_path.resolve()
