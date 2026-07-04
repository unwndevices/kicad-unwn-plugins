"""Trackpad parameters: derivations, constraint validation, presets."""

from __future__ import annotations

import math

import pytest

from captouch.params import (
    TRACKPAD_PRESETS,
    SliderError,
    TrackpadError,
    TrackpadParams,
    validate_trackpad,
)


def test_half_diag_derived_from_pitch_and_gap():
    p = TrackpadParams(diamond_pitch=5.0, diamond_gap=0.5)
    assert p.half_diag == pytest.approx((5.0 - 0.5 * math.sqrt(2.0)) / 2.0)
    assert p.diamond_diag == pytest.approx(2.0 * p.half_diag)


def test_node_and_pin_counts():
    p = TrackpadParams(num_rows=4, num_cols=5)
    assert p.num_nodes == 20
    assert p.num_pins == 9
    assert (p.num_rx, p.num_tx) == (4, 5)


def test_overall_extent_is_lines_times_pitch():
    p = TrackpadParams(num_rows=4, num_cols=5, diamond_pitch=5.0)
    assert p.width == pytest.approx(25.0)
    assert p.height == pytest.approx(20.0)
    # With no explicit panel the outline equals the lattice extent.
    assert (p.lattice_width, p.lattice_height) == (p.width, p.height)


def test_from_size_derives_counts_and_pins_outline():
    # 300x200 @ 5 mm pitch is an exact multiple: 60x40 diamonds, outline == lattice.
    p = TrackpadParams.from_size(300, 200, diamond_pitch=5.0)
    assert (p.num_cols, p.num_rows) == (60, 40)
    assert (p.panel_width, p.panel_height) == (300, 200)
    assert (p.width, p.height) == (300, 200)
    assert (p.lattice_width, p.lattice_height) == (300, 200)
    validate_trackpad(p)


@pytest.mark.parametrize(
    "target,pitch,expected_cols",
    [(308, 5.0, 62), (302, 5.0, 60), (305, 5.0, 61)],  # round(dim/pitch)
)
def test_from_size_rounds_counts_to_nearest(target, pitch, expected_cols):
    p = TrackpadParams.from_size(target, 100, diamond_pitch=pitch)
    assert p.num_cols == expected_cols
    # The outline is held at exactly the requested size regardless of rounding.
    assert p.width == pytest.approx(target)


def test_from_size_floors_at_min_lines():
    # A target smaller than two pitches still yields the 2-line structural minimum.
    p = TrackpadParams.from_size(3, 3, diamond_pitch=5.0)
    assert (p.num_rows, p.num_cols) == (2, 2)


def test_from_size_passes_through_kwargs():
    p = TrackpadParams.from_size(50, 50, diamond_pitch=5.0, name="CT_Big", diamond_gap=0.4)
    assert p.name == "CT_Big"
    assert p.diamond_gap == 0.4


def test_width_height_follow_explicit_panel():
    p = TrackpadParams(num_rows=4, num_cols=5, diamond_pitch=5.0, panel_width=40, panel_height=30)
    assert (p.width, p.height) == (40, 30)  # outline = panel
    assert (p.lattice_width, p.lattice_height) == (25, 20)  # lattice = lines*pitch


@pytest.mark.parametrize("field", ["panel_width", "panel_height"])
def test_reject_nonpositive_panel(field):
    with pytest.raises(TrackpadError, match=f"{field} must be > 0"):
        validate_trackpad(TrackpadParams(**{field: 0.0}))


@pytest.mark.parametrize("key", sorted(TRACKPAD_PRESETS))
def test_presets_validate(key):
    validate_trackpad(TRACKPAD_PRESETS[key])  # must not raise


def test_iqs550_preset_is_an_inscribed_conform_circle_within_the_chip_caps():
    p = TRACKPAD_PRESETS["iqs550"]
    assert p.device == "iqs550"
    assert (p.mask_shape, p.clip_mode) == ("circle", "conform")
    # 10 Rx × 10 Tx = 100 nodes, comfortably inside the 10×15 / 150-node envelope.
    assert (p.num_rows, p.num_cols, p.num_nodes) == (10, 10, 100)
    validate_trackpad(p)  # device caps included


def test_trackpad_error_is_a_slider_error():
    # so the GUI/CLI `except SliderError` path catches it (like WheelError).
    assert issubclass(TrackpadError, SliderError)


@pytest.mark.parametrize("field,value", [("num_rows", 1), ("num_cols", 1), ("num_rows", 0)])
def test_reject_line_counts_below_floor(field, value):
    with pytest.raises(TrackpadError, match=">= 2"):
        validate_trackpad(TrackpadParams(**{field: value}))


