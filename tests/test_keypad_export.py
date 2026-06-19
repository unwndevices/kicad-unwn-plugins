"""Keypad exporters: pad structure, layers, pad<->pin 1:1, support zones, golden files."""

from __future__ import annotations

from pathlib import Path

import pytest

from captouch import sexpr
from captouch.export import footprint, symbol
from captouch.geometry import build_keypad
from captouch.params import KeypadParams

GOLDEN = Path(__file__).parent / "golden"
CONFIGS = [(1, 1), (2, 3), (3, 4)]

# Fixed, deterministic config backing the golden files: a 3×4 grid of 10 mm square
# keys (a numeric keypad layout), default 4 mm separation.
GOLDEN_PARAMS = KeypadParams(name="CT_Keypad_3x4", num_rows=3, num_cols=4)


def _pads(fp_node):
    return sexpr.find_all(fp_node, "pad")


def _pad_layers(pad):
    return list(sexpr.find(pad, "layers")[1:])


def _pin_numbers(sym_lib_node):
    sym = sexpr.find(sym_lib_node, "symbol")
    nums = []
    for sub in sexpr.find_all(sym, "symbol"):
        for pin in sexpr.find_all(sub, "pin"):
            nums.append(sexpr.find(pin, "number")[1])
    return nums


@pytest.mark.parametrize("rows,cols", CONFIGS)
def test_one_pad_per_button(rows, cols):
    geo = build_keypad(KeypadParams(num_rows=rows, num_cols=cols))
    pads = _pads(footprint.keypad_footprint(geo))
    assert len(pads) == rows * cols
    for p in pads:
        assert _pad_layers(p) == ["F.Cu"]  # discrete self-cap buttons on the top layer


@pytest.mark.parametrize("rows,cols", CONFIGS)
def test_pads_map_one_to_one_to_pins(rows, cols):
    geo = build_keypad(KeypadParams(num_rows=rows, num_cols=cols))
    pad_nums = [sexpr.children(p)[0] for p in _pads(footprint.keypad_footprint(geo))]
    pin_nums = _pin_numbers(symbol.keypad_symbol_lib(geo))
    assert sorted(pad_nums, key=int) == sorted(pin_nums, key=int)
    assert len(set(pad_nums)) == rows * cols  # every button distinct


@pytest.mark.parametrize(
    "shape,token", [("rect", "fp_rect"), ("circle", "fp_circle"), ("diamond", "fp_poly")]
)
def test_fab_outline_per_button_shape(shape, token):
    fp_node = footprint.keypad_footprint(
        build_keypad(KeypadParams(num_rows=2, num_cols=2, button_shape=shape))
    )
    fab = [n for n in sexpr.find_all(fp_node, token) if sexpr.find(n, "layer")[1] == "F.Fab"]
    assert len(fab) == 4  # one nominal F.Fab outline per button


def test_symbol_records_self_cap_series_r():
    sym_lib = symbol.keypad_symbol_lib(build_keypad(GOLDEN_PARAMS))
    sym = sexpr.find(sym_lib, "symbol")
    props = {p[1]: p[2] for p in sexpr.find_all(sym, "property")}
    assert "Series_R" in props and "560 Ω" in props["Series_R"]  # self-cap value


def test_support_zones_emitted_when_enabled():
    geo = build_keypad(
        KeypadParams(name="K", num_rows=2, num_cols=2, ground_hatch=True, guard_ring=True)
    )
    fp_node = footprint.keypad_footprint(geo)
    zones = sexpr.find_all(fp_node, "zone")
    assert len(zones) == 2  # B.Cu ground pour + F.Cu guard ring
    # one extra GND pin appended (5th, past the 4 buttons)
    pin_nums = _pin_numbers(symbol.keypad_symbol_lib(geo))
    assert "5" in pin_nums and len(pin_nums) == 5


def test_no_support_zones_by_default():
    fp_node = footprint.keypad_footprint(build_keypad(KeypadParams(num_rows=2, num_cols=2)))
    assert sexpr.find_all(fp_node, "zone") == []


@pytest.mark.parametrize("rows,cols", CONFIGS)
def test_emitted_text_round_trips(rows, cols):
    geo = build_keypad(KeypadParams(num_rows=rows, num_cols=cols))
    for text in (
        footprint.keypad_footprint_text(geo),
        symbol.keypad_symbol_lib_text(geo),
    ):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_golden_footprint():
    text = footprint.keypad_footprint_text(build_keypad(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Keypad_3x4.kicad_mod").read_text()


def test_golden_symbol():
    text = symbol.keypad_symbol_lib_text(build_keypad(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Keypad_3x4.kicad_sym").read_text()
