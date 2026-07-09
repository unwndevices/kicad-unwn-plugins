"""Footprint emission of support copper: default-off identity, zones, net-tie, mask."""

from __future__ import annotations

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import build_slider, build_trackpad, build_wheel, net_tie_number
from captouch.params import SliderParams, TrackpadParams, WheelParams
from kicad_core import sexpr


def _pin_numbers(sym_lib):
    sym = sexpr.find(sym_lib, "symbol")
    nums = []
    for sub in sexpr.find_all(sym, "symbol"):
        for pin in sexpr.find_all(sub, "pin"):
            nums.append(sexpr.find(pin, "number")[1])
    return nums


def _pin_named(sym_lib, name):
    sym = sexpr.find(sym_lib, "symbol")
    out = []
    for sub in sexpr.find_all(sym, "symbol"):
        for pin in sexpr.find_all(sub, "pin"):
            if sexpr.find(pin, "name")[1] == name:
                out.append(sexpr.find(pin, "number")[1])
    return out


def _zones(node):
    return sexpr.find_all(node, "zone")


def _zone_layers(node):
    return sorted(sexpr.find(z, "layer")[1] for z in _zones(node))


def _fp_poly_layers(node):
    return [sexpr.find(p, "layer")[1] for p in sexpr.find_all(node, "fp_poly")]


# --------------------------------------------------------------------------- #
# default-off: no zones, byte-identical to the pre-Phase-8 output
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "build,params",
    [
        (build_slider, SliderParams(name="S")),
        (build_wheel, WheelParams(name="W")),
        (build_trackpad, TrackpadParams(name="T", num_rows=3, num_cols=3)),
    ],
)
def test_default_off_has_no_zones(build, params):
    geo = build(params)
    node = (
        footprint.trackpad_footprint(geo)
        if isinstance(params, TrackpadParams)
        else footprint.widget_footprint(geo)
    )
    assert _zones(node) == []
    assert "F.Mask" not in _fp_poly_layers(node)


def test_default_off_byte_identical_to_no_support_fields():
    # Two slider params that differ only in (unset / off) support fields must emit
    # the exact same footprint text — the off path is untouched.
    a = build_slider(SliderParams(name="X"))
    b = build_slider(
        SliderParams(name="X", guard_width=0.6, ground_margin=3.0)
    )  # off, values inert
    assert footprint.widget_footprint_text(a) == footprint.widget_footprint_text(b)


# --------------------------------------------------------------------------- #
# feature-on: zones, net-tie pad, F.Mask aperture, round-trip
# --------------------------------------------------------------------------- #
def test_ground_hatch_emits_bcu_hatched_zone():
    geo = build_slider(SliderParams(name="S", ground_hatch=True))
    node = footprint.widget_footprint(geo)
    zones = _zones(node)
    assert len(zones) == 1
    z = zones[0]
    assert sexpr.find(z, "layer")[1] == "B.Cu"
    fill = sexpr.find(z, "fill")
    assert sexpr.find(fill, "mode") is not None  # hatch mode present
    assert sexpr.find(fill, "hatch_thickness") is not None


def test_guard_ring_emits_fcu_solid_zone_and_mask_aperture():
    geo = build_slider(SliderParams(name="S", guard_ring=True, guard_mask_open=True))
    node = footprint.widget_footprint(geo)
    zones = _zones(node)
    assert _zone_layers(node) == ["F.Cu"]
    assert sexpr.find(sexpr.find(zones[0], "fill"), "mode") is None  # solid (no hatch mode)
    assert "F.Mask" in _fp_poly_layers(node)  # mask opened over the ring


def test_guard_ring_no_mask_open_omits_mask():
    geo = build_slider(SliderParams(name="S", guard_ring=True, guard_mask_open=False))
    node = footprint.widget_footprint(geo)
    assert "F.Mask" not in _fp_poly_layers(node)


def test_both_features_emit_two_zones_and_one_nettie_pad():
    geo = build_slider(
        SliderParams(name="S", num_segments=4, end_dummies=1, ground_hatch=True, guard_ring=True)
    )
    node = footprint.widget_footprint(geo)
    assert _zone_layers(node) == ["B.Cu", "F.Cu"]
    pads = sexpr.find_all(node, "pad")
    # 4 active + 2 dummy electrodes + 1 GND net-tie
    assert len(pads) == 7
    nettie = [
        p
        for p in pads
        if any(isinstance(c, sexpr.Sym) and c.name == "thru_hole" for c in sexpr.children(p))
    ]
    assert len(nettie) == 1
    assert sexpr.children(nettie[0])[0] == "7"  # numbered after the electrodes


