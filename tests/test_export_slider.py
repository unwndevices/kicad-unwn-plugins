"""Slider exporters: footprint/symbol structure, pad<->pin 1:1, golden files."""

from __future__ import annotations

from pathlib import Path

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import build_slider
from captouch.params import SliderParams
from kicad_core import sexpr

GOLDEN = Path(__file__).parent / "golden"
SHAPES = ["rectangular", "chevron", "interdigitated"]


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
    geo = build_slider(SliderParams(segment_shape=shape))
    fp_node = footprint.slider_footprint(geo)
    pads = sexpr.find_all(fp_node, "pad")
    assert len(pads) == len(geo.electrodes)
    for pad in pads:
        flags = [c.name for c in sexpr.children(pad) if isinstance(c, sexpr.Sym)]
        assert "custom" in flags and "smd" in flags


@pytest.mark.parametrize("shape", SHAPES)
def test_pads_map_one_to_one_to_pins(shape):
    geo = build_slider(SliderParams(segment_shape=shape))
    fp_node = footprint.slider_footprint(geo)
    sym_node = symbol.slider_symbol_lib(geo)

    pad_nums = _pad_numbers(fp_node)
    pin_nums = _pin_numbers(sym_node)
    assert len(pad_nums) == len(geo.electrodes)
    assert len(pin_nums) == len(geo.electrodes)
    # exact 1:1 correspondence of the number sets
    assert sorted(pad_nums) == sorted(pin_nums)
    assert len(set(pin_nums)) == len(pin_nums)  # pins uniquely numbered


def test_footprint_has_courtyard_and_fab_outline():
    geo = build_slider(SliderParams())
    fp_node = footprint.slider_footprint(geo)
    layers = {sexpr.find(r, "layer")[1] for r in sexpr.find_all(fp_node, "fp_rect")}
    assert "F.CrtYd" in layers
    assert "F.Fab" in layers


def test_footprint_version_token():
    # Nodes built directly hold the integer date tokens; after a text round-trip
    # they re-read as bare symbols. Pin both: it is the format-drift guard.
    geo = build_slider(SliderParams())
    fp_node = footprint.slider_footprint(geo)
    assert sexpr.find(fp_node, "version")[1] == footprint.FOOTPRINT_VERSION == 20241229
    sym_node = symbol.slider_symbol_lib(geo)
    assert sexpr.find(sym_node, "version")[1] == symbol.SYMBOL_LIB_VERSION == 20241209


@pytest.mark.parametrize("shape", SHAPES)
def test_emitted_text_round_trips(shape):
    geo = build_slider(SliderParams(segment_shape=shape))
    for text in (footprint.slider_footprint_text(geo), symbol.slider_symbol_lib_text(geo)):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_rectangular_golden_footprint():
    geo = build_slider(SliderParams(name="CT_Slider_Rect", segment_shape="rectangular"))
    text = footprint.slider_footprint_text(geo)
    golden = (GOLDEN / "CT_Slider_Rect.kicad_mod").read_text()
    assert text == golden


def test_rectangular_golden_symbol():
    geo = build_slider(SliderParams(name="CT_Slider_Rect", segment_shape="rectangular"))
    text = symbol.slider_symbol_lib_text(geo)
    golden = (GOLDEN / "CT_Slider_Rect.kicad_sym").read_text()
    assert text == golden
