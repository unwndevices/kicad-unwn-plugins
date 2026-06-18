"""Fab-rule guards: profiles, feature derivation, and violation reporting."""

from __future__ import annotations

import math

import pytest

from captouch.params import (
    FAB_PROFILES,
    FabRules,
    SliderParams,
    TrackpadParams,
    WheelParams,
    check_fab,
)
from captouch.params.fab import (
    ANNULAR,
    CLEARANCE,
    DEFAULT_PROFILE,
    DRILL,
    WIDTH,
    FabViolation,
    fab_features,
)

SQRT2 = math.sqrt(2.0)


# -- profiles ---------------------------------------------------------------- #
def test_default_profile_exists_and_is_a_known_key():
    assert DEFAULT_PROFILE in FAB_PROFILES


@pytest.mark.parametrize("key", sorted(FAB_PROFILES))
def test_profiles_are_well_formed(key):
    r = FAB_PROFILES[key]
    assert r.name == key
    assert r.description
    for kind in (WIDTH, CLEARANCE, DRILL, ANNULAR):
        assert r.limit_for(kind) > 0


# -- feature derivation ------------------------------------------------------ #
def test_slider_features_report_gap_and_chevron_tip():
    feats = fab_features(SliderParams(segment_shape="chevron", air_gap=0.5, tip_radius=0.2))
    by_label = {label: (kind, val) for label, kind, val in feats}
    assert by_label["inter-electrode gap"] == (CLEARANCE, 0.5)
    assert by_label["chevron tip rounding"] == (WIDTH, pytest.approx(0.4))


def test_rectangular_slider_has_no_tip_feature():
    labels = [label for label, _, _ in fab_features(SliderParams(segment_shape="rectangular"))]
    assert "chevron tip rounding" not in labels


def test_trackpad_neck_pinch_is_tighter_than_the_bulk_gap():
    p = TrackpadParams(diamond_gap=0.5, bridge_width=0.2)
    feats = {label: val for label, _, val in fab_features(p)}
    expected_pinch = (0.5 * SQRT2 - 0.2) / 2.0
    assert feats["bridge-neck pinch clearance"] == pytest.approx(expected_pinch)
    assert feats["bridge-neck pinch clearance"] < feats["diamond facing-edge gap"]


def test_trackpad_via_annular_is_half_the_diameter_minus_drill():
    p = TrackpadParams(via_drill=0.3, via_diameter=0.6)
    feats = {label: (kind, val) for label, kind, val in fab_features(p)}
    assert feats["bridge via annular ring"] == (ANNULAR, pytest.approx(0.15))
    assert feats["bridge via drill"] == (DRILL, pytest.approx(0.3))


def test_fab_features_rejects_unknown_type():
    with pytest.raises(TypeError):
        fab_features(object())


# -- checking ---------------------------------------------------------------- #
def test_default_widgets_clear_the_default_profile():
    assert check_fab(SliderParams(), "default") == []
    assert check_fab(WheelParams(), "default") == []
    assert check_fab(TrackpadParams(), "default") == []


def test_default_trackpad_annular_trips_the_oshpark_profile():
    # The default 0.15 mm annular ring is below OSH Park's 6-mil (0.1524 mm) floor.
    violations = check_fab(TrackpadParams(), "oshpark")
    kinds = {v.kind for v in violations}
    assert ANNULAR in kinds
    assert all(isinstance(v, FabViolation) for v in violations)


def test_sharp_chevron_tip_is_flagged_as_too_thin():
    violations = check_fab(SliderParams(segment_shape="chevron", tip_radius=0.0), "default")
    assert any(v.kind == WIDTH and v.value == 0.0 for v in violations)


def test_thin_bridge_and_small_via_are_each_flagged():
    p = TrackpadParams(bridge_width=0.1, via_drill=0.2, via_diameter=0.4)
    kinds = {v.kind for v in check_fab(p, "default")}
    assert WIDTH in kinds  # 0.1 mm neck < 0.15
    assert DRILL in kinds  # 0.2 mm drill < 0.3
    assert ANNULAR in kinds  # (0.4-0.2)/2 = 0.1 < 0.15


def test_check_accepts_a_fabrules_object_directly():
    custom = FabRules("loose", min_track_width=0.05, min_clearance=0.05,
                      min_drill=0.1, min_annular_ring=0.05)
    assert check_fab(TrackpadParams(bridge_width=0.1, via_drill=0.2, via_diameter=0.4), custom) == []


def test_unknown_profile_name_raises():
    with pytest.raises(ValueError, match="unknown fab profile"):
        check_fab(SliderParams(), "no-such-fab")


def test_violation_message_mentions_value_and_limit():
    v = FabViolation("bridge via annular ring", ANNULAR, value=0.1, limit=0.15)
    assert "0.100" in v.message and "0.150" in v.message and ANNULAR in v.message
