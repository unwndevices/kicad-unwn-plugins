"""Wheel parameters: derivations, constraint validation, presets."""

from __future__ import annotations

import math

import pytest

from captouch.params import (
    WHEEL_PRESETS,
    SliderError,
    WheelError,
    WheelParams,
    validate_wheel,
)


def test_width_derived_from_finger():
    p = WheelParams(finger_diameter=8.0, air_gap=0.5, segment_width=None)
    assert p.width == pytest.approx(7.0)  # finger - 2A


def test_explicit_width_overrides_finger():
    p = WheelParams(segment_width=6.0)
    assert p.width == 6.0


def test_mean_radius_derived_from_pitch():
    # circumference = num_segments * (W + A); mean_radius = circ / 2pi.
    p = WheelParams(num_segments=5, segment_width=7.0, air_gap=0.5)
    assert p.pitch == pytest.approx(7.5)
    assert p.mean_circumference == pytest.approx(37.5)
    assert p.mean_radius == pytest.approx(37.5 / (2 * math.pi))


def test_inner_outer_radius_from_ring_width():
    p = WheelParams(ring_width=5.0)
    assert p.outer_radius - p.inner_radius == pytest.approx(5.0)
    assert (p.inner_radius + p.outer_radius) / 2 == pytest.approx(p.mean_radius)
    assert p.center_hole_diameter == pytest.approx(2 * p.inner_radius)


def test_rectangular_amplitude_is_zero():
    assert WheelParams(segment_shape="rectangular").amplitude == 0.0


def test_arc_per_segment():
    assert WheelParams(num_segments=8).arc_per_segment_deg == pytest.approx(45.0)


def test_tip_radius_default_and_validation():
    assert WheelParams().tip_radius == 0.15
    with pytest.raises(WheelError, match="tip_radius"):
        validate_wheel(WheelParams(tip_radius=-0.1))


@pytest.mark.parametrize("key", sorted(WHEEL_PRESETS))
def test_presets_validate(key):
    validate_wheel(WHEEL_PRESETS[key])  # must not raise


def test_wheel_error_is_a_slider_error():
    # so callers can catch either widget's constraint failure with one except.
    assert issubclass(WheelError, SliderError)


def test_reject_bad_shape():
    with pytest.raises(WheelError):
        validate_wheel(WheelParams(segment_shape="zigzag"))


def test_reject_too_few_segments():
    with pytest.raises(WheelError):
        validate_wheel(WheelParams(num_segments=2))


def test_reject_nonpositive_ring_width():
    with pytest.raises(WheelError):
        validate_wheel(WheelParams(ring_width=0.0))


def test_reject_ring_wider_than_radius():
    # A huge ring drives the inner radius negative.
    with pytest.raises(WheelError, match="inner radius"):
        validate_wheel(WheelParams(num_segments=4, ring_width=40.0))


def test_reject_centre_collision():
    # A wide ring on a small-pitch ring shrinks the hole until the M gaps no
    # longer fit around it (inner arc pitch <= air_gap), though inner_radius > 0.
    p = WheelParams(num_segments=12, segment_shape="rectangular", segment_width=1.0,
                    air_gap=1.0, ring_width=6.0, relax_finger_constraint=True)
    assert p.inner_radius > 0  # not caught by the simpler radius check
    with pytest.raises(WheelError, match="centre hole"):
        validate_wheel(p)


def test_reject_finger_constraint_violation():
    with pytest.raises(WheelError, match="finger constraint"):
        validate_wheel(WheelParams(segment_width=8.0, air_gap=0.5, finger_diameter=20.0))


def test_relax_finger_constraint_allows_mismatch():
    validate_wheel(
        WheelParams(segment_width=8.0, air_gap=0.5, finger_diameter=20.0,
                    relax_finger_constraint=True)
    )


def test_reject_tooth_depth_at_or_above_half_width():
    with pytest.raises(WheelError, match="tooth_depth"):
        validate_wheel(WheelParams(segment_shape="chevron", segment_width=7.0,
                                   air_gap=0.5, finger_diameter=8.0, tooth_depth=4.0))
