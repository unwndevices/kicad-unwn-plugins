"""Mutual-cap slider exporters: pad structure, layers, pad<->pin 1:1, golden files."""

from __future__ import annotations

from pathlib import Path

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import build_mutual_slider
from captouch.params import MutualSliderParams
from kicad_core import sexpr

GOLDEN = Path(__file__).parent / "golden"
CONFIGS = [(3, 1), (5, 1), (5, 2)]

# Fixed, deterministic config that backs the golden files: the canonical single-Y
# mutual slider — one Rx sense line spanning five Tx drive electrodes (6 pins).
GOLDEN_PARAMS = MutualSliderParams(name="CT_MutualSlider_5", num_segments=5, sense_rows=1)


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


@pytest.mark.parametrize("segments,rows", CONFIGS)
def test_pad_count_matches_geometry(segments, rows):
    geo = build_mutual_slider(MutualSliderParams(num_segments=segments, sense_rows=rows))
    expected = sum(len(n.fcu) + len(n.bcu) + len(n.vias) for n in geo.nets)
    assert len(_pads(footprint.mutual_slider_footprint(geo))) == expected


@pytest.mark.parametrize("segments,rows", CONFIGS)
def test_pads_map_one_to_one_to_pins(segments, rows):
    geo = build_mutual_slider(MutualSliderParams(num_segments=segments, sense_rows=rows))
    pad_nums = {sexpr.children(p)[0] for p in _pads(footprint.mutual_slider_footprint(geo))}
    pin_nums = _pin_numbers(symbol.mutual_slider_symbol_lib(geo))
    assert len(pad_nums) == segments + rows  # one distinct number per Tx/Rx line
    assert sorted(pad_nums, key=int) == sorted(pin_nums, key=int)
    assert len(set(pin_nums)) == len(pin_nums)


def test_sense_line_is_fcu_only_drive_straps_on_bcu():
    geo = build_mutual_slider(MutualSliderParams(num_segments=5, sense_rows=1))
    pads = _pads(footprint.mutual_slider_footprint(geo))
    rx_numbers = {n.pad_number for n in geo.rx_nets}
    for p in pads:
        if sexpr.children(p)[0] in rx_numbers:
            assert _pad_layers(p) == ["F.Cu"]  # sense line never on B.Cu
    has_bcu = [p for p in pads if "B.Cu" in _pad_layers(p) and "*.Cu" not in _pad_layers(p)]
    assert len(has_bcu) == sum(len(n.bcu) for n in geo.nets)  # drive straps on B.Cu


def test_footprint_uses_rect_outline():
    fp_node = footprint.mutual_slider_footprint(build_mutual_slider(GOLDEN_PARAMS))
    assert sexpr.find_all(fp_node, "fp_circle") == []
    layers = [sexpr.find(r, "layer")[1] for r in sexpr.find_all(fp_node, "fp_rect")]
    assert "F.Fab" in layers and "F.CrtYd" in layers


def test_symbol_records_mutual_series_r():
    sym_lib = symbol.mutual_slider_symbol_lib(build_mutual_slider(GOLDEN_PARAMS))
    sym = sexpr.find(sym_lib, "symbol")  # properties live on the inner symbol node
    props = {p[1]: p[2] for p in sexpr.find_all(sym, "property")}
    assert "Series_R" in props and "2 kΩ" in props["Series_R"]  # mutual-cap value


@pytest.mark.parametrize("segments,rows", CONFIGS)
def test_emitted_text_round_trips(segments, rows):
    geo = build_mutual_slider(MutualSliderParams(num_segments=segments, sense_rows=rows))
    for text in (
        footprint.mutual_slider_footprint_text(geo),
        symbol.mutual_slider_symbol_lib_text(geo),
    ):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_golden_footprint():
    text = footprint.mutual_slider_footprint_text(build_mutual_slider(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_MutualSlider_5.kicad_mod").read_text()


def test_golden_symbol():
    text = symbol.mutual_slider_symbol_lib_text(build_mutual_slider(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_MutualSlider_5.kicad_sym").read_text()
