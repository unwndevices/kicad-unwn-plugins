"""Reference-plane identification & four-bucket classification tests (issue #18).

Covers the six acceptance criteria on top of the walking skeleton:

1. reference plane resolved per trace from the propagation table, geometric fallback
   where the table is silent;
2. a void carved in a *declared* plane is still flagged (coverage re-checked);
3. power-net pours qualify as reference planes, sub-``min_pour_area_mm2`` pours do not;
4. stripline traces reference both neighbours, microstrip references one;
5. segments classify into all four buckets — ``reference-change`` (GND→power) detected;
6. classification verified on the real multi-net fixture board.
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import GeometryCollection, LineString, Point

from kicad_core.sexpr import loads
from returnpath.cli import main
from returnpath.detector import _spans, check_return_path, resolve_reference_layers
from returnpath.parser import parse_board, parse_propagation, reference_plane_refs
from returnpath.report import format_text_report
from returnpath.stackup import parse_stackup

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
CLASSIFY_BOARD = FIXTURES / "classify_board.kicad_pcb"
REF_NETS = ("GND", "+3V3")


def _board():
    return parse_board(CLASSIFY_BOARD.read_text(), REF_NETS)


def _trace(board, net):
    return next(t for t in board.traces if t.net == net)


# --------------------------------------------------------------------------- #
# stackup + adjacency (§4.3) — AC4
# --------------------------------------------------------------------------- #
def test_stackup_is_physical_copper_order():
    stack = parse_stackup(loads(CLASSIFY_BOARD.read_text()))
    assert stack.order == ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
    assert stack.neighbours("B.Cu") == ("In2.Cu", None)  # microstrip (outer)
    assert stack.neighbours("In1.Cu") == ("F.Cu", "In2.Cu")  # stripline (inner)


def test_stripline_references_two_planes_microstrip_one():
    board = _board()
    # In1.Cu sits between the F.Cu and In2.Cu planes → two references (stripline).
    assert set(resolve_reference_layers(_trace(board, "SIG_STRIP"), board)) == {"F.Cu", "In2.Cu"}
    # B.Cu is an outer layer → one reference, the In2.Cu neighbour (microstrip).
    assert resolve_reference_layers(_trace(board, "SIG_MICRO"), board) == ("In2.Cu",)


# --------------------------------------------------------------------------- #
# qualifying planes (§4.2 / §5.2) — AC3
# --------------------------------------------------------------------------- #
def test_power_plane_qualifies_and_submin_pour_excluded():
    board = _board()
    keys = {(p.layer, p.net) for p in board.plane_refs}
    assert ("In2.Cu", "+3V3") in keys  # power-net pour qualifies as a reference plane
    assert ("F.Cu", "GND") in keys and ("B.Cu", "GND") in keys
    # The 0.25 mm² GND sliver on In1.Cu is below min_pour_area_mm2 (1.0) → not a plane.
    assert not any(p.layer == "In1.Cu" for p in board.plane_refs)


def test_submin_floor_is_per_layer_net():
    # A large GND plane on a layer must not rescue a sub-min power pour on the same layer.
    root = loads(_layered_board_with_tiny_power())
    refs = reference_plane_refs(root, ("GND", "+3V3"))
    keys = {(p.layer, p.net) for p in refs}
    assert ("In2.Cu", "GND") in keys
    assert ("In2.Cu", "+3V3") not in keys  # 0.25 mm² power sliver excluded on its own merit


# --------------------------------------------------------------------------- #
# four-bucket classification (§4.4) — AC5, AC6
# --------------------------------------------------------------------------- #
def test_four_buckets_on_fixture():
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    by_net = {f.net: f for f in findings}
    # solid segments (fully referenced by one plane) emit nothing.
    assert "SIG_STRIP" not in by_net
    assert "SIG_MICRO" not in by_net
    # the three defect buckets, each with its default severity.
    assert by_net["SIG_SPLIT"].cls == "split-crossing" and by_net["SIG_SPLIT"].severity == "error"
    assert (
        by_net["SIG_REFCHG"].cls == "reference-change" and by_net["SIG_REFCHG"].severity == "info"
    )
    assert by_net["SIG_EDGE"].cls == "edge-overhang" and by_net["SIG_EDGE"].severity == "warning"


def test_reference_change_names_both_planes():
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    f = next(f for f in findings if f.cls == "reference-change")
    assert "GND" in f.message and "+3V3" in f.message  # GND → power transition described
    assert f.reference_layer == "In2.Cu"


def test_split_crossing_against_power_plane():
    # SIG_SPLIT crosses the slot in the +3V3 plane — a power pour is a valid reference,
    # and the both-ends predicate labels the crossing a split (not an over-run).
    f = next(
        f for f in check_return_path(_board(), reference_nets=REF_NETS) if f.net == "SIG_SPLIT"
    )
    assert f.cls == "split-crossing"
    assert f.reference_layer == "In2.Cu"
    assert f.span_mm == 4.0
    assert (f.x, f.y) == (45.0, 20.0)


def test_spans_extracts_linestrings_from_geometry_collection():
    # difference() can return a GeometryCollection (Point + LineString) when a trace grazes
    # a plane vertex; the real void inside it must not be discarded with the point.
    line = LineString([(0, 0), (10, 0)])
    void = LineString([(3, 0), (7, 0)])
    gc = GeometryCollection([Point(3, 0), void])
    spans = _spans(line, gc, 0.1, 0.0065, 0.25)
    assert len(spans) == 1
    assert spans[0].length == 4.0


def test_reference_net_trace_skipped_even_if_flag_diverges():
    # plane_refs are built with +3V3 as a reference net; a +3V3 trace must not be checked
    # against its own plane even when check_return_path is called with the default GND set.
    board = parse_board(_reference_net_trace_board(), ("GND", "+3V3"))
    findings = check_return_path(board, reference_nets=("GND",))
    assert not any(f.net == "+3V3" for f in findings)


def test_no_reference_when_no_adjacent_plane():
    # A trace whose only planes are on its own layer has no adjacent reference → warning.
    board = parse_board(_board_with_only_same_layer_plane(), ("GND",))
    findings = check_return_path(board, reference_nets=("GND",))
    assert len(findings) == 1
    assert findings[0].cls == "no-reference" and findings[0].severity == "warning"


# --------------------------------------------------------------------------- #
# propagation table — hybrid resolution (§4.1) — AC1, AC2
# --------------------------------------------------------------------------- #
def test_propagation_table_parsed():
    table = parse_propagation(loads(_board_with_propagation("B.Cu", "F.Cu")))
    assert table == {"B.Cu": ("F.Cu",)}


def test_declared_reference_wins_over_geometry():
    # Geometry alone would pick the adjacent In2.Cu; the declared table names F.Cu.
    geometric = parse_board(_board_with_propagation("B.Cu", None), ("GND",))
    assert resolve_reference_layers(_trace(geometric, "SIG"), geometric) == ("In2.Cu",)
    declared = parse_board(_board_with_propagation("B.Cu", "F.Cu"), ("GND",))
    assert resolve_reference_layers(_trace(declared, "SIG"), declared) == ("F.Cu",)


def test_void_in_declared_plane_still_flagged():
    # The table declares In2.Cu as B.Cu's reference; coverage is re-checked anyway, so the
    # slot carved in that *declared* plane still trips a split-crossing (not a trusted pass).
    board = parse_board(_slotted_declared_board(), ("GND",))
    findings = check_return_path(board, reference_nets=("GND",))
    splits = [f for f in findings if f.cls == "split-crossing"]
    assert len(splits) == 1
    assert splits[0].reference_layer == "In2.Cu"


# --------------------------------------------------------------------------- #
# report / CLI wiring for the new classes — AC5, AC6
# --------------------------------------------------------------------------- #
def test_report_shows_all_three_classes_with_info():
    findings = check_return_path(_board(), reference_nets=REF_NETS)
    text = format_text_report("classify_board.kicad_pcb", findings)
    assert "split-crossing" in text
    assert "reference-change" in text
    assert "edge-overhang" in text
    assert "1 info" in text  # the reference-change is counted as info


def test_cli_fails_on_split_error_over_multiplane_board():
    assert main(["check", str(CLASSIFY_BOARD), "--reference-nets", "GND", "+3V3"]) == 1


# --------------------------------------------------------------------------- #
# inline fixtures
# --------------------------------------------------------------------------- #
def _four_layer_header(*, nets: str) -> str:
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        '\t(generator "returnpath-fixture")\n'
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n'
        '\t\t(1 "In1.Cu" signal)\n'
        '\t\t(2 "In2.Cu" signal)\n'
        '\t\t(31 "B.Cu" signal)\n'
        "\t)\n" + nets
    )


def _solid_zone(net: str, layer: str) -> str:
    return (
        "\t(zone\n"
        f'\t\t(net "{net}")\n'
        f'\t\t(layers "{layer}")\n'
        "\t\t(filled_polygon\n"
        f'\t\t\t(layer "{layer}")\n'
        "\t\t\t(pts (xy 2 2) (xy 58 2) (xy 58 38) (xy 2 38))\n"
        "\t\t)\n"
        "\t)\n"
    )


def _reference_net_trace_board() -> str:
    # A +3V3 trace on B.Cu whose only adjacent pour is the +3V3 In2.Cu plane.
    nets = '\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "+3V3")\n'
    return (
        _four_layer_header(nets=nets) + "\t(segment (start 10 10) (end 20 10) (width 0.25)"
        ' (layer "B.Cu") (net "+3V3"))\n' + _solid_zone("+3V3", "In2.Cu") + ")\n"
    )


def _board_with_propagation(signal_layer: str, top_reference: str | None) -> str:
    setup = ""
    if top_reference is not None:
        setup = (
            "\t(setup\n"
            "\t\t(track_propagation\n"
            f'\t\t\t(layer "{signal_layer}" (top_reference "{top_reference}"))\n'
            "\t\t)\n"
            "\t)\n"
        )
    nets = '\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "SIG")\n'
    return (
        _four_layer_header(nets=nets) + setup + "\t(segment (start 10 10) (end 20 10) (width 0.25)"
        ' (layer "B.Cu") (net "SIG"))\n'
        + _solid_zone("GND", "F.Cu")
        + _solid_zone("GND", "In2.Cu")
        + ")\n"
    )


def _slotted_declared_board() -> str:
    nets = '\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "SIG")\n'
    return (
        _four_layer_header(nets=nets) + "\t(setup\n\t\t(track_propagation\n"
        '\t\t\t(layer "B.Cu" (top_reference "In2.Cu"))\n'
        "\t\t)\n\t)\n" + "\t(segment (start 30 10) (end 30 30) (width 0.25)"
        ' (layer "B.Cu") (net "SIG"))\n' + "\t(zone\n"
        '\t\t(net "GND")\n'
        '\t\t(layers "In2.Cu")\n'
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts (xy 2 2) (xy 58 2) (xy 58 18) (xy 2 18))\n"
        "\t\t)\n"
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts (xy 2 22) (xy 58 22) (xy 58 38) (xy 2 38))\n"
        "\t\t)\n"
        "\t)\n" + ")\n"
    )


def _board_with_only_same_layer_plane() -> str:
    # A B.Cu trace whose only reference pour is on B.Cu itself → no adjacent plane.
    nets = '\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "SIG")\n'
    return (
        _four_layer_header(nets=nets) + "\t(segment (start 10 10) (end 20 10) (width 0.25)"
        ' (layer "B.Cu") (net "SIG"))\n' + _solid_zone("GND", "B.Cu") + ")\n"
    )


def _layered_board_with_tiny_power() -> str:
    nets = '\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "+3V3")\n'
    return (
        _four_layer_header(nets=nets) + _solid_zone("GND", "In2.Cu") + "\t(zone\n"
        '\t\t(net "+3V3")\n'
        '\t\t(layers "In2.Cu")\n'
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts (xy 1 1) (xy 1.5 1) (xy 1.5 1.5) (xy 1 1.5))\n"
        "\t\t)\n"
        "\t)\n" + ")\n"
    )
