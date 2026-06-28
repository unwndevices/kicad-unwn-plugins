"""Sensitivity/filtering advisories: series-R, overlay sizing, Cp budget."""

from __future__ import annotations

from dataclasses import replace

import pytest

from captouch.params import (
    WHEEL_PRESETS,
    SliderParams,
    TrackpadParams,
    WheelParams,
    check_advisories,
    estimate_cp_pf,
    recommended_series_r,
)
from captouch.params.advisory import CP_BUDGET_SELF_PF, SERIES_R_MUTUAL, SERIES_R_SELF


def _features(advisories):
    return {a.feature for a in advisories}


def _one(advisories, feature):
    matches = [a for a in advisories if a.feature == feature]
    assert len(matches) == 1, f"expected exactly one {feature!r}, got {advisories}"
    return matches[0]


# -- series resistor (always present, never blocks) -------------------------- #
def test_series_r_self_cap_for_slider_and_wheel():
    for p in (SliderParams(), WheelParams()):
        adv = _one(check_advisories(p), "series resistor")
        assert SERIES_R_SELF in adv.message
        assert adv.blocks is False
    assert recommended_series_r(SliderParams())[0] == SERIES_R_SELF


def test_series_r_mutual_cap_for_trackpad():
    adv = _one(check_advisories(TrackpadParams()), "series resistor")
    assert SERIES_R_MUTUAL in adv.message
    assert adv.blocks is False
    assert recommended_series_r(TrackpadParams())[0] == SERIES_R_MUTUAL


# -- overlay-dependent items are gated on an overlay being specified --------- #
def test_no_overlay_yields_only_series_r_on_a_normal_part():
    # default geometry is well under the Cp budget, so with no overlay the only
    # advisory is the (informational) series-R recommendation.
    assert _features(check_advisories(SliderParams())) == {"series resistor"}
    assert _features(check_advisories(TrackpadParams())) == {"series resistor"}


# -- electrode-vs-overlay sizing (slider / wheel) ---------------------------- #
def test_undersized_slider_triggers_sizing_warning_and_blocks():
    # segment_height 8 mm < finger 8 + 2 x 2 mm overlay = 12 mm.
    p = SliderParams(segment_height=8.0, overlay_thickness=2.0)
    adv = _one(check_advisories(p), "electrode vs overlay sizing")
    assert adv.blocks is True
    assert "8.00 mm" in adv.message and "12.00 mm" in adv.message


def test_well_sized_slider_has_no_sizing_warning():
    p = SliderParams(overlay_thickness=0.5)  # height 12 >= finger 8 + 1
    assert "electrode vs overlay sizing" not in _features(check_advisories(p))


def test_overlay_adds_sensitivity_note_using_er():
    p = SliderParams(overlay_thickness=1.0, overlay_er=7.8)
    note = _one(check_advisories(p), "overlay sensitivity")
    assert note.blocks is False
    assert "7.8" in note.message


# -- trackpad overlay-thickness window --------------------------------------- #
def test_trackpad_overlay_too_thick_warns():
    adv = _one(check_advisories(TrackpadParams(overlay_thickness=5.0)), "overlay thickness")
    assert adv.blocks is True
    assert "maximum" in adv.message


def test_trackpad_overlay_too_thin_warns():
    adv = _one(check_advisories(TrackpadParams(overlay_thickness=0.2)), "overlay thickness")
    assert adv.blocks is True
    assert "minimum" in adv.message


def test_trackpad_overlay_in_window_no_thickness_warning():
    feats = _features(check_advisories(TrackpadParams(overlay_thickness=1.0)))
    assert "overlay thickness" not in feats


# -- parasitic Cp budget ----------------------------------------------------- #
def test_oversized_electrode_exceeds_cp_budget_and_blocks():
    p = SliderParams(
        segment_shape="rectangular",
        segment_width=40.0,
        segment_height=40.0,
        relax_finger_constraint=True,
    )
    adv = _one(check_advisories(p), "parasitic Cp")
    assert adv.blocks is True


def test_normal_electrode_under_cp_budget():
    assert "parasitic Cp" not in _features(check_advisories(SliderParams()))


def test_estimate_cp_pf_parallel_plate_value():
    # 96 mm^2 over 1.6 mm FR-4 (er 4.5) ~ 2.4 pF.
    assert estimate_cp_pf(96.0, 1.6) == pytest.approx(2.39, abs=0.05)
    # well under the self-cap budget headroom.
    assert estimate_cp_pf(96.0, 1.6) < CP_BUDGET_SELF_PF


# -- spiral copper slivers (wheel only) -------------------------------------- #
def test_steep_spiral_triggers_sliver_advisory_and_blocks():
    # The 45° preset on a narrow (2 mm) ring drives the outer-edge corner well
    # below the 20° minimum (~13°), so exactly one blocking advisory fires.
    p = replace(WHEEL_PRESETS["spiral"], ring_width=2.0, spiral_angle=70.0)
    adv = _one(check_advisories(p), "spiral copper slivers")
    assert adv.blocks is True
    assert "DRC" in adv.message and "spiral_angle" in adv.message


def test_max_legal_spiral_angle_still_slivers():
    # 90° is the hard cap, yet on the stock 6 mm ring it still pinches to ~20°,
    # so the geometry-aware guard catches what the sanity ceiling alone cannot.
    p = replace(WHEEL_PRESETS["spiral"], spiral_angle=90.0)
    adv = _one(check_advisories(p), "spiral copper slivers")
    assert adv.blocks is True


def test_spiral_preset_has_no_sliver_advisory():
    # The shipped 45° / 6 mm-ring preset is a ~35° outer corner: comfortably quiet.
    assert "spiral copper slivers" not in _features(check_advisories(WHEEL_PRESETS["spiral"]))


def test_zero_angle_spiral_has_no_sliver_advisory():
    # spiral_angle 0 degenerates to radial bars — no taper, no sliver.
    p = replace(WHEEL_PRESETS["spiral"], spiral_angle=0.0)
    assert "spiral copper slivers" not in _features(check_advisories(p))


@pytest.mark.parametrize("shape", ["rectangular", "chevron"])
def test_non_spiral_wheel_never_slivers(shape):
    # The guard is spiral-only; toothed/radial wheels never raise it.
    p = WheelParams(segment_shape=shape, spiral_angle=88.0)
    assert "spiral copper slivers" not in _features(check_advisories(p))


def test_slider_never_gets_spiral_sliver_advisory():
    # _wheel_spiral_advisory must not leak into the shared self-cap path.
    assert "spiral copper slivers" not in _features(check_advisories(SliderParams()))


def test_unsupported_type_raises():
    with pytest.raises(TypeError):
        check_advisories(object())  # type: ignore[arg-type]
