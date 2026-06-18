"""Integration gate: generated files render and pass DRC in an installed KiCad.

Skipped when ``kicad-cli`` is not on PATH. These are the authoritative
"it opens in KiCad" checks behind the unit tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import build_slider, build_trackpad, build_wheel
from captouch.params import SliderParams, TrackpadParams, WheelParams

from _board import trackpad_net_map, widget_board_text

KICAD_CLI = shutil.which("kicad-cli")
pytestmark = pytest.mark.skipif(KICAD_CLI is None, reason="kicad-cli not installed")

SHAPES = ["rectangular", "chevron", "interdigitated"]


def _wheel(shape):
    kw = dict(name="CT_Wheel", num_segments=5, segment_shape=shape,
              ring_width=5.0, air_gap=0.5, finger_diameter=8.0)
    if shape == "rectangular":
        kw["segment_width"] = 7.0
    return build_wheel(WheelParams(**kw))


def _run(*args):
    return subprocess.run(
        [KICAD_CLI, *args], capture_output=True, text=True, check=False
    )


def _drc(board_path, out_json):
    proc = _run("pcb", "drc", "--format", "json", "--severity-all",
                "--output", str(out_json), str(board_path))
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(out_json.read_text())


@pytest.mark.parametrize("shape", SHAPES)
def test_footprint_renders(shape, tmp_path):
    geo = build_slider(SliderParams(name="CT_Slider", segment_shape=shape))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Slider.kicad_mod").write_text(footprint.slider_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()  # kicad-cli does not create the output dir (and exits 0 if it fails)

    proc = _run("fp", "export", "svg", "--footprint", "CT_Slider",
                "--output", str(svg_dir), str(pretty))
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Slider.svg").exists()


def test_symbol_renders(tmp_path):
    geo = build_slider(SliderParams(name="CT_Slider"))
    sym = tmp_path / "CT_Slider.kicad_sym"
    sym.write_text(symbol.slider_symbol_lib_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run("sym", "export", "svg", "--output", str(svg_dir), str(sym))
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Slider_unit1.svg").exists()


@pytest.mark.parametrize("shape", SHAPES)
def test_drc_clean(shape, tmp_path):
    geo = build_slider(SliderParams(name="CT_Slider", segment_shape=shape))
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == []


def test_drc_catches_undersized_gap(tmp_path):
    # Negative control: a sub-clearance gap MUST be flagged, proving the DRC
    # gate is real and not vacuously passing on netless copper.
    geo = build_slider(SliderParams(
        name="TinyGap", segment_shape="rectangular",
        air_gap=0.05, relax_finger_constraint=True,
    ))
    board = tmp_path / "tiny.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "tiny.json")
    clearances = [v for v in report["violations"] if v["type"] == "clearance"]
    assert clearances, "expected clearance violations for a 0.05 mm gap"


# --------------------------------------------------------------------------- #
# wheel
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shape", SHAPES)
def test_wheel_footprint_renders(shape, tmp_path):
    geo = _wheel(shape)
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Wheel.kicad_mod").write_text(footprint.wheel_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()

    proc = _run("fp", "export", "svg", "--footprint", "CT_Wheel",
                "--output", str(svg_dir), str(pretty))
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Wheel.svg").exists()


@pytest.mark.parametrize("shape", SHAPES)
def test_wheel_drc_clean(shape, tmp_path):
    geo = _wheel(shape)
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == []


def test_wheel_sharp_chevron_tips_sliver(tmp_path):
    # Negative control: with tip rounding disabled, a chevron wheel's acute tips
    # taper to copper slivers — proving the default tip_radius relief (which
    # makes test_wheel_drc_clean[chevron] pass) is doing real work.
    geo = build_wheel(WheelParams(name="Sharp", segment_shape="chevron",
                                  num_segments=5, ring_width=5.0, air_gap=0.5,
                                  finger_diameter=8.0, tip_radius=0.0, corner_radius=0.0))
    board = tmp_path / "sharp.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "sharp.json")
    slivers = [v for v in report["violations"] if v["type"] == "copper_sliver"]
    assert slivers, "expected copper slivers for un-rounded chevron tips"


# --------------------------------------------------------------------------- #
# trackpad (two-layer diamond matrix with via bridges)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rows,cols", [(3, 3), (4, 5), (5, 5)])
def test_trackpad_drc_clean(rows, cols, tmp_path):
    # Real nets are assigned per Rx/Tx line, so this checks BOTH inter-net
    # clearance (Rx vs Tx copper, vias vs copper) AND connectivity: an empty
    # `unconnected_items` proves the via bridges actually join each Tx column
    # across the two layers (with nets unassigned the check would be vacuous).
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=rows, num_cols=cols))
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


def test_trackpad_footprint_renders(tmp_path):
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=4, num_cols=5))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Trackpad.kicad_mod").write_text(footprint.trackpad_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run("fp", "export", "svg", "--footprint", "CT_Trackpad",
                "--output", str(svg_dir), str(pretty))
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Trackpad.svg").exists()


@pytest.mark.parametrize("kw", [
    {"mask_shape": "rrect", "corner_radius": 2.0}, {"mask_shape": "circle"},
])
def test_trackpad_masked_footprint_renders(kw, tmp_path):
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=4, num_cols=4, **kw))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Trackpad.kicad_mod").write_text(footprint.trackpad_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run("fp", "export", "svg", "--footprint", "CT_Trackpad",
                "--output", str(svg_dir), str(pretty))
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Trackpad.svg").exists()


@pytest.mark.parametrize("rows,cols", [(4, 4), (5, 5), (6, 6)])
@pytest.mark.parametrize("kw", [
    {"mask_shape": "rrect", "corner_radius": 2.0}, {"mask_shape": "circle"},
])
def test_trackpad_masked_copper_drc_clean(kw, rows, cols, tmp_path):
    # Clipped circle/rrect copper must be DRC-clean AND fully connected across the
    # sizes where the mask drops corner diamonds: an empty unconnected_items proves
    # every kept Tx island is still bridged and no clipped Rx arc floats — the
    # correctness guarantee behind the centre-inside construction.
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=rows, num_cols=cols, **kw))
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


def test_trackpad_drc_catches_undersized_gap(tmp_path):
    # Negative control: shrinking the gap (and neck) below the fab clearance MUST
    # be flagged — proving Rx and Tx sit on distinct nets and the gate is real.
    geo = build_trackpad(TrackpadParams(name="TinyGap", num_rows=3, num_cols=3,
                                        diamond_gap=0.12, bridge_width=0.08))
    board = tmp_path / "tiny.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "tiny.json")
    clearances = [v for v in report["violations"] if v["type"] == "clearance"]
    assert clearances, "expected clearance violations for a 0.12 mm diamond gap"


def test_trackpad_bridges_required_for_connectivity(tmp_path):
    # Negative control for the bridge itself: drop the vias/straps and the Tx
    # columns fall apart into disconnected F.Cu diamonds → unconnected items.
    from dataclasses import replace as _replace

    geo = build_trackpad(TrackpadParams(name="NoBridge", num_rows=3, num_cols=3))
    stripped = _replace(geo, nets=[_replace(n, bcu=[], vias=[]) for n in geo.nets])
    board = tmp_path / "nobridge.kicad_pcb"
    board.write_text(widget_board_text(stripped, nets=trackpad_net_map(stripped)))
    report = _drc(board, tmp_path / "nobridge.json")
    assert report["unconnected_items"], "expected unconnected Tx diamonds without bridges"