@pytest.mark.parametrize("rows,cols", [(2, 2), (16, 16), (60, 40)])
def test_large_and_minimal_matrices_validate(rows, cols):
    # No upper cap: a minimal 2x2 and a 60x40 (2400-node, >100) pad both validate.
    p = TrackpadParams(num_rows=rows, num_cols=cols)
    assert validate_trackpad(p) is p


def test_reject_gap_too_wide_for_pitch():
    # gap·√2 >= pitch drives the half-diagonal non-positive.
    with pytest.raises(TrackpadError, match="half-diagonal"):
        validate_trackpad(TrackpadParams(diamond_pitch=2.0, diamond_gap=2.0))


def test_reject_nonpositive_gap():
    with pytest.raises(TrackpadError, match="diamond_gap"):
        validate_trackpad(TrackpadParams(diamond_gap=0.0))


def test_reject_bridge_wider_than_corridor():
    # bridge_width must be < gap·√2 so the neck fits between the diamonds.
    with pytest.raises(TrackpadError, match="bridge_width"):
        validate_trackpad(TrackpadParams(diamond_gap=0.3, bridge_width=1.0))


def test_reject_via_without_annular_ring():
    with pytest.raises(TrackpadError, match="annular"):
        validate_trackpad(TrackpadParams(via_drill=0.5, via_diameter=0.55))


def test_reject_nonpositive_via_drill():
    with pytest.raises(TrackpadError, match="via_drill"):
        validate_trackpad(TrackpadParams(via_drill=0.0))


# -- mask shape (rect / rrect / circle) ------------------------------------- #
def test_default_mask_is_rect():
    p = TrackpadParams()
    assert p.mask_shape == "rect"
    validate_trackpad(p)  # the default must still validate


def test_effective_radius_defaults_to_inscribed():
    # 4x5 @ 5 mm → 20 x 25 mm → inscribed radius = 0.5·min = 10.
    p = TrackpadParams(num_rows=4, num_cols=5, diamond_pitch=5.0)
    assert p.effective_radius == pytest.approx(10.0)


def test_effective_radius_honours_explicit():
    p = TrackpadParams(mask_shape="circle", radius=7.0)
    assert p.effective_radius == pytest.approx(7.0)


def test_reject_unknown_mask_shape():
    with pytest.raises(TrackpadError, match="mask_shape"):
        validate_trackpad(TrackpadParams(mask_shape="hexagon"))


def test_default_clip_mode_is_inscribe():
    assert TrackpadParams().clip_mode == "inscribe"


def test_reject_unknown_clip_mode():
    with pytest.raises(TrackpadError, match="clip_mode"):
        validate_trackpad(TrackpadParams(mask_shape="circle", clip_mode="squash"))


def test_conform_clip_mode_validates():
    validate_trackpad(
        TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle", clip_mode="conform")
    )


def test_reject_negative_min_feature():
    with pytest.raises(TrackpadError, match="min_feature"):
        validate_trackpad(TrackpadParams(min_feature=-0.1))


def test_rrect_requires_positive_bounded_corner_radius():
    validate_trackpad(TrackpadParams(mask_shape="rrect", corner_radius=2.0))
    with pytest.raises(TrackpadError, match="corner_radius"):
        validate_trackpad(TrackpadParams(mask_shape="rrect", corner_radius=0.0))
    # > min(width, height)/2 (3x3 @5 → 7.5) is rejected.
    with pytest.raises(TrackpadError, match="corner_radius"):
        validate_trackpad(
            TrackpadParams(num_rows=3, num_cols=3, mask_shape="rrect", corner_radius=8.0)
        )


def test_corner_radius_rejected_unless_rrect():
    with pytest.raises(TrackpadError, match="corner_radius"):
        validate_trackpad(TrackpadParams(mask_shape="rect", corner_radius=1.0))


def test_circle_radius_bounds():
    validate_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle"))
    validate_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle", radius=5.0))
    # radius > inscribed (4x4 @5 → 20 mm → max 10) clips no copper → rejected.
    with pytest.raises(TrackpadError, match="radius"):
        validate_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle", radius=12.0))


def test_radius_rejected_unless_circle():
    with pytest.raises(TrackpadError, match="radius"):
        validate_trackpad(TrackpadParams(mask_shape="rect", radius=5.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_rejected(bad):
    with pytest.raises(TrackpadError, match="finite"):
        validate_trackpad(TrackpadParams(diamond_pitch=bad))
