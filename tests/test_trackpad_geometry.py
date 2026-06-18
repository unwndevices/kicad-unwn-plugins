"""Trackpad geometry: counts, layer split, bridges, vias, gap, numbering."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from captouch.geometry import build_trackpad
from captouch.geometry._base import rounded_rect_points
from captouch.params import TrackpadError, TrackpadParams

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


@pytest.mark.parametrize("rows,cols", [(2, 2), (20, 18)])
def test_builds_below_floor_and_above_old_caps(rows, cols):
    # The 3-16 row/col and 100-node caps are gone: a minimal 2x2 and a 20x18
    # (360-node, lines > 16) matrix both build a full net per line.
    geo = build_trackpad(TrackpadParams(num_rows=rows, num_cols=cols))
    assert len(geo.nets) == rows + cols
    assert all(n.fcu for n in geo.nets)  # every line carries copper


def _copper_bounds(geo):
    cu = unary_union([g for n in geo.nets for g in n.fcu] + [g for n in geo.nets for g in n.bcu])
    return cu.bounds


def test_size_driven_exact_matches_count_driven():
    # 40x30 @ 5 mm is an exact multiple, so a from_size pad and the equivalent
    # count-driven pad build the same copper (the panel just records the target).
    sized = build_trackpad(TrackpadParams.from_size(150, 200, diamond_pitch=5.0))
    counted = build_trackpad(TrackpadParams(num_cols=30, num_rows=40, diamond_pitch=5.0))
    assert len(sized.nets) == len(counted.nets)
    sa = sum(g.area for n in sized.nets for g in n.fcu)
    ca = sum(g.area for n in counted.nets for g in n.fcu)
    assert sa == pytest.approx(ca)


def test_panel_outline_drives_bounds():
    # The outline (F.Fab / courtyard) is the requested panel exactly, whether the
    # lattice overflows (gets trimmed) or underflows (empty margin) the target.
    for target in (300, 308, 302):  # exact, overflow, underflow at 5 mm pitch
        geo = build_trackpad(TrackpadParams.from_size(target, 100, diamond_pitch=5.0))
        minx, _, maxx, _ = geo.bounds
        assert maxx - minx == pytest.approx(target)


def test_panel_overflow_trims_copper_to_outline():
    # 308 wide @ 5 mm rounds to 62 cols (lattice 310 > 308): the rim is trimmed so
    # no copper extends past the panel outline.
    p = TrackpadParams.from_size(308, 100, diamond_pitch=5.0)
    assert p.lattice_width > p.width  # lattice overflows the outline
    geo = build_trackpad(p)
    minx, _, maxx, _ = _copper_bounds(geo)
    assert minx >= -p.width / 2 - 1e-6 and maxx <= p.width / 2 + 1e-6


def test_panel_underflow_terminates_at_lattice_rim_with_empty_margin():
    # 302 wide @ 5 mm rounds to 60 cols (lattice 300 < 302): the rim stays clean
    # half-diamonds at the lattice edge and the surplus is an empty margin.
    p = TrackpadParams.from_size(302, 100, diamond_pitch=5.0)
    assert p.lattice_width < p.width  # lattice underflows the outline
    geo = build_trackpad(p)
    minx, _, maxx, _ = _copper_bounds(geo)
    assert maxx - minx == pytest.approx(p.lattice_width)  # copper == lattice, not panel
    assert maxx < p.width / 2  # an empty margin remains out to the outline


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
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, diamond_gap=gap, bridge_width=bw))
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


# -- mask outline (Stage A: documentation only; copper still rect) ---------- #
def test_fab_outline_follows_mask_shape():
    assert build_trackpad(TrackpadParams()).fab_primitives[0][0] == "rect"

    rr = build_trackpad(TrackpadParams(mask_shape="rrect", corner_radius=2.0))
    kind, *_rest, r = rr.fab_primitives[0]
    assert kind == "rrect" and r == pytest.approx(2.0)

    circ = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle"))
    kind, cx, cy, r = circ.fab_primitives[0]
    assert kind == "circle" and (cx, cy) == (0.0, 0.0)
    assert r == pytest.approx(10.0)  # 4x4 @ 5 mm → 20 mm → inscribed radius 10


@pytest.mark.parametrize(
    "shape,kw",
    [
        ("rect", {}),
        ("rrect", {"corner_radius": 2.0}),
        ("circle", {}),
    ],
)
def test_courtyard_follows_mask_shape(shape, kw):
    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape=shape, **kw))
    assert geo.courtyard_outline[0] == shape
    assert geo.courtyard_outline == geo.fab_primitives[0]  # same outline as F.Fab


def test_clipped_copper_stays_inside_the_mask():
    # Every surviving piece (F.Cu + B.Cu) lies within the mask region, with a tiny
    # tolerance for the polyline-approximated disk boundary.
    p = TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle")
    geo = build_trackpad(p)
    r = p.effective_radius
    for n in geo.nets:
        for poly in [*n.fcu, *n.bcu]:
            assert poly.bounds[0] >= -r - 0.05 and poly.bounds[2] <= r + 0.05
            assert poly.bounds[1] >= -r - 0.05 and poly.bounds[3] <= r + 0.05


def test_circle_drops_outer_columns_orphan_errors_on_elongated():
    # A square matrix clips cleanly; an elongated one cannot inscribe a circle that
    # reaches its outer columns, so it hard-errors (the chosen orphan policy).
    build_trackpad(TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle"))
    with pytest.raises(TrackpadError, match="outside the circle mask"):
        build_trackpad(TrackpadParams(num_rows=3, num_cols=8, mask_shape="circle"))


def test_clipped_rx_rows_are_single_connected_pieces():
    geo = build_trackpad(TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle"))
    for n in geo.rx_nets:
        assert len(n.fcu) == 1  # keep-largest guarantees one galvanic Rx piece


def test_clipped_tx_islands_are_all_bridged():
    # Every surviving Tx column resolves to one electrically-connected net: its
    # F.Cu diamonds are joined by (diamonds-1) B.Cu straps when >1 survive.
    geo = build_trackpad(TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle"))
    for n in geo.tx_nets:
        assert len(n.bcu) == max(0, len(n.fcu) - 1)
        assert len(n.vias) == 2 * len(n.bcu)


def test_curved_mask_clips_corner_copper():
    # Stage B: a rounded-rect / circle mask actually clips the copper, removing
    # corner area the rect mask keeps.
    def total_fcu(geo):
        return sum(p.area for n in geo.nets for p in n.fcu)

    rect = build_trackpad(TrackpadParams(num_rows=4, num_cols=4))
    rr = build_trackpad(
        TrackpadParams(num_rows=4, num_cols=4, mask_shape="rrect", corner_radius=3.0)
    )
    circ = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape="circle"))
    assert total_fcu(rr) < total_fcu(rect)  # corners shaved
    assert total_fcu(circ) < total_fcu(rr)  # a disk removes more than a fillet


# -- conform clip mode (rim diamonds cut to the curve, Azoteq AZD068 §6) ---- #
def _total_fcu(geo):
    return sum(p.area for n in geo.nets for p in n.fcu)


def test_conform_fills_more_copper_than_inscribe():
    # Cutting rim diamonds to the curve keeps copper that inscribe drops whole, so
    # conform leaves strictly more F.Cu and reaches closer to the mask radius.
    kw = dict(num_rows=7, num_cols=7, diamond_pitch=5.0, mask_shape="circle")
    inscribe = build_trackpad(TrackpadParams(**kw, clip_mode="inscribe"))
    conform = build_trackpad(TrackpadParams(**kw, clip_mode="conform"))
    assert _total_fcu(conform) > _total_fcu(inscribe)
    r = conform.params.effective_radius
    reach = max(abs(v) for n in conform.nets for p in n.fcu for v in p.bounds)
    assert reach > 0.95 * r  # copper extends out to ~the mask boundary


def test_conform_rx_rows_single_piece_tx_fully_bridged():
    # Connectivity survives the cut: each Rx row stays one galvanic F.Cu piece and
    # each Tx column's surviving diamonds are joined by (diamonds-1) B.Cu straps.
    geo = build_trackpad(
        TrackpadParams(
            num_rows=7, num_cols=7, diamond_pitch=5.0, mask_shape="circle", clip_mode="conform"
        )
    )
    for n in geo.rx_nets:
        assert len(n.fcu) == 1
    for n in geo.tx_nets:
        assert len(n.bcu) == max(0, len(n.fcu) - 1)
        assert len(n.vias) == 2 * len(n.bcu)


def test_conform_vias_land_on_their_nets_copper():
    geo = build_trackpad(
        TrackpadParams(
            num_rows=7, num_cols=7, diamond_pitch=5.0, mask_shape="circle", clip_mode="conform"
        )
    )
    for n in geo.tx_nets:
        fcu = unary_union(n.fcu)
        bcu = unary_union(n.bcu)
        for v in n.vias:
            p = Point(*v.at)
            assert fcu.distance(p) < 1e-6
            assert bcu.distance(p) < 1e-6


def test_conform_copper_stays_inside_the_mask():
    p = TrackpadParams(
        num_rows=7, num_cols=7, diamond_pitch=5.0, mask_shape="circle", clip_mode="conform"
    )
    geo = build_trackpad(p)
    r = p.effective_radius
    for n in geo.nets:
        for poly in [*n.fcu, *n.bcu]:
            assert poly.bounds[0] >= -r - 0.05 and poly.bounds[2] <= r + 0.05
            assert poly.bounds[1] >= -r - 0.05 and poly.bounds[3] <= r + 0.05


def test_conform_reports_partial_channels():
    kw = dict(num_rows=7, num_cols=7, diamond_pitch=5.0, mask_shape="circle")
    conform = build_trackpad(TrackpadParams(**kw, clip_mode="conform"))
    partials = conform.partial_channels()
    # The four edge rows/cols lose ~half their area → flagged for disabling.
    assert {name for name, _ in partials} >= {"Rx1", "Rx7", "Tx1", "Tx7"}
    assert all(frac < 0.5 for _, frac in partials)
    # The central channels keep most of their copper.
    central = next(n for n in conform.rx_nets if n.pin_name == "Rx4")
    assert central.area_fraction > 0.9


def test_rect_mask_has_no_partial_channels():
    # A rect mask clips nothing, so every channel is a full (1.0) channel.
    geo = build_trackpad(TrackpadParams(num_rows=5, num_cols=5))
    assert geo.partial_channels() == []
    assert all(n.area_fraction == 1.0 for n in geo.nets)


def test_conform_area_fraction_bounds():
    geo = build_trackpad(
        TrackpadParams(
            num_rows=6, num_cols=6, diamond_pitch=5.0, mask_shape="circle", clip_mode="conform"
        )
    )
    for n in geo.nets:
        assert 0.0 < n.area_fraction <= 1.0


def test_conform_is_a_noop_for_rect_mask():
    # A rect mask clips nothing the lattice doesn't already terminate on, so conform
    # and inscribe coincide and every channel stays a full (1.0) channel.
    a = build_trackpad(TrackpadParams(num_rows=4, num_cols=5, clip_mode="inscribe"))
    b = build_trackpad(TrackpadParams(num_rows=4, num_cols=5, clip_mode="conform"))
    assert a.bounds == b.bounds
    assert _total_fcu(a) == pytest.approx(_total_fcu(b))
    assert all(n.area_fraction == 1.0 for n in b.nets)


def test_conform_elongated_circle_errors():
    with pytest.raises(TrackpadError, match="outside the circle mask"):
        build_trackpad(
            TrackpadParams(num_rows=3, num_cols=8, mask_shape="circle", clip_mode="conform")
        )


def test_rounded_rect_points_form_valid_polygon():
    pts = rounded_rect_points(-5.0, -4.0, 5.0, 4.0, 1.5)
    poly = Polygon(pts)
    assert poly.is_valid
    assert poly.bounds == pytest.approx((-5.0, -4.0, 5.0, 4.0), abs=1e-6)
    assert (-5.0, -4.0) not in pts  # the sharp corner is replaced by an arc


def test_rounded_rect_points_degenerate_radius_is_a_rectangle():
    assert rounded_rect_points(-5.0, -4.0, 5.0, 4.0, 0.0) == [
        (-5.0, -4.0),
        (5.0, -4.0),
        (5.0, 4.0),
        (-5.0, 4.0),
    ]
