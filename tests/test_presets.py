"""Vendor-preset verification — presets reproduce documented reference dimensions.

Phase 5 "done when": *presets reproduce vendor reference dimensions*. Each preset
cites a vendor table in its definition; these tests pin the resolved dimensions to
the numbers in those sources (see ``docs/capacitive-touch-design-guidelines.md``
sections 2–4 / 6) so a future edit can't silently drift a preset away from the
geometry it claims to reproduce.
"""

from __future__ import annotations

import pytest

from captouch.params import (
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    check_fab,
    validate_slider,
    validate_trackpad,
    validate_wheel,
)
from captouch.params.slider import FINGER_CONSTRAINT_TOL

# -- expected vendor reference dimensions ------------------------------------ #
# Slider: resolved width W, gap A, finger Ø, shape, active count, dummies/end.
# (Infineon AN85951; Microchip AN2934 Table 1-3; Azoteq AZD125 Table 6.2.)
SLIDER_EXPECT = {
    "infineon": dict(num_segments=5, shape="chevron", W=8.0, A=0.5, finger=9.0, dummies=1),
    "microchip": dict(num_segments=4, shape="interdigitated", W=6.0, A=1.0, finger=8.0, dummies=1),
    "azoteq": dict(num_segments=4, shape="interdigitated", W=7.0, A=0.5, finger=8.0, dummies=1),
}

# Wheel: resolved arc width W, gap A, finger Ø, shape, segments, ring width.
# (ST AN2869 Fig 15; Microchip AN2934 Table 1-5; Infineon AN64846.)
WHEEL_EXPECT = {
    "st_rotary": dict(num_segments=5, shape="chevron", W=8.0, A=0.5, finger=9.0, ring=5.0),
    "microchip": dict(num_segments=4, shape="interdigitated", W=6.0, A=1.0, finger=8.0, ring=4.0),
    "infineon": dict(num_segments=8, shape="chevron", W=7.0, A=0.5, finger=8.0, ring=5.0),
    "spiral": dict(num_segments=8, shape="spiral", W=7.0, A=0.5, finger=8.0, ring=6.0),
}

# Trackpad: matrix size, pitch, gap. (Infineon AN234185 §4.3; Microchip AN2934
# Table 1-6; a compact 3×3 smoke pad.)
TRACKPAD_EXPECT = {
    "infineon": dict(rows=5, cols=5, pitch=5.0, gap=0.5),
    "microchip": dict(rows=4, cols=6, pitch=6.0, gap=0.5),
    "compact": dict(rows=3, cols=3, pitch=5.0, gap=0.5),
    "iqs550": dict(rows=10, cols=10, pitch=6.0, gap=0.5),
}


# -- coverage: every preset is pinned ---------------------------------------- #
def test_every_preset_has_an_expectation():
    assert set(SLIDER_PRESETS) == set(SLIDER_EXPECT)
    assert set(WHEEL_PRESETS) == set(WHEEL_EXPECT)
    assert set(TRACKPAD_PRESETS) == set(TRACKPAD_EXPECT)


# -- slider ------------------------------------------------------------------ #
@pytest.mark.parametrize("key", sorted(SLIDER_EXPECT))
def test_slider_preset_matches_vendor_reference(key):
    p, exp = SLIDER_PRESETS[key], SLIDER_EXPECT[key]
    validate_slider(p)  # the preset itself is valid
    assert p.num_segments == exp["num_segments"]
    assert p.segment_shape == exp["shape"]
    assert p.width == pytest.approx(exp["W"])
    assert p.air_gap == pytest.approx(exp["A"])
    assert p.finger_diameter == pytest.approx(exp["finger"])
    assert p.end_dummies == exp["dummies"]
    # Reproduces the vendor finger geometry: W + 2A = finger (Infineon Eq. 73).
    assert abs(p.width + 2 * p.air_gap - p.finger_diameter) <= FINGER_CONSTRAINT_TOL
    # Active count stays in the vendor 3–8 range (guidelines §2.1 / §6.2).
    assert 3 <= p.num_segments <= 8


# -- wheel ------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(WHEEL_EXPECT))
def test_wheel_preset_matches_vendor_reference(key):
    p, exp = WHEEL_PRESETS[key], WHEEL_EXPECT[key]
    validate_wheel(p)
    assert p.num_segments == exp["num_segments"]
    assert p.segment_shape == exp["shape"]
    assert p.width == pytest.approx(exp["W"])
    assert p.air_gap == pytest.approx(exp["A"])
    assert p.finger_diameter == pytest.approx(exp["finger"])
    assert p.ring_width == pytest.approx(exp["ring"])
    assert abs(p.width + 2 * p.air_gap - p.finger_diameter) <= FINGER_CONSTRAINT_TOL
    # Arc width should stay in ST's recommended 6–8 mm band (AN2869 §5.3).
    assert 6.0 <= p.width <= 8.0


# -- trackpad ---------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(TRACKPAD_EXPECT))
def test_trackpad_preset_matches_vendor_reference(key):
    p, exp = TRACKPAD_PRESETS[key], TRACKPAD_EXPECT[key]
    validate_trackpad(p)
    assert (p.num_rows, p.num_cols) == (exp["rows"], exp["cols"])
    assert p.diamond_pitch == pytest.approx(exp["pitch"])
    assert p.diamond_gap == pytest.approx(exp["gap"])
    # Matrix and pitch stay inside the vendor envelopes (guidelines §4 / §6.4).
    assert 3 <= p.num_rows <= 16 and 3 <= p.num_cols <= 16
    assert p.num_nodes <= 100
    assert 3.8 <= p.diamond_pitch <= 10.0


# -- manufacturability: presets are buildable on a conservative fab ---------- #
@pytest.mark.parametrize("presets", [SLIDER_PRESETS, WHEEL_PRESETS, TRACKPAD_PRESETS])
def test_presets_clear_the_default_fab_profile(presets):
    # Every shipped preset should be manufacturable on the conservative default
    # profile without warnings — a regression guard on the preset dimensions.
    for p in presets.values():
        assert check_fab(p, "default") == [], f"{p.name} trips the default fab profile"
