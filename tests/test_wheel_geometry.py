"""Wheel geometry: counts, continuity, uniform gap, centre hole, numbering."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Point

from captouch.geometry import build_wheel
from captouch.params import WheelParams

SHAPES = ["rectangular", "chevron", "interdigitated", "spiral"]


def _params(shape, **kw):
    base = dict(
        num_segments=5, segment_shape=shape, ring_width=5.0, air_gap=0.5, finger_diameter=8.0
    )
    if shape == "rectangular":
        base.update(segment_width=7.0)  # W+2A == finger
    base.update(kw)
    return WheelParams(**base)


def _min_cyclic_gap(geo):
    el = geo.electrodes
    n = len(el)
    return min(el[i].polygon.distance(el[(i + 1) % n].polygon) for i in range(n))


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("m", [3, 5, 8])
def test_segment_count(shape, m):
    geo = build_wheel(_params(shape, num_segments=m))
    assert len(geo.electrodes) == m


@pytest.mark.parametrize("shape", SHAPES)
def test_wheel_is_continuous_all_active(shape):
    geo = build_wheel(_params(shape))
    assert len(geo.active) == len(geo.electrodes)
    assert geo.dummies == []


@pytest.mark.parametrize("shape", SHAPES)
def test_segments_are_valid_single_polygons(shape):
    geo = build_wheel(_params(shape))
    for e in geo.electrodes:
        assert e.polygon.is_valid
        assert e.polygon.geom_type == "Polygon"
        assert e.polygon.area > 0


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("gap", [0.3, 0.5, 1.0])
def test_uniform_air_gap(shape, gap):
    geo = build_wheel(_params(shape, air_gap=gap, finger_diameter=7.0 + 2 * gap))
    assert _min_cyclic_gap(geo) == pytest.approx(gap, abs=2e-2)


@pytest.mark.parametrize("shape", SHAPES)
def test_anchor_is_inside_its_electrode(shape):
    geo = build_wheel(_params(shape))
    for e in geo.electrodes:
        assert e.polygon.contains(Point(*e.anchor))


@pytest.mark.parametrize("shape", SHAPES)
def test_centre_hole_is_kept_clear(shape):
    geo = build_wheel(_params(shape))
    # No copper intrudes into the centre keep-out: every vertex is at radius
    # >= inner_radius (small tolerance for tessellation / rounding).
    ri = geo.inner_radius
    for e in geo.electrodes:
        for x, y in e.points:
            assert math.hypot(x, y) >= ri - 0.05


@pytest.mark.parametrize("shape", SHAPES)
def test_numbering_walks_around_the_ring(shape):
    m = 6
    geo = build_wheel(_params(shape, num_segments=m))
    nums = [e.pad_number for e in geo.electrodes]
    assert nums == [str(i + 1) for i in range(m)]
    assert [e.pin_name for e in geo.electrodes] == [f"E{i + 1}" for i in range(m)]
    # Each consecutive pad sits one segment-step further around the ring (the
    # step wraps cleanly past the +x axis between the last pad and the first).
    step = 2 * math.pi / m
    angs = [
        math.atan2(e.polygon.centroid.y, e.polygon.centroid.x) % (2 * math.pi)
        for e in geo.electrodes
    ]
    diffs = [(angs[(i + 1) % m] - angs[i]) % (2 * math.pi) for i in range(m)]
    assert all(abs(d - step) < 0.15 for d in diffs), diffs


def test_tip_radius_rounds_chevron_only():
    sharp = build_wheel(_params("chevron", tip_radius=0.0))
    rounded = build_wheel(_params("chevron", tip_radius=0.3))
    assert [e.points for e in sharp.electrodes] != [e.points for e in rounded.electrodes]

    # interdigitated has square (non-acute) tips → tip_radius is a no-op.
    a = build_wheel(_params("interdigitated", tip_radius=0.0))
    b = build_wheel(_params("interdigitated", tip_radius=0.3))
    assert [e.points for e in a.electrodes] == [e.points for e in b.electrodes]


def test_geometry_is_centred_on_origin():
    geo = build_wheel(_params("chevron"))
    minx, miny, maxx, maxy = geo.bounds
    assert minx == pytest.approx(-maxx, abs=0.05)
    assert miny == pytest.approx(-maxy, abs=0.05)
    assert maxx == pytest.approx(geo.outer_radius, abs=0.05)


# --------------------------------------------------------------------------- #
# spiral: the twist is real and monotone
# --------------------------------------------------------------------------- #
def test_spiral_differs_from_untwisted():
    # A swirled spiral must not coincide with its zero-twist degenerate (which is
    # just straight radial bars) — proving spiral_angle actually bends the copper.
    flat = build_wheel(_params("spiral", spiral_angle=0.0))
    swirl = build_wheel(_params("spiral", spiral_angle=45.0))
    assert [e.points for e in flat.electrodes] != [e.points for e in swirl.electrodes]


def test_spiral_zero_twist_matches_rectangular():
    # spiral_angle == 0 degenerates to straight radial bars: same per-electrode
    # area as the equivalent rectangular wheel (both toothless radial wedges).
    flat = build_wheel(_params("spiral", spiral_angle=0.0))
    rect = build_wheel(_params("rectangular"))
    assert flat.electrodes[0].polygon.area == pytest.approx(rect.electrodes[0].polygon.area, abs=1e-6)


def test_larger_spiral_angle_twists_more():
    # A bigger twist produces different geometry than a smaller one (not just a
    # rigid rotation of the same shape).
    small = build_wheel(_params("spiral", spiral_angle=20.0))
    large = build_wheel(_params("spiral", spiral_angle=70.0))
    assert [e.points for e in small.electrodes] != [e.points for e in large.electrodes]
    # A harder twist lengthens each boundary, so its (uniform-width) gap strip
    # removes more copper — every electrode ends up smaller.
    assert large.electrodes[0].polygon.area < small.electrodes[0].polygon.area


def test_spiral_ignores_teeth_fields():
    # Spiral is toothless: num_fingers / tooth_depth have no effect on the copper.
    a = build_wheel(_params("spiral", num_fingers=3, tooth_depth=None))
    b = build_wheel(_params("spiral", num_fingers=9, tooth_depth=2.0))
    assert [e.points for e in a.electrodes] == [e.points for e in b.electrodes]
