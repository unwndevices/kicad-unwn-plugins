"""Walking-skeleton tests for the return-path checker (issue #17).

Covers the six acceptance criteria against committed fixture boards:

1. a real 20260206 board parses and reports split-crossing findings (not a false
   empty-plane "clean" pass);
2. a pre-KiCad-10 board (numeric nets / ``net_name`` child) is *rejected*, not
   silently passed;
3. the both-ends-on-plane predicate distinguishes split-crossing from edge-overhang;
4. the text report is grouped with an error/warning tally;
5. exit codes 0 / 1 / 2;
6. detection is exercised against the committed fixtures below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_core.sexpr import loads
from returnpath.cli import main
from returnpath.detector import check_split_crossing
from returnpath.parser import (
    BASELINE_VERSION,
    ParserContractError,
    parse_board,
    reference_planes,
)
from returnpath.report import format_text_report

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"
LEGACY_BOARD = FIXTURES / "legacy_board.kicad_pcb"


@pytest.fixture
def split_findings():
    board = parse_board(SPLIT_BOARD.read_text())
    return board, check_split_crossing(board)


# --------------------------------------------------------------------------- #
# parser contract (§3)
# --------------------------------------------------------------------------- #
def test_split_board_is_kicad10_baseline():
    board = parse_board(SPLIT_BOARD.read_text())
    assert board.version == BASELINE_VERSION


def test_multi_layer_zone_selects_plane_per_filled_polygon_layer():
    # The single GND zone spans In2.Cu + B.Cu; each layer must resolve to its own
    # plane, and the slotted In2.Cu plane must not be merged with the B.Cu pour.
    board = parse_board(SPLIT_BOARD.read_text())
    assert set(board.planes) == {"In2.Cu", "B.Cu"}
    # In2.Cu is the two-island (slotted) plane; B.Cu is the solid pour.
    assert board.planes["In2.Cu"].area < board.planes["B.Cu"].area


def test_traces_parsed_by_name():
    board = parse_board(SPLIT_BOARD.read_text())
    nets = {t.net for t in board.traces}
    assert nets == {"SIG_FAST", "SIG_EDGE", "SIG_OK"}


# AC2 — a pre-KiCad-10 board must NOT silently pass.
def test_legacy_numeric_net_board_is_rejected():
    with pytest.raises(ParserContractError) as exc:
        parse_board(LEGACY_BOARD.read_text())
    assert "pre-KiCad-10" in str(exc.value)


def test_legacy_board_would_have_looked_clean():
    # Guard the *reason* AC2 exists: without the schema guard the name-based parser
    # finds no GND plane on the numeric-net board — the false empty-plane pass.
    root = loads(LEGACY_BOARD.read_text())
    assert reference_planes(root, ("GND",)) == {}  # empty → would report "clean"


def test_reference_nets_thread_into_plane_selection():
    # A power-plane board reads "clean" under the default GND set (no GND copper) but
    # yields the split once its own reference net is selected — parse_board must honour
    # the passed reference_nets, not hardcode GND.
    text = _power_plane_board()
    assert parse_board(text).planes == {}  # default GND → no plane
    board = parse_board(text, ("+3V3",))
    assert set(board.planes) == {"In2.Cu"}
    findings = check_split_crossing(board, reference_nets=("+3V3",))
    assert any(f.cls == "split-crossing" for f in findings)


def test_cli_reference_nets_flag_finds_power_plane_split(tmp_path, capsys):
    board = tmp_path / "pwr.kicad_pcb"
    board.write_text(_power_plane_board())
    # Restrict to GND only: the +3V3 pour is not a plane → nothing to fail on → exit 0.
    assert main(["check", str(board), "--reference-nets", "GND"]) == 0
    # Select the real reference net → the split surfaces and fails the build.
    assert main(["check", str(board), "--reference-nets", "+3V3"]) == 1
    assert "split-crossing" in capsys.readouterr().out


def test_sliver_area_floor_drops_thin_span():
    # The SIG_FAST 4 mm crossing survives at 0.25 mm width (1.0 mm²) but is dropped
    # when the trace is thin enough that the uncovered copper falls below the floor.
    board = parse_board(SPLIT_BOARD.read_text())
    fat = check_split_crossing(board)
    assert any(f.cls == "split-crossing" for f in fat)
    # A 0.25 mm-wide, 4 mm span is 1.0 mm²; a floor above that suppresses it.
    thin = check_split_crossing(board, sliver_ignore_area_mm2=2.0)
    assert not any(f.net == "SIG_FAST" for f in thin)


# --------------------------------------------------------------------------- #
# detector (§4.4 / §5.1) — AC1, AC3
# --------------------------------------------------------------------------- #
def test_reports_split_crossing(split_findings):
    _, findings = split_findings
    splits = [f for f in findings if f.cls == "split-crossing"]
    assert len(splits) == 1
    f = splits[0]
    assert f.net == "SIG_FAST"
    assert f.severity == "error"
    assert f.reference_layer == "In2.Cu"
    assert f.layer == "B.Cu"
    # The In2.Cu slot runs y=18..22 → a 4 mm crossing at x=30.
    assert f.span_mm == pytest.approx(4.0, abs=1e-6)
    assert f.x == pytest.approx(30.0, abs=1e-6)


def test_both_ends_predicate_distinguishes_overhang(split_findings):
    _, findings = split_findings
    overhangs = [f for f in findings if f.cls == "edge-overhang"]
    assert len(overhangs) == 1
    f = overhangs[0]
    assert f.net == "SIG_EDGE"
    assert f.severity == "warning"
    # Runs from the pour top edge (y=38) out to y=45 → a 7 mm free-ended over-run.
    assert f.span_mm == pytest.approx(7.0, abs=1e-6)


def test_covered_trace_yields_no_finding(split_findings):
    _, findings = split_findings
    assert not [f for f in findings if f.net == "SIG_OK"]


def test_not_a_false_empty_plane_pass(split_findings):
    _, findings = split_findings
    # The whole point of AC1: real findings, not zero.
    assert findings


# --------------------------------------------------------------------------- #
# report (§8.2) — AC4
# --------------------------------------------------------------------------- #
def test_text_report_grouped_with_tally(split_findings):
    _, findings = split_findings
    text = format_text_report("split_board.kicad_pcb", findings)
    assert "split_board.kicad_pcb" in text
    assert "split-crossing" in text
    assert "edge-overhang" in text
    # errors sorted before warnings.
    assert text.index("split-crossing") < text.index("edge-overhang")
    assert "Summary: 1 error, 1 warning" in text


def test_text_report_clean_board():
    text = format_text_report("empty.kicad_pcb", [])
    assert "no return-path findings" in text
    assert "0 errors, 0 warnings" in text


# --------------------------------------------------------------------------- #
# CLI exit codes (§10) — AC5
# --------------------------------------------------------------------------- #
def test_cli_exit_1_on_error(capsys):
    assert main(["check", str(SPLIT_BOARD)]) == 1
    out = capsys.readouterr().out
    assert "split-crossing" in out


def test_cli_exit_0_when_fail_on_none(capsys):
    assert main(["check", str(SPLIT_BOARD), "--fail-on", "none"]) == 0


def test_cli_exit_0_when_only_warnings_and_fail_on_error(tmp_path, capsys):
    # A board whose only finding is an edge-overhang (warning) exits 0 by default.
    board = tmp_path / "warn_only.kicad_pcb"
    board.write_text(_warn_only_board())
    assert main(["check", str(board)]) == 0
    assert main(["check", str(board), "--fail-on", "warning"]) == 1


def test_cli_exit_2_on_missing_board(capsys):
    assert main(["check", "/no/such/board.kicad_pcb"]) == 2
    assert "not found" in capsys.readouterr().out


def test_cli_exit_2_on_legacy_board(capsys):
    # AC2 at the CLI seam: a numeric-net board fails usage, not a silent clean pass.
    assert main(["check", str(LEGACY_BOARD)]) == 2
    assert "pre-KiCad-10" in capsys.readouterr().out


def _warn_only_board() -> str:
    """A minimal 20260206 board with one edge-overhang and no split-crossing."""
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        '\t(generator "returnpath-fixture")\n'
        '\t(net 0 "")\n'
        '\t(net 1 "GND")\n'
        '\t(net 2 "SIG")\n'
        "\t(segment\n"
        "\t\t(start 20 10)\n"
        "\t\t(end 20 30)\n"
        "\t\t(width 0.25)\n"
        '\t\t(layer "B.Cu")\n'
        '\t\t(net "SIG")\n'
        "\t)\n"
        "\t(zone\n"
        '\t\t(net "GND")\n'
        '\t\t(layers "In2.Cu")\n'
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts\n"
        "\t\t\t\t(xy 2 2) (xy 38 2) (xy 38 20) (xy 2 20)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )


def _power_plane_board() -> str:
    """A 20260206 board whose only reference plane is a slotted +3V3 pour on In2.Cu."""
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        '\t(generator "returnpath-fixture")\n'
        '\t(net 0 "")\n'
        '\t(net 1 "+3V3")\n'
        '\t(net 2 "SIG")\n'
        "\t(segment\n"
        "\t\t(start 30 10)\n"
        "\t\t(end 30 30)\n"
        "\t\t(width 0.25)\n"
        '\t\t(layer "B.Cu")\n'
        '\t\t(net "SIG")\n'
        "\t)\n"
        "\t(zone\n"
        '\t\t(net "+3V3")\n'
        '\t\t(layers "In2.Cu")\n'
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts\n"
        "\t\t\t\t(xy 2 2) (xy 58 2) (xy 58 18) (xy 2 18)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts\n"
        "\t\t\t\t(xy 2 22) (xy 58 22) (xy 58 38) (xy 2 38)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )
