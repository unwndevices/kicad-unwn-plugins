"""Button geometry: outline, fill styles, hat, naming, bounds."""

from __future__ import annotations

import pytest

from captouch.geometry import ButtonGeometry, build_button, build_support, net_tie_number
from captouch.params import BUTTON_OUTLINES, BUTTON_STYLES, ButtonError, ButtonParams


def test_default_builds_one_sense_electrode():
    geo = build_button(ButtonParams())
    assert isinstance(geo, ButtonGeometry)
    assert len(geo.active) == 1
    assert geo.dummies == []
    assert geo.active[0].pin_name == "BTN"
    assert geo.active[0].pad_number == "1"


@pytest.mark.parametrize("outline", BUTTON_OUTLINES)
@pytest.mark.parametrize("style", BUTTON_STYLES)
def test_every_outline_and_style_builds(outline, style):
    geo = build_button(ButtonParams(outline=outline, style=style, ground_hat=False))
    assert len(geo.electrodes) == 1
    poly = geo.electrodes[0].polygon
    assert poly.is_valid and poly.area > 0


def test_ground_hat_adds_gnd_dummy():
    geo = build_button(ButtonParams(style="radial", ground_hat=True))
    assert len(geo.active) == 1
    assert len(geo.dummies) == 1
    assert geo.dummies[0].pin_name == "GND"
    assert geo.dummies[0].pad_number == "2"
    overlap = geo.active[0].polygon.intersection(geo.dummies[0].polygon)
    assert overlap.area == pytest.approx(0.0, abs=1e-4)


@pytest.mark.parametrize("style", ["radial", "interdigitated", "chevron"])
def test_hat_styles_produce_two_pads(style):
    geo = build_button(ButtonParams(style=style, ground_hat=True, outline="square"))
    assert len(geo.electrodes) == 2
    assert geo.electrodes[0].polygon.area > 0
    assert geo.electrodes[1].polygon.area > 0


def test_patterned_has_less_copper_than_solid():
    solid = build_button(ButtonParams(style="solid", outline="circle", size=12.0))
    radial = build_button(ButtonParams(style="radial", outline="circle", size=12.0))
    assert radial.electrodes[0].polygon.area < solid.electrodes[0].polygon.area


def test_circle_fab_is_a_circle_square_is_a_rect():
    circ = build_button(ButtonParams(outline="circle"))
    assert circ.fab_primitives[0][0] == "circle"
    assert circ.courtyard_outline[0] == "circle"
    sq = build_button(ButtonParams(outline="square", style="solid"))
    assert sq.fab_primitives[0][0] == "rect"
    assert sq.courtyard_outline[0] == "rect"


def test_symbol_columns_put_hat_on_the_right():
    left, right = build_button(ButtonParams(ground_hat=True)).symbol_columns()
    assert left == [("1", "BTN")]
    assert right == [("2", "GND")]


def test_invalid_params_raise_before_geometry():
    with pytest.raises(ButtonError):
        build_button(ButtonParams(size=0))


def test_support_copper_builds_around_the_button():
    geo = build_button(ButtonParams(ground_hatch=True, guard_ring=True))
    sc = build_support(geo)
    assert sc is not None
    assert net_tie_number(geo) == "2"  # one past the sense pad


def test_hat_plus_support_net_tie_skips_both_pads():
    geo = build_button(ButtonParams(ground_hat=True, ground_hatch=True))
    assert net_tie_number(geo) == "3"
