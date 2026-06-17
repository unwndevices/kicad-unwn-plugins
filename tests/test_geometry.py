"""Slider geometry: segment counts, uniform gap, validity, numbering."""

from __future__ import annotations

import pytest
from shapely.geometry import Point

from captouch.geometry import build_slider
from captouch.params import SliderParams

SHAPES = ["rectangular", "chevron", "interdigitated"]


def _min_gap(geo):
    el = geo.electrodes
    return min(el[i].polygon.distance(el[i + 1].polygon) for i in range(len(el) - 1))


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("dummies", [0, 1, 2])
def test_segment_count(shape, dummies):
    p = SliderParams(segment_shape=shape, num_segments=4, end_dummies=dummies)
    geo = build_slider(p)
    assert len(geo.electrodes) == 4 + 2 * dummies
    assert len(geo.active) == 4
    assert len(geo.dummies) == 2 * dummies


@pytest.mark.parametrize("shape", SHAPES)
def test_segments_are_valid_single_polygons(shape):
    geo = build_slider(SliderParams(segment_shape=shape))
    for e in geo.electrodes:
        assert e.polygon.is_valid
        assert e.polygon.geom_type == "Polygon"
        assert e.polygon.area > 0


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("gap", [0.3, 0.5, 1.0])
def test_uniform_air_gap(shape, gap):
    # Width is derived so the finger constraint holds for each gap.
    geo = build_slider(SliderParams(segment_shape=shape, air_gap=gap))
    assert _min_gap(geo) == pytest.approx(gap, abs=1e-3)


@pytest.mark.parametrize("shape", SHAPES)
def test_anchor_is_inside_its_electrode(shape):
    geo = build_slider(SliderParams(segment_shape=shape, corner_radius=0.3))
    for e in geo.electrodes:
        assert e.polygon.contains(Point(*e.anchor))


def test_left_to_right_ordering_and_numbering():
    geo = build_slider(SliderParams(num_segments=4, end_dummies=1))
    xs = [e.polygon.centroid.x for e in geo.electrodes]
    assert xs == sorted(xs)  # ordered left to right
    # active pads numbered 1..N with names E1..EN; dummies named GND, distinct numbers
    assert [e.pin_name for e in geo.active] == ["E1", "E2", "E3", "E4"]
    assert [e.pad_number for e in geo.active] == ["1", "2", "3", "4"]
    assert all(e.pin_name == "GND" for e in geo.dummies)
    nums = [e.pad_number for e in geo.electrodes]
    assert len(set(nums)) == len(nums)  # all pad numbers unique


def test_geometry_is_centred_on_origin():
    geo = build_slider(SliderParams())
    minx, miny, maxx, maxy = geo.bounds
    assert minx == pytest.approx(-maxx)
    assert miny == pytest.approx(-maxy)


@pytest.mark.parametrize("shape", ["chevron", "interdigitated"])
def test_interdigitation_interleaves_neighbours(shape):
    # Adjacent electrodes' x-extents must overlap (teeth reach into each other).
    geo = build_slider(SliderParams(segment_shape=shape))
    el = geo.electrodes
    for i in range(len(el) - 1):
        a, b = el[i].polygon.bounds, el[i + 1].polygon.bounds
        assert a[2] > b[0]  # left electrode's max-x exceeds right electrode's min-x


def test_tip_radius_rounds_chevron_only():
    # Chevron tips change when rounded; rectangular has no acute tips so its
    # tip_radius is a no-op (only corner_radius would touch it).
    sharp = build_slider(SliderParams(segment_shape="chevron", tip_radius=0.0))
    rounded = build_slider(SliderParams(segment_shape="chevron", tip_radius=0.3))
    assert [e.points for e in sharp.electrodes] != [e.points for e in rounded.electrodes]

    a = build_slider(SliderParams(segment_shape="rectangular", segment_width=7.0, tip_radius=0.0))
    b = build_slider(SliderParams(segment_shape="rectangular", segment_width=7.0, tip_radius=0.3))
    assert [e.points for e in a.electrodes] == [e.points for e in b.electrodes]


def test_excessive_tip_radius_degrades_gracefully():
    # round_corners must never raise: a far-too-large radius leaves valid copper.
    geo = build_slider(SliderParams(segment_shape="chevron", tip_radius=5.0))
    for e in geo.electrodes:
        assert e.polygon.is_valid and e.polygon.area > 0


def test_rectangular_segments_have_expected_width():
    geo = build_slider(SliderParams(segment_shape="rectangular", num_segments=3, end_dummies=0))
    for e in geo.electrodes:
        minx, miny, maxx, maxy = e.polygon.bounds
        assert (maxx - minx) == pytest.approx(geo.params.width, abs=1e-3)
        assert (maxy - miny) == pytest.approx(geo.params.segment_height, abs=1e-3)
