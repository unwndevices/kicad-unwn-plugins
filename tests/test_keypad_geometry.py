"""Keypad geometry: grid layout, per-button electrodes, naming, bounds, fab outlines."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from captouch.geometry import KeypadGeometry, build_keypad, build_support, net_tie_number
from captouch.params import KeypadError, KeypadParams


@pytest.mark.parametrize("rows,cols", [(1, 1), (2, 3), (4, 3)])
def test_one_electrode_per_button(rows, cols):
    geo = build_keypad(KeypadParams(num_rows=rows, num_cols=cols))
    assert isinstance(geo, KeypadGeometry)
    assert len(geo.electrodes) == rows * cols
    assert geo.active == geo.electrodes and geo.dummies == []  # every button is active


def test_pad_numbers_and_pin_names_are_sequential():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=3))
    assert [e.pad_number for e in geo.electrodes] == [str(i + 1) for i in range(6)]
    assert [e.pin_name for e in geo.electrodes] == [f"K{i + 1}" for i in range(6)]


def test_grid_is_centred_on_origin():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=4, button_size=10.0, gap=4.0))
    minx, miny, maxx, maxy = geo.bounds
    assert minx == pytest.approx(-maxx) and miny == pytest.approx(-maxy)


@pytest.mark.parametrize("shape", ["rect", "circle", "diamond"])
def test_bounds_track_grid_extent(shape):
    p = KeypadParams(num_rows=2, num_cols=3, button_shape=shape, button_size=10.0, gap=4.0)
    geo = build_keypad(p)
    minx, miny, maxx, maxy = geo.bounds
    assert maxx - minx == pytest.approx(p.width)
    assert maxy - miny == pytest.approx(p.height)


def test_adjacent_buttons_sit_one_pitch_apart():
    p = KeypadParams(num_rows=1, num_cols=3, button_size=10.0, gap=4.0)
    geo = build_keypad(p)
    xs = [cx for cx, _ in geo.centers]
    assert xs[1] - xs[0] == pytest.approx(p.pitch)
    assert xs[2] - xs[1] == pytest.approx(p.pitch)


@pytest.mark.parametrize(
    "shape,kind", [("rect", "rect"), ("circle", "circle"), ("diamond", "poly")]
)
def test_fab_primitive_kind_per_shape(shape, kind):
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=2, button_shape=shape))
    prims = geo.fab_primitives
    assert len(prims) == geo.params.num_buttons  # one nominal outline per button
    assert all(pr[0] == kind for pr in prims)


def test_courtyard_outline_is_a_rect():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=2))
    assert geo.courtyard_outline[0] == "rect"


@pytest.mark.parametrize("shape", ["rect", "diamond"])
def test_buttons_are_single_valid_polygons(shape):
    # Even with corner rounding, each button stays one valid (non-empty) polygon.
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=2, button_shape=shape, corner_radius=1.0))
    for e in geo.electrodes:
        assert isinstance(e.polygon, Polygon)
        assert e.polygon.is_valid and e.polygon.area > 0


def test_buttons_do_not_overlap():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=3, button_size=10.0, gap=4.0))
    polys = [e.polygon for e in geo.electrodes]
    for i, a in enumerate(polys):
        for b in polys[i + 1 :]:
            assert not a.intersects(b) or a.intersection(b).area == pytest.approx(0.0)


def test_symbol_columns_split_buttons_into_halves():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=3))  # 6 buttons
    left, right = geo.symbol_columns()
    assert len(left) == 3 and len(right) == 3
    assert {n for n, _ in left} | {n for n, _ in right} == {str(i + 1) for i in range(6)}


def test_invalid_params_raise_before_build():
    with pytest.raises(KeypadError):
        build_keypad(KeypadParams(num_rows=0))


# -- support copper reuses the shared zone builder --------------------------- #
def test_support_copper_builds_and_numbers_the_net_tie():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=2, ground_hatch=True, guard_ring=True))
    sc = build_support(geo)
    assert sc is not None and sc.ground is not None and sc.guard is not None
    # The GND net-tie is numbered one past the last button (4 buttons -> "5").
    assert net_tie_number(geo) == "5"


def test_no_support_copper_by_default():
    geo = build_keypad(KeypadParams(num_rows=2, num_cols=2))
    assert build_support(geo) is None
    assert net_tie_number(geo) is None
