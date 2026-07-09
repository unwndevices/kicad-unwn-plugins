"""Plane-edge clearance & return-via-at-layer-change tests (issue #20).

Covers the five acceptance criteria for the remaining two v1 checks (spec §5.1 #2/#3):

1. edge-clearance uses the per-trace ``max(3H, 90 mil, 1×W)`` formula from stackup H; a
   scalar override replaces it with a flat floor;
2. a trace hugging the plane edge below threshold is flagged; one comfortably inside is not;
3. a layer-changing signal via with no return via within ``return_via_distance_mm`` is
   flagged; one with a nearby stitch via is not;
4. both checks respect per-net/netclass threshold and severity overrides (§6);
5. the checks are verified on the real fixture board (no false positives).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString

from kicad_core.sexpr import loads
from returnpath.cli import main
from returnpath.config import Config
from returnpath.detector import (
    EDGE_CLEARANCE_MIL_FLOOR_MM,
    _edge_clearance_threshold,
    check_return_path,
)
from returnpath.parser import Trace, parse_board, parse_vias
from returnpath.stackup import parse_stackup

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
EDGE_VIA_BOARD = FIXTURES / "edge_via_board.kicad_pcb"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"
REF_NETS = ("GND",)


def _board():
    return parse_board(EDGE_VIA_BOARD.read_text(), REF_NETS)


def _by_cls(findings, cls):
    return [f for f in findings if f.cls == cls]


# --------------------------------------------------------------------------- #
# dielectric stackup + the edge-clearance formula (§5.2) — AC1
# --------------------------------------------------------------------------- #
def test_dielectric_height_sums_between_copper_layers():
    stack = parse_stackup(loads(EDGE_VIA_BOARD.read_text()))
    # B.Cu ↔ In2.Cu are separated by the single prepreg (0.2 mm).
    assert stack.dielectric_height("B.Cu", "In2.Cu") == 0.2
    # In1.Cu ↔ In2.Cu straddle the thick core (1.065 mm); order is symmetric.
    assert stack.dielectric_height("In1.Cu", "In2.Cu") == 1.065
    assert stack.dielectric_height("In2.Cu", "In1.Cu") == 1.065
    # A board without a (setup (stackup …)) build has no known H.
    assert parse_stackup(loads(SPLIT_BOARD.read_text())).dielectric_height("B.Cu", "In2.Cu") is None


def test_edge_clearance_formula_picks_the_dominant_term():
    board = _board()
    thin = Trace(net="S", layer="B.Cu", width=0.25, line=LineString([(0, 0), (1, 0)]))
    # H = 0.2 → 3H = 0.6, dominated by the 90 mil floor (2.286 mm).
    assert _edge_clearance_threshold(thin, "In2.Cu", board, None) == EDGE_CLEARANCE_MIL_FLOOR_MM
    # A stripline over the thick core: 3 × 1.065 = 3.195 mm dominates the 90 mil floor.
    strip = Trace(net="S", layer="In1.Cu", width=0.25, line=LineString([(0, 0), (1, 0)]))
    assert _edge_clearance_threshold(strip, "In2.Cu", board, None) == 3.195
    # A wide trace with no stackup: the 1×W term wins.
    wide = Trace(net="S", layer="B.Cu", width=3.0, line=LineString([(0, 0), (1, 0)]))
    assert _edge_clearance_threshold(wide, "In2.Cu", board, None) == 3.0


def test_scalar_override_replaces_the_formula():
    board = _board()
    thin = Trace(net="S", layer="B.Cu", width=0.25, line=LineString([(0, 0), (1, 0)]))
    # A configured edge_clearance_mm is a flat floor, ignoring H / 90 mil / width.
    assert _edge_clearance_threshold(thin, "In2.Cu", board, 0.30) == 0.30


# --------------------------------------------------------------------------- #
# edge-clearance detection (§5.1 #2) — AC2
# --------------------------------------------------------------------------- #
def test_hugging_trace_flagged_inside_trace_not():
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    edge = _by_cls(findings, "edge-clearance")
    assert {f.net for f in edge} == {"SIG_HUG"}  # only the edge-hugging trace
    f = edge[0]
    assert f.severity == "warning"
    assert f.reference_layer == "In2.Cu"
    assert f.span_mm == pytest.approx(0.4, abs=1e-6)  # 0.4 mm from the y=2 plane edge
    # The report location lands on the trace at the closest approach.
    assert f.y == 2.4


def test_edge_clearance_skips_uncovered_traces():
    # SIG_INSIDE is comfortably referenced; the overhang/split cases are the classifier's,
    # so edge-clearance never double-reports a trace that leaves the pour.
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    assert not any(f.net == "SIG_INSIDE" for f in findings)


# --------------------------------------------------------------------------- #
# return-via-at-layer-change (§5.1 #3) — AC3
# --------------------------------------------------------------------------- #
def test_vias_parsed():
    vias = parse_vias(loads(EDGE_VIA_BOARD.read_text()))
    assert {v.net for v in vias} == {"SIG_LONELY", "SIG_STITCHED", "GND"}
    lonely = next(v for v in vias if v.net == "SIG_LONELY")
    assert (lonely.x, lonely.y) == (40.0, 20.0)
    assert lonely.layers == ("F.Cu", "B.Cu")


def test_lonely_via_flagged_stitched_via_not():
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    missing = _by_cls(findings, "missing-return-via")
    assert {f.net for f in missing} == {"SIG_LONELY"}  # no GND via within 2.0 mm
    f = missing[0]
    assert f.severity == "error"
    assert (f.x, f.y) == (40.0, 20.0)


def test_return_via_distance_override_flags_the_stitched_via():
    # Tightening return_via_distance_mm below the 1.0 mm stitch gap flags SIG_STITCHED too.
    config = Config(reference_nets=("GND",)).with_overrides(sets=["return_via_distance_mm=0.5"])
    findings = check_return_path(
        _board(), reference_nets=REF_NETS, config=config, net_to_netclass={}
    )
    assert {f.net for f in _by_cls(findings, "missing-return-via")} == {
        "SIG_LONELY",
        "SIG_STITCHED",
    }


# --------------------------------------------------------------------------- #
# per-net threshold & severity overrides (§6) — AC4
# --------------------------------------------------------------------------- #
def test_edge_clearance_threshold_override_clears_the_finding():
    # A per-run scalar edge_clearance_mm of 0.3 mm makes the 0.4 mm SIG_HUG gap acceptable.
    config = Config(reference_nets=("GND",)).with_overrides(sets=["edge_clearance_mm=0.3"])
    findings = check_return_path(
        _board(), reference_nets=REF_NETS, config=config, net_to_netclass={}
    )
    assert not _by_cls(findings, "edge-clearance")


def test_severity_override_downgrades_both_new_classes():
    config = Config(reference_nets=("GND",)).with_overrides(
        sets=["severity.edge_clearance=info", "severity.missing_return_via=warning"]
    )
    findings = check_return_path(
        _board(), reference_nets=REF_NETS, config=config, net_to_netclass={}
    )
    assert _by_cls(findings, "edge-clearance")[0].severity == "info"
    assert _by_cls(findings, "missing-return-via")[0].severity == "warning"


def test_ignore_severity_silences_the_via_check():
    config = Config(reference_nets=("GND",)).with_overrides(
        sets=["severity.missing_return_via=ignore"]
    )
    findings = check_return_path(
        _board(), reference_nets=REF_NETS, config=config, net_to_netclass={}
    )
    assert not _by_cls(findings, "missing-return-via")


# --------------------------------------------------------------------------- #
# verified on the real fixture board (§5.1) — AC5
# --------------------------------------------------------------------------- #
def test_no_false_positives_on_real_board():
    # The real split board has no near-edge trace and no vias — the two new checks must
    # stay silent there, leaving its split-crossing + edge-overhang findings untouched.
    findings = check_return_path(parse_board(SPLIT_BOARD.read_text()))
    assert not _by_cls(findings, "edge-clearance")
    assert not _by_cls(findings, "missing-return-via")


def test_cli_reports_both_new_findings(capsys):
    assert main(["check", str(EDGE_VIA_BOARD), "--reference-nets", "GND"]) == 1
    out = capsys.readouterr().out
    assert "edge-clearance" in out
    assert "missing-return-via" in out
