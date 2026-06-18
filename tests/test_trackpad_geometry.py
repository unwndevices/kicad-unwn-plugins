"""Trackpad geometry: counts, layer split, bridges, vias, gap, numbering."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Point
from shapely.ops import unary_union

from captouch.geometry import build_trackpad
from captouch.params import TrackpadParams

SIZES = [(3, 3), (3, 5), (4, 5), (5, 5)]


def _net_fcu_distance(geo):
    """Smallest distance between F.Cu copper of two different nets."""
    nets = geo.nets
    best = math.inf
    for i in range(len(nets)):
        ui = unary_union(nets[i].fcu)
        for j in range(i + 1, len(nets)):
            best = min(best, ui.distance(unary_union(nets[j].fcu)))
    return best


@pytest.mark.parametrize("rows,cols", SIZES)
def test_net_counts(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    assert len(geo.nets) == rows + cols
    assert len(geo.rx_nets) == rows  # Rx = rows
    assert len(geo.tx_nets) == cols  # Tx = cols
    assert geo.params.num_nodes == rows * cols


@pytest.mark.parametrize("rows,cols", SIZES)
def test_numbering_and_pin_names(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    assert [n.pad_number for n in geo.nets] == [str(i + 1) for i in range(rows + cols)]
    assert [n.pin_name for n in geo.rx_nets] == [f"Rx{i + 1}" for i in range(rows)]
    assert [n.pin_name for n in geo.tx_nets] == [f"Tx{i + 1}" for i in range(cols)]


@pytest.mark.parametrize("rows,cols", SIZES)
def test_rx_continuous_tx_bridged(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    for n in geo.rx_nets:
        assert len(n.fcu) == 1  # one connected row of F.Cu copper
        assert n.bcu == [] and n.vias == []  # continuous → no bridge
    for n in geo.tx_nets:
        assert len(n.fcu) == rows + 1  # diamonds, two halved at the edges
        assert len(n.bcu) == rows  # one B.Cu strap per consecutive pair
        assert len(n.vias) == 2 * rows  # two vias per strap


@pytest.mark.parametrize("rows,cols", SIZES)
def test_all_pieces_valid_and_above_sliver(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    for n in geo.nets:
        for poly in [*n.fcu, *n.bcu]:
            assert poly.is_valid and poly.geom_type == "Polygon"
            assert poly.area >= 1e-3


@pytest.mark.parametrize("gap", [0.4, 0.5, 0.6])
def test_pinch_clearance_matches_design(gap):
    # The minimum copper-copper gap in a diamond pattern is the neck *pinch*
    # (Rx neck vs Tx diamond), (gap·√2 − bridge_width)/2 — tighter than the bulk
    # diamond gap. This is the clearance the DRC gate ultimately checks.
    bw = 0.2
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4,
                                        diamond_gap=gap, bridge_width=bw))
    expected = (gap * math.sqrt(2.0) - bw) / 2.0
    assert _net_fcu_distance(geo) == pytest.approx(expected, abs=2e-2)


@pytest.mark.parametrize("rows,cols", SIZES)
def test_vias_land_in_their_nets_copper(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    for n in geo.tx_nets:
        fcu = unary_union(n.fcu)
        bcu = unary_union(n.bcu)
        for v in n.vias:
            p = Point(*v.at)
            assert fcu.distance(p) < 1e-6  # inside an F.Cu diamond
            assert bcu.distance(p) < 1e-6  # inside the B.Cu strap


@pytest.mark.parametrize("rows,cols", SIZES)
def test_anchor_inside_largest_fcu_piece(rows, cols):
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    for n in geo.nets:
        biggest = max(n.fcu, key=lambda g: g.area)
        assert biggest.contains(Point(*n.anchor))


def test_geometry_centred_on_origin():
    p = TrackpadParams(num_rows=4, num_cols=5, diamond_pitch=5.0)
    geo = build_trackpad(p)
    minx, miny, maxx, maxy = geo.bounds
    assert (minx, maxx) == pytest.approx((-p.width / 2, p.width / 2), abs=0.05)
    assert (miny, maxy) == pytest.approx((-p.height / 2, p.height / 2), abs=0.05)


def test_symbol_columns_split_rx_left_tx_right():
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=5))
    left, right = geo.symbol_columns()
    assert [name for _, name in left] == [f"Rx{i + 1}" for i in range(4)]
    assert [name for _, name in right] == [f"Tx{i + 1}" for i in range(5)]
