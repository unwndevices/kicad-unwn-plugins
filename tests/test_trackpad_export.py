"""Trackpad exporters: pad structure, layers, vias, pad<->pin 1:1, golden files."""

from __future__ import annotations

from pathlib import Path

import pytest

from captouch import sexpr
from captouch.export import footprint, symbol
from captouch.geometry import build_trackpad
from captouch.params import TrackpadParams

GOLDEN = Path(__file__).parent / "golden"
SIZES = [(3, 3), (4, 5)]

# Fixed, deterministic config that backs the golden files. 3x3 is the smallest
# matrix with interior crossings, so it exercises B.Cu straps and vias.
GOLDEN_PARAMS = TrackpadParams(name="CT_Trackpad_3x3", num_rows=3, num_cols=3)


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


@pytest.mark.parametrize("rows,cols", SIZES)
def test_pad_count_matches_geometry(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    expected = sum(len(n.fcu) + len(n.bcu) + len(n.vias) for n in geo.nets)
    assert len(_pads(footprint.trackpad_footprint(geo))) == expected


@pytest.mark.parametrize("rows,cols", SIZES)
def test_vias_are_thru_hole_with_drill(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    pads = _pads(footprint.trackpad_footprint(geo))
    vias = [p for p in pads if any(isinstance(c, sexpr.Sym) and c.name == "thru_hole"
                                   for c in sexpr.children(p))]
    assert len(vias) == sum(len(n.vias) for n in geo.nets)
    for v in vias:
        assert sexpr.find(v, "drill") is not None
        flags = [c.name for c in sexpr.children(v) if isinstance(c, sexpr.Sym)]
        assert "circle" in flags


@pytest.mark.parametrize("rows,cols", SIZES)
def test_layer_assignment(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    pads = _pads(footprint.trackpad_footprint(geo))
    has_bcu = [p for p in pads if "B.Cu" in _pad_layers(p) and "*.Cu" not in _pad_layers(p)]
    assert len(has_bcu) == sum(len(n.bcu) for n in geo.nets)  # straps on B.Cu
    # Rx (continuous) copper is F.Cu only — never a B.Cu strap.
    rx_pad_numbers = {n.pad_number for n in geo.rx_nets}
    for p in pads:
        if sexpr.children(p)[0] in rx_pad_numbers:
            assert _pad_layers(p) == ["F.Cu"]


@pytest.mark.parametrize("rows,cols", SIZES)
def test_pads_map_one_to_one_to_pins(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    pad_nums = {sexpr.children(p)[0] for p in _pads(footprint.trackpad_footprint(geo))}
    pin_nums = _pin_numbers(symbol.trackpad_symbol_lib(geo))
    assert len(pad_nums) == rows + cols  # one distinct number per Rx/Tx line
    assert sorted(pad_nums, key=int) == sorted(pin_nums, key=int)
    assert len(set(pin_nums)) == len(pin_nums)


def test_footprint_uses_rect_outline():
    geo = build_trackpad(GOLDEN_PARAMS)
    fp_node = footprint.trackpad_footprint(geo)
    assert sexpr.find_all(fp_node, "fp_circle") == []
    rects = sexpr.find_all(fp_node, "fp_rect")
    layers = [sexpr.find(r, "layer")[1] for r in rects]
    assert "F.Fab" in layers and "F.CrtYd" in layers


def test_rrect_mask_emits_fp_poly_fab_outline():
    # Stage A: rrect mask → F.Fab is a polyline fp_poly; courtyard stays a rect.
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4,
                                        mask_shape="rrect", corner_radius=2.0))
    fp_node = footprint.trackpad_footprint(geo)
    fab_polys = [p for p in sexpr.find_all(fp_node, "fp_poly")
                 if sexpr.find(p, "layer")[1] == "F.Fab"]
    assert len(fab_polys) == 1
    rects = sexpr.find_all(fp_node, "fp_rect")
    assert [sexpr.find(r, "layer")[1] for r in rects] == ["F.CrtYd"]


def test_circle_mask_emits_fp_circle_fab_outline():
    # Stage A: circle mask → F.Fab is an fp_circle; courtyard stays a rect.
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle"))
    fp_node = footprint.trackpad_footprint(geo)
    fab_circles = [c for c in sexpr.find_all(fp_node, "fp_circle")
                   if sexpr.find(c, "layer")[1] == "F.Fab"]
    assert len(fab_circles) == 1
    rects = sexpr.find_all(fp_node, "fp_rect")
    assert [sexpr.find(r, "layer")[1] for r in rects] == ["F.CrtYd"]


@pytest.mark.parametrize("shape,kw", [("rrect", {"corner_radius": 2.0}), ("circle", {})])
def test_masked_footprint_text_round_trips(shape, kw):
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape=shape, **kw))
    text = footprint.trackpad_footprint_text(geo)
    assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_version_tokens():
    geo = build_trackpad(GOLDEN_PARAMS)
    fp_node = footprint.trackpad_footprint(geo)
    assert sexpr.find(fp_node, "version")[1] == footprint.FOOTPRINT_VERSION == 20241229
    sym_node = symbol.trackpad_symbol_lib(geo)
    assert sexpr.find(sym_node, "version")[1] == symbol.SYMBOL_LIB_VERSION == 20241209


@pytest.mark.parametrize("rows,cols", SIZES)
def test_emitted_text_round_trips(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    for text in (footprint.trackpad_footprint_text(geo),
                 symbol.trackpad_symbol_lib_text(geo)):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_golden_footprint():
    text = footprint.trackpad_footprint_text(build_trackpad(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Trackpad_3x3.kicad_mod").read_text()


def test_golden_symbol():
    text = symbol.trackpad_symbol_lib_text(build_trackpad(GOLDEN_PARAMS))
    assert text == (GOLDEN / "CT_Trackpad_3x3.kicad_sym").read_text()
