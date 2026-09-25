"""Single self-cap button parameters: derivations, validation, presets, advisories."""

from __future__ import annotations

import math

import pytest

from captouch.params import (
    BUTTON_OUTLINES,
    BUTTON_PRESETS,
    BUTTON_STYLES,
    ButtonError,
    ButtonParams,
    SliderError,
    check_advisories,
    check_fab,
    params_from_json,
    params_to_json,
    recommended_series_r,
    validate_button,
)
from captouch.params.advisory import BUTTON_OVERLAY_SIZE_FACTOR


def test_error_is_a_slider_error():
    assert issubclass(ButtonError, SliderError)


def test_default_is_a_radial_circle():
    p = ButtonParams()
    assert p.outline == "circle"
    assert p.style == "radial"
    assert p.size == 12.0
    assert p.num_pins == 1
    assert p.ground_hat is False


def test_hat_adds_a_second_pin():
    assert ButtonParams(ground_hat=True).num_pins == 2


@pytest.mark.parametrize("outline", BUTTON_OUTLINES)
def test_valid_outlines_accepted(outline):
    validate_button(ButtonParams(outline=outline, style="solid"))


@pytest.mark.parametrize("style", BUTTON_STYLES)
def test_valid_styles_accepted(style):
    validate_button(ButtonParams(style=style, ground_hat=False))


def test_reject_unknown_outline_and_style():
    with pytest.raises(ButtonError, match="outline"):
        validate_button(ButtonParams(outline="hexagon"))
    with pytest.raises(ButtonError, match="style"):
        validate_button(ButtonParams(style="spiral"))


def test_reject_hat_on_solid_and_hatch():
    with pytest.raises(ButtonError, match="ground_hat"):
        validate_button(ButtonParams(style="solid", ground_hat=True))
    with pytest.raises(ButtonError, match="ground_hat"):
        validate_button(ButtonParams(style="hatch", ground_hat=True))


def test_reject_nonpositive_size():
    with pytest.raises(ButtonError, match="size"):
        validate_button(ButtonParams(size=0))


def test_reject_too_few_legs():
    with pytest.raises(ButtonError, match="num_legs"):
        validate_button(ButtonParams(style="radial", num_legs=2))


def test_reject_corner_radius_over_half():
    with pytest.raises(ButtonError, match="corner_radius"):
        validate_button(ButtonParams(outline="square", size=8.0, corner_radius=5.0))


def test_auto_leg_width_is_positive():
    p = ButtonParams()
    assert p.effective_leg_width > 0
    assert p.resolved().leg_width == pytest.approx(p.effective_leg_width)


def test_outline_area_circle_and_square():
    assert ButtonParams(outline="circle", size=10.0).outline_area == pytest.approx(math.pi * 25.0)
    assert ButtonParams(outline="square", size=10.0).outline_area == pytest.approx(100.0)


def test_self_cap_series_r_is_560():
    value, mode = recommended_series_r(ButtonParams())
    assert value == "560 Ω" and "self" in mode.lower()


def test_overlay_sizing_advisory_blocks_undersize():
    p = ButtonParams(size=5.0, overlay_thickness=2.0)  # need >= 6 mm
    sizing = [a for a in check_advisories(p) if a.feature == "button vs overlay sizing"]
    assert sizing and sizing[0].blocks
    assert BUTTON_OVERLAY_SIZE_FACTOR == 3.0


def test_overlay_advisories_off_without_overlay():
    features = {a.feature for a in check_advisories(ButtonParams())}
    assert "button vs overlay sizing" not in features


def test_json_round_trip_preserves_widget_identity():
    p = ButtonParams(outline="square", style="chevron", num_legs=6, name="RT")
    text = params_to_json(p)
    assert '"widget": "button"' in text
    back = params_from_json(text)
    assert isinstance(back, ButtonParams) and back == p


@pytest.mark.parametrize("key", sorted(BUTTON_PRESETS))
def test_presets_are_valid_and_clear_default_fab(key):
    p = BUTTON_PRESETS[key]
    assert validate_button(p) is p
    assert check_fab(p, "default") == [], f"{p.name} trips the default fab profile"
