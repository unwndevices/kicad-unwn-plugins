"""Slider parameter validation and the W + 2A finger constraint."""

from __future__ import annotations

import pytest

from captouch.params import SLIDER_PRESETS, SliderError, SliderParams, validate_slider


def test_width_derived_from_finger_satisfies_constraint():
    p = SliderParams()  # segment_width None -> derived
    assert p.width == pytest.approx(p.finger_diameter - 2 * p.air_gap)
    assert p.width + 2 * p.air_gap == pytest.approx(p.finger_diameter)
    validate_slider(p)  # must not raise


def test_explicit_width_violating_constraint_is_rejected():
    p = SliderParams(segment_width=8.0, finger_diameter=8.0, air_gap=0.5)
    with pytest.raises(SliderError, match="finger constraint"):
        validate_slider(p)


def test_relax_flag_bypasses_finger_constraint():
    p = SliderParams(segment_width=8.0, finger_diameter=8.0, relax_finger_constraint=True)
    validate_slider(p)  # must not raise


@pytest.mark.parametrize("n", [0, 1, 2])
def test_too_few_segments_rejected(n):
    with pytest.raises(SliderError, match="num_segments"):
        validate_slider(SliderParams(num_segments=n))


def test_unknown_shape_rejected():
    with pytest.raises(SliderError, match="segment_shape"):
        validate_slider(SliderParams(segment_shape="zigzag"))


def test_tooth_depth_must_be_below_half_width():
    # amplitude >= W/2 would let adjacent boundaries collide.
    p = SliderParams(segment_shape="chevron", tooth_depth=10.0)
    with pytest.raises(SliderError, match="tooth_depth"):
        validate_slider(p)


@pytest.mark.parametrize("bad", [
    dict(air_gap=0.0),
    dict(segment_height=0.0),
    dict(end_dummies=3),
    dict(segment_width=-1.0, relax_finger_constraint=True),
])
def test_out_of_range_values_rejected(bad):
    with pytest.raises(SliderError):
        validate_slider(SliderParams(**bad))


def test_tip_radius_default_and_validation():
    assert SliderParams().tip_radius == 0.15
    with pytest.raises(SliderError, match="tip_radius"):
        validate_slider(SliderParams(tip_radius=-0.1))


@pytest.mark.parametrize("name", sorted(SLIDER_PRESETS))
def test_presets_are_valid(name):
    validate_slider(SLIDER_PRESETS[name])


def test_derived_quantities():
    p = SliderParams(num_segments=4, end_dummies=1)  # W=7, A=0.5
    assert p.num_physical_segments == 6
    assert p.pitch == pytest.approx(7.5)
    # M*W + (M-1)*A
    assert p.total_length == pytest.approx(6 * 7 + 5 * 0.5)
