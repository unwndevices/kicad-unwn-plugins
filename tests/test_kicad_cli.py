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
from captouch.geometry import build_slider, build_wheel
from captouch.params import SliderParams, WheelParams

from _board import widget_board_text

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
