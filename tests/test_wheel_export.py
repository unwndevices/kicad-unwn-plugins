"""Wheel exporters: footprint/symbol structure, pad<->pin 1:1, golden files."""

from __future__ import annotations

from pathlib import Path

import pytest

from captouch import sexpr
from captouch.export import footprint, symbol
from captouch.geometry import build_wheel
from captouch.params import WheelParams

GOLDEN = Path(__file__).parent / "golden"
SHAPES = ["rectangular", "chevron", "interdigitated", "spiral"]


def _params(shape, **kw):
    base = dict(
        name="CT_Wheel",
        num_segments=5,
        segment_shape=shape,
        ring_width=5.0,
        air_gap=0.5,
        finger_diameter=8.0,
    )
    if shape == "rectangular":
        base.update(segment_width=7.0)
    base.update(kw)
    return WheelParams(**base)


def _pad_numbers(fp_node):
    return [sexpr.children(p)[0] for p in sexpr.find_all(fp_node, "pad")]


def _pin_numbers(sym_lib_node):
    sym = sexpr.find(sym_lib_node, "symbol")
    nums = []
    for sub in sexpr.find_all(sym, "symbol"):
        for pin in sexpr.find_all(sub, "pin"):
            nums.append(sexpr.find(pin, "number")[1])
    return nums


@pytest.mark.parametrize("shape", SHAPES)
def test_one_pad_per_electrode(shape):
    geo = build_wheel(_params(shape))
    fp_node = footprint.wheel_footprint(geo)
    pads = sexpr.find_all(fp_node, "pad")
    assert len(pads) == len(geo.electrodes)
    for pad in pads:
        flags = [c.name for c in sexpr.children(pad) if isinstance(c, sexpr.Sym)]
        assert "custom" in flags and "smd" in flags


@pytest.mark.parametrize("shape", SHAPES)
def test_pads_map_one_to_one_to_pins(shape):
    geo = build_wheel(_params(shape))
    pad_nums = _pad_numbers(footprint.wheel_footprint(geo))
    pin_nums = _pin_numbers(symbol.wheel_symbol_lib(geo))
    assert len(pad_nums) == len(geo.electrodes)
    assert sorted(pad_nums) == sorted(pin_nums)
    assert len(set(pin_nums)) == len(pin_nums)


def test_footprint_uses_circular_outline():
    # A wheel documents itself with circles (outer + centre hole) and a circular
    # courtyard — not rectangles.
    geo = build_wheel(_params("chevron"))
    fp_node = footprint.wheel_footprint(geo)
    assert sexpr.find_all(fp_node, "fp_rect") == []
    circles = sexpr.find_all(fp_node, "fp_circle")
    layers = [sexpr.find(c, "layer")[1] for c in circles]
    assert layers.count("F.Fab") == 2  # outer edge + centre hole
    assert "F.CrtYd" in layers


def test_footprint_version_token():
    geo = build_wheel(_params("chevron"))
    fp_node = footprint.wheel_footprint(geo)
    assert sexpr.find(fp_node, "version")[1] == footprint.FOOTPRINT_VERSION == 20241229
    sym_node = symbol.wheel_symbol_lib(geo)
    assert sexpr.find(sym_node, "version")[1] == symbol.SYMBOL_LIB_VERSION == 20241209


@pytest.mark.parametrize("shape", SHAPES)
def test_emitted_text_round_trips(shape):
    geo = build_wheel(_params(shape))
    for text in (footprint.wheel_footprint_text(geo), symbol.wheel_symbol_lib_text(geo)):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_rectangular_golden_footprint():
    geo = build_wheel(
        WheelParams(
            name="CT_Wheel_Rect",
            segment_shape="rectangular",
            num_segments=4,
            segment_width=7.0,
            ring_width=5.0,
            air_gap=0.5,
            finger_diameter=8.0,
        )
    )
    text = footprint.wheel_footprint_text(geo)
    golden = (GOLDEN / "CT_Wheel_Rect.kicad_mod").read_text()
    assert text == golden


def test_rectangular_golden_symbol():
    geo = build_wheel(
        WheelParams(
            name="CT_Wheel_Rect",
            segment_shape="rectangular",
            num_segments=4,
            segment_width=7.0,
            ring_width=5.0,
            air_gap=0.5,
            finger_diameter=8.0,
        )
    )
    text = symbol.wheel_symbol_lib_text(geo)
    golden = (GOLDEN / "CT_Wheel_Rect.kicad_sym").read_text()
    assert text == golden


def _spiral_golden_params():
    return WheelParams(
        name="CT_Wheel_Spiral",
        segment_shape="spiral",
        num_segments=5,
        ring_width=5.0,
        air_gap=0.5,
        finger_diameter=8.0,
        spiral_angle=45.0,
    )


def test_spiral_golden_footprint():
    geo = build_wheel(_spiral_golden_params())
    text = footprint.wheel_footprint_text(geo)
    golden = (GOLDEN / "CT_Wheel_Spiral.kicad_mod").read_text()
    assert text == golden


def test_spiral_golden_symbol():
    geo = build_wheel(_spiral_golden_params())
    text = symbol.wheel_symbol_lib_text(geo)
    golden = (GOLDEN / "CT_Wheel_Spiral.kicad_sym").read_text()
    assert text == golden
