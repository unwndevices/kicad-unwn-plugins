"""Integration gate: generated files render and pass DRC in an installed KiCad.

Skipped when ``kicad-cli`` is not on PATH. These are the authoritative
"it opens in KiCad" checks behind the unit tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from _board import support_board_text, trackpad_net_map, widget_board_text

from captouch.export import footprint, symbol
from captouch.geometry import (
    build_keypad,
    build_mutual_slider,
    build_slider,
    build_support,
    build_trackpad,
    build_wheel,
)
from captouch.params import (
    BUTTON_SHAPES,
    KeypadParams,
    MutualSliderParams,
    SliderParams,
    TrackpadParams,
    WheelParams,
)

KICAD_CLI = shutil.which("kicad-cli")
pytestmark = pytest.mark.skipif(KICAD_CLI is None, reason="kicad-cli not installed")

SHAPES = ["rectangular", "chevron", "interdigitated"]


def _wheel(shape):
    kw = dict(
        name="CT_Wheel",
        num_segments=5,
        segment_shape=shape,
        ring_width=5.0,
        air_gap=0.5,
        finger_diameter=8.0,
    )
    if shape == "rectangular":
        kw["segment_width"] = 7.0
    return build_wheel(WheelParams(**kw))


def _run(*args):
    return subprocess.run([KICAD_CLI, *args], capture_output=True, text=True, check=False)


def _drc(board_path, out_json, *, refill=False):
    args = ["pcb", "drc", "--format", "json", "--severity-all"]
    if refill:  # required for any board carrying zones (the filler runs before DRC)
        args.append("--refill-zones")
    args += ["--output", str(out_json), str(board_path)]
    proc = _run(*args)
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

    proc = _run(
        "fp", "export", "svg", "--footprint", "CT_Slider", "--output", str(svg_dir), str(pretty)
    )
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
    geo = build_slider(
        SliderParams(
            name="TinyGap",
            segment_shape="rectangular",
            air_gap=0.05,
            relax_finger_constraint=True,
        )
    )
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

    proc = _run(
        "fp", "export", "svg", "--footprint", "CT_Wheel", "--output", str(svg_dir), str(pretty)
    )
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
    geo = build_wheel(
        WheelParams(
            name="Sharp",
            segment_shape="chevron",
            num_segments=5,
            ring_width=5.0,
            air_gap=0.5,
            finger_diameter=8.0,
            tip_radius=0.0,
            corner_radius=0.0,
        )
    )
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
    proc = _run(
        "fp", "export", "svg", "--footprint", "CT_Trackpad", "--output", str(svg_dir), str(pretty)
    )
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Trackpad.svg").exists()


@pytest.mark.parametrize(
    "kw",
    [
        {"mask_shape": "rrect", "corner_radius": 2.0},
        {"mask_shape": "circle"},
    ],
)
def test_trackpad_masked_footprint_renders(kw, tmp_path):
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=4, num_cols=4, **kw))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Trackpad.kicad_mod").write_text(footprint.trackpad_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run(
        "fp", "export", "svg", "--footprint", "CT_Trackpad", "--output", str(svg_dir), str(pretty)
    )
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Trackpad.svg").exists()


@pytest.mark.parametrize("rows,cols", [(4, 4), (5, 5), (6, 6)])
@pytest.mark.parametrize(
    "kw",
    [
        {"mask_shape": "rrect", "corner_radius": 2.0},
        {"mask_shape": "circle"},
        {"mask_shape": "rrect", "corner_radius": 2.0, "clip_mode": "conform"},
        {"mask_shape": "circle", "clip_mode": "conform"},
    ],
)
def test_trackpad_masked_copper_drc_clean(kw, rows, cols, tmp_path):
    # Clipped circle/rrect copper must be DRC-clean AND fully connected across the
    # sizes where the mask drops corner diamonds, in BOTH clip modes: an empty
    # unconnected_items proves every kept Tx island is still bridged and no clipped
    # Rx arc floats. For conform this also exercises the cut rim partials — the via
    # centres still land on copper and the min-width open leaves no slivers.
    geo = build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=rows, num_cols=cols, **kw))
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


@pytest.mark.parametrize(
    "kw",
    [
        {"mask_shape": "circle", "clip_mode": "conform"},
        {"mask_shape": "rrect", "corner_radius": 6.0, "clip_mode": "conform"},
    ],
)
def test_trackpad_conform_large_drc_clean(kw, tmp_path):
    # A larger conform pad cuts many rim diamonds into partial channels; it must
    # still pass DRC and stay fully connected. The circle case here also leaves
    # below-threshold partials, exercising the rim where the cut is deepest.
    geo = build_trackpad(
        TrackpadParams(name="CT_Trackpad", num_rows=7, num_cols=7, diamond_pitch=6.0, **kw)
    )
    if kw["mask_shape"] == "circle":
        assert geo.partial_channels(), "expected sub-threshold rim channels to report"
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


@pytest.mark.parametrize("w,h", [(28, 23), (52, 38)])
def test_trackpad_panel_sized_drc_clean(w, h, tmp_path):
    # Size-driven pads: the outline is pinned to the target, so the rounded lattice
    # overflows it (rim diamonds trimmed by the rect-box clip) on at least one axis.
    # The cut partials must stay DRC-clean and fully connected — vias still land on
    # copper, no floating rim copper — exactly as for a conform curved mask.
    # 28x23 trims both axes; 52x38 trims height while the width insets (empty margin).
    p = TrackpadParams.from_size(w, h, diamond_pitch=5.0, name="CT_Trackpad")
    assert p.lattice_width > p.width or p.lattice_height > p.height  # the lattice is trimmed
    geo = build_trackpad(p)
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


def test_trackpad_drc_catches_undersized_gap(tmp_path):
    # Negative control: shrinking the gap (and neck) below the fab clearance MUST
    # be flagged — proving Rx and Tx sit on distinct nets and the gate is real.
    geo = build_trackpad(
        TrackpadParams(name="TinyGap", num_rows=3, num_cols=3, diamond_gap=0.12, bridge_width=0.08)
    )
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


# --------------------------------------------------------------------------- #
# mutual-cap slider (a 1-row diamond matrix with via bridges)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("segments,rows", [(3, 1), (5, 1), (6, 2)])
def test_mutual_slider_drc_clean(segments, rows, tmp_path):
    # Real nets per Rx/Tx line: an empty `violations` proves inter-net clearance
    # (Rx sense line vs Tx drive copper, vias vs copper), and an empty
    # `unconnected_items` proves the via bridges join each Tx drive electrode
    # across the two layers over the single continuous sense row.
    geo = build_mutual_slider(MutualSliderParams(name="MS", num_segments=segments, sense_rows=rows))
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo, nets=trackpad_net_map(geo)))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


def test_mutual_slider_footprint_renders(tmp_path):
    geo = build_mutual_slider(MutualSliderParams(name="CT_MutualSlider", num_segments=5))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_MutualSlider.kicad_mod").write_text(footprint.mutual_slider_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run(
        "fp",
        "export",
        "svg",
        "--footprint",
        "CT_MutualSlider",
        "--output",
        str(svg_dir),
        str(pretty),
    )
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_MutualSlider.svg").exists()


# --------------------------------------------------------------------------- #
# keypad (discrete self-cap button grid)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shape", BUTTON_SHAPES)
@pytest.mark.parametrize("rows,cols", [(2, 3), (3, 4)])
def test_keypad_drc_clean(shape, rows, cols, tmp_path):
    # Buttons are independent netless copper (like a slider): an empty `violations`
    # proves every button keeps clearance from its neighbours at the default 4 mm
    # separation, and an empty `unconnected_items` (no nets) confirms there is
    # nothing left dangling.
    geo = build_keypad(
        KeypadParams(name="CT_Keypad", num_rows=rows, num_cols=cols, button_shape=shape)
    )
    board = tmp_path / "board.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "drc.json")
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == []


@pytest.mark.parametrize("shape", BUTTON_SHAPES)
def test_keypad_footprint_renders(shape, tmp_path):
    geo = build_keypad(KeypadParams(name="CT_Keypad", num_rows=2, num_cols=3, button_shape=shape))
    pretty = tmp_path / "lib.pretty"
    pretty.mkdir()
    (pretty / "CT_Keypad.kicad_mod").write_text(footprint.keypad_footprint_text(geo))
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    proc = _run(
        "fp", "export", "svg", "--footprint", "CT_Keypad", "--output", str(svg_dir), str(pretty)
    )
    assert proc.returncode == 0 and "Error" not in proc.stdout, proc.stdout + proc.stderr
    assert (svg_dir / "CT_Keypad.svg").exists()


def test_keypad_drc_catches_undersized_gap(tmp_path):
    # Negative control: a sub-clearance button-to-button gap MUST be flagged,
    # proving the DRC gate is real and not vacuously passing on the spaced grid.
    geo = build_keypad(KeypadParams(name="TinyGap", num_rows=2, num_cols=2, gap=0.05))
    board = tmp_path / "tiny.kicad_pcb"
    board.write_text(widget_board_text(geo))
    report = _drc(board, tmp_path / "tiny.json")
    clearances = [v for v in report["violations"] if v["type"] == "clearance"]
    assert clearances, "expected clearance violations for a 0.05 mm button gap"


# --------------------------------------------------------------------------- #
# support copper (Phase 8): hatched ground + guard / ESD ring
# --------------------------------------------------------------------------- #
# kicad-cli does not refill footprint-embedded zones, so support_board_text lifts
# them to board level on the GND net; --refill-zones then fills them for real. An
# empty `violations` proves the filled GND pour keeps clearance from the electrode
# nets; an empty `unconnected_items` proves the GND net-tie + probe pad are bridged
# by the fill (the geometry is correct and the tie works).
def _probe(geo, sc):
    """A point in the (ground or guard) pour but clear of the electrode area — a
    second GND point reachable only through the filled pour."""
    from shapely.geometry import box as _box

    zone = sc.ground if sc.ground is not None else sc.guard
    minx, miny, maxx, maxy = geo.bounds
    safe = zone.difference(_box(minx, miny, maxx, maxy).buffer(0.5))  # outside the electrodes
    p = safe.representative_point()
    return (round(p.x, 4), round(p.y, 4))


SUPPORT_CASES = [
    ("slider_ground", build_slider, SliderParams(name="S", ground_hatch=True)),
    ("slider_guard", build_slider, SliderParams(name="S", guard_ring=True)),
    ("slider_both", build_slider, SliderParams(name="S", ground_hatch=True, guard_ring=True)),
    ("wheel_both", build_wheel, WheelParams(name="W", ground_hatch=True, guard_ring=True)),
    (
        "keypad_both",
        build_keypad,
        KeypadParams(name="K", num_rows=2, num_cols=2, ground_hatch=True, guard_ring=True),
    ),
    (
        "trackpad_both",
        build_trackpad,
        TrackpadParams(name="T", num_rows=4, num_cols=5, ground_hatch=True, guard_ring=True),
    ),
    (
        "trackpad_circle",
        build_trackpad,
        TrackpadParams(
            name="T",
            num_rows=4,
            num_cols=4,
            mask_shape="circle",
            ground_hatch=True,
            guard_ring=True,
        ),
    ),
]


@pytest.mark.parametrize("label,build,params", SUPPORT_CASES, ids=[c[0] for c in SUPPORT_CASES])
def test_support_copper_drc_clean(label, build, params, tmp_path):
    geo = build(params)
    sc = build_support(geo)
    board = tmp_path / "board.kicad_pcb"
    board.write_text(support_board_text(geo, probe_at=_probe(geo, sc)))
    report = _drc(board, tmp_path / "drc.json", refill=True)
    assert report["violations"] == [], report["violations"]
    assert report["unconnected_items"] == [], report["unconnected_items"]


def test_support_pour_required_for_gnd_connectivity(tmp_path):
    # Negative control: without the lifted GND pour, the net-tie and the probe pad
    # are two isolated GND points → unconnected. Proves the fill (not something
    # else) is what ties the support copper to GND.
    geo = build_slider(SliderParams(name="S", ground_hatch=True, guard_ring=True))
    sc = build_support(geo)
    board = tmp_path / "board.kicad_pcb"
    board.write_text(support_board_text(geo, with_zones=False, probe_at=_probe(geo, sc)))
    report = _drc(board, tmp_path / "drc.json", refill=True)
    assert report["unconnected_items"], "expected a floating GND probe without the pour"
