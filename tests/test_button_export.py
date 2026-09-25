"""Button exporters: pad structure, layers, pad<->pin 1:1, golden files."""

from __future__ import annotations

from pathlib import Path

from captouch.export import footprint, symbol
from captouch.geometry import build_button
from captouch.params import ButtonParams
from kicad_core import sexpr

GOLDEN = Path(__file__).parent / "golden"
GOLDEN_PARAMS = ButtonParams(name="CT_Button_Snowflake")


def _pads(fp_node):
    return sexpr.find_all(fp_node, "pad")


def _pin_numbers(sym_lib_node):
    nums = []
    for sub in sexpr.find_all(sexpr.find(sym_lib_node, "symbol"), "symbol"):
        for pin in sexpr.find_all(sub, "pin"):
            nums.append(sexpr.find(pin, "number")[1])
    return nums


def test_one_pad_for_solid_sense():
    geo = build_button(ButtonParams(style="solid"))
    pads = _pads(footprint.button_footprint(geo))
    assert len(pads) == 1
    assert list(sexpr.find(pads[0], "layers")[1:]) == ["F.Cu"]


def test_hat_emits_two_pads_mapped_to_pins():
    geo = build_button(ButtonParams(name="B", style="radial", ground_hat=True))
    pad_nums = [sexpr.children(p)[0] for p in _pads(footprint.button_footprint(geo))]
    pin_nums = _pin_numbers(symbol.button_symbol_lib(geo))
    assert sorted(pad_nums, key=int) == sorted(pin_nums, key=int) == ["1", "2"]


def test_symbol_records_self_cap_series_r():
    sym = sexpr.find(symbol.button_symbol_lib(build_button(GOLDEN_PARAMS)), "symbol")
    props = {p[1]: p[2] for p in sexpr.find_all(sym, "property")}
    assert "Series_R" in props and "560 Ω" in props["Series_R"]


def test_circle_fab_outline():
    fp_node = footprint.button_footprint(build_button(ButtonParams(outline="circle")))
    fab = [n for n in sexpr.find_all(fp_node, "fp_circle") if sexpr.find(n, "layer")[1] == "F.Fab"]
    assert len(fab) == 1


def test_emitted_text_round_trips():
    geo = build_button(GOLDEN_PARAMS)
    for text in (
        footprint.button_footprint_text(geo),
        symbol.button_symbol_lib_text(geo),
    ):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_golden_footprint():
    text = footprint.button_footprint_text(build_button(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Button_Snowflake.kicad_mod").read_text()


def test_golden_symbol():
    text = symbol.button_symbol_lib_text(build_button(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Button_Snowflake.kicad_sym").read_text()