def test_zone_net_is_emitted_netless():
    # A baked net_name on a net-0 zone crashes kicad-cli fp export svg; library
    # zones are emitted net-less and tied on the board.
    geo = build_slider(SliderParams(name="S", ground_hatch=True))
    z = _zones(footprint.widget_footprint(geo))[0]
    assert sexpr.find(z, "net")[1] == 0
    assert sexpr.find(z, "net_name")[1] == ""


@pytest.mark.parametrize(
    "build,params",
    [
        (build_slider, SliderParams(name="S", ground_hatch=True, guard_ring=True)),
        (build_wheel, WheelParams(name="W", ground_hatch=True, guard_ring=True)),
        (build_trackpad, TrackpadParams(name="T", ground_hatch=True, guard_ring=True)),
        (
            build_trackpad,
            TrackpadParams(name="T", mask_shape="circle", num_rows=4, num_cols=4, guard_ring=True),
        ),
    ],
)
def test_support_footprint_round_trips(build, params):
    geo = build(params)
    text = (
        footprint.trackpad_footprint_text(geo)
        if isinstance(params, TrackpadParams)
        else footprint.widget_footprint_text(geo)
    )
    assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


# --------------------------------------------------------------------------- #
# symbol: GND pin added when (and only when) support copper is enabled
# --------------------------------------------------------------------------- #
def test_symbol_gains_one_gnd_pin_when_enabled():
    off = symbol.widget_symbol_lib(build_wheel(WheelParams(name="W")))
    on = symbol.widget_symbol_lib(build_wheel(WheelParams(name="W", ground_hatch=True)))
    assert len(_pin_numbers(on)) == len(_pin_numbers(off)) + 1
    tie = net_tie_number(build_wheel(WheelParams(name="W", ground_hatch=True)))
    assert tie in _pin_named(on, "GND")  # the net-tie pin is named GND


def test_only_one_extra_pin_for_both_features():
    base = build_wheel(WheelParams(name="W"))
    both = build_wheel(WheelParams(name="W", ground_hatch=True, guard_ring=True))
    n = len(_pin_numbers(symbol.widget_symbol_lib(base)))
    assert len(_pin_numbers(symbol.widget_symbol_lib(both))) == n + 1  # one shared GND tie


@pytest.mark.parametrize(
    "build,params,fp_fn,sym_fn",
    [
        (
            build_slider,
            SliderParams(name="S", ground_hatch=True, guard_ring=True),
            footprint.widget_footprint,
            symbol.widget_symbol_lib,
        ),
        (
            build_trackpad,
            TrackpadParams(name="T", ground_hatch=True, guard_ring=True),
            footprint.trackpad_footprint,
            symbol.trackpad_symbol_lib,
        ),
    ],
)
def test_pads_and_pins_stay_one_to_one(build, params, fp_fn, sym_fn):
    geo = build(params)
    pad_nums = {sexpr.children(p)[0] for p in sexpr.find_all(fp_fn(geo), "pad")}
    pin_nums = set(_pin_numbers(sym_fn(geo)))
    assert pad_nums == pin_nums  # GND net-tie pad is matched by the GND pin


def test_off_symbol_unchanged():
    # No support copper -> the symbol is byte-identical to before (no GND tie pin).
    a = symbol.widget_symbol_lib_text(build_slider(SliderParams(name="S")))
    b = symbol.widget_symbol_lib_text(build_slider(SliderParams(name="S", guard_gap=3.0)))
    assert a == b


def test_validate_rejects_degenerate_zone():
    from captouch.export.footprint import FootprintError, _zone, validate_footprint

    geo = build_slider(SliderParams(name="S"))
    node = footprint.widget_footprint(geo)
    bad = _zone([(0.0, 0.0), (1.0, 0.0)], layer="B.Cu", min_thickness=0.18)  # 2 pts
    node = [*node[:-1], bad, node[-1]]
    with pytest.raises(FootprintError, match="zone polygon"):
        validate_footprint(node)
