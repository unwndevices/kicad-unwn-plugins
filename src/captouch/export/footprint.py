"""Emit a KiCad footprint (`.kicad_mod`) for a touch widget.

Each electrode is a single **custom-shaped SMD copper pad** on ``F.Cu`` (so it
carries a net and DRC sees it), whose outline is a closed polygon. The pad is
anchored at an interior point of its own copper and its primitive polygon is
emitted relative to that anchor, so the mandatory anchor pad adds no copper
outside the electrode and never shorts neighbouring pads at the origin.

A slider footprint is the electrodes plus a courtyard (``F.CrtYd``) and a
documentation outline (``F.Fab``). Output targets the KiCad 9.0 footprint format
(``version 20241229``), which both KiCad 9 and 10 accept.
"""

from __future__ import annotations

from typing import Sequence

from typing import Union

from .. import __version__, sexpr
from ..geometry import SliderGeometry, TrackpadGeometry, WheelGeometry
from ..geometry._base import (
    ANCHOR_RADIUS,
    anchor_point,
    polygon_points,
    rounded_rect_points,
)
from ..sexpr import Sym

#: Any widget geometry the exporter can serialise (duck-typed: ``electrodes``,
#: ``bounds``, ``params.name``, ``fab_primitives``, ``courtyard_outline``).
WidgetGeometry = Union[SliderGeometry, WheelGeometry, TrackpadGeometry]

# KiCad 9.0 footprint/board S-expression format version (date token). KiCad 10
# reads and upgrades it; emitting a newer token would make KiCad 9 reject it.
FOOTPRINT_VERSION = 20241229
GENERATOR = "kicad-captouch"

COURTYARD_MARGIN = 0.25  # mm around the copper bounding box
COURTYARD_WIDTH = 0.05
FAB_WIDTH = 0.1
SILK_WIDTH = 0.12

Point = tuple[float, float]


def _effects(size: float = 1.0, thickness: float = 0.15) -> list:
    return [
        Sym("effects"),
        [Sym("font"), [Sym("size"), size, size], [Sym("thickness"), thickness]],
    ]


def _property(name: str, value: str, at: tuple[float, float, float], layer: str) -> list:
    x, y, rot = at
    return [
        Sym("property"),
        name,
        value,
        [Sym("at"), x, y, rot],
        [Sym("layer"), layer],
        _effects(),
    ]


def _pts(points: Sequence[Point]) -> list:
    return [Sym("pts"), *[[Sym("xy"), x, y] for (x, y) in points]]


def _fp_rect(p1: Point, p2: Point, *, layer: str, width: float) -> list:
    return [
        Sym("fp_rect"),
        [Sym("start"), p1[0], p1[1]],
        [Sym("end"), p2[0], p2[1]],
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_circle(center: Point, radius: float, *, layer: str, width: float) -> list:
    cx, cy = center
    return [
        Sym("fp_circle"),
        [Sym("center"), cx, cy],
        [Sym("end"), round(cx + radius, 6), cy],  # a point on the circle
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_poly(points: Sequence[Point], *, layer: str, width: float) -> list:
    return [
        Sym("fp_poly"),
        _pts(points),
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_rrect(p1: Point, p2: Point, r: float, *, layer: str, width: float) -> list:
    """A rounded rectangle. KiCad has no filleted-rect primitive, so it is emitted
    as a polyline ``fp_poly`` whose corner arcs come from :func:`rounded_rect_points`."""
    pts = rounded_rect_points(p1[0], p1[1], p2[0], p2[1], r)
    return _fp_poly(pts, layer=layer, width=width)


def _expand_outline(prim: tuple, margin: float) -> tuple:
    """Grow a documentation primitive outward by *margin* (for the courtyard)."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        return ("rect", x1 - margin, y1 - margin, x2 + margin, y2 + margin)
    if kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        return ("rrect", x1 - margin, y1 - margin, x2 + margin, y2 + margin, r + margin)
    if kind == "circle":
        _, cx, cy, r = prim
        return ("circle", cx, cy, r + margin)
    raise ValueError(f"unknown outline primitive: {prim!r}")


def _emit_outline(prim: tuple, *, layer: str, width: float) -> list:
    """Render a ``("rect"|"rrect"|"circle", …)`` primitive on *layer*."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        return _fp_rect((x1, y1), (x2, y2), layer=layer, width=width)
    if kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        return _fp_rrect((x1, y1), (x2, y2), r, layer=layer, width=width)
    if kind == "circle":
        _, cx, cy, r = prim
        return _fp_circle((cx, cy), r, layer=layer, width=width)
    raise ValueError(f"unknown outline primitive: {prim!r}")


def custom_polygon_pad(
    points: Sequence[Point],
    *,
    number: str = "1",
    at: Point = (0.0, 0.0),
    layer: str = "F.Cu",
    anchor: float = 2 * ANCHOR_RADIUS,
) -> list:
    """Build a custom-shape SMD pad from a closed polygon outline.

    *points* are absolute (geometry-space) coordinates; they are emitted relative
    to *at*, which becomes the pad position. *at* must lie inside the polygon.
    """
    if len(points) < 3:
        raise ValueError("a polygon pad needs at least 3 points")
    ax, ay = at
    rel = [(round(x - ax, 6), round(y - ay, 6)) for (x, y) in points]
    return [
        Sym("pad"),
        number,
        Sym("smd"),
        Sym("custom"),
        [Sym("at"), ax, ay],
        [Sym("size"), anchor, anchor],
        [Sym("layers"), layer],
        [Sym("options"), [Sym("clearance"), Sym("outline")], [Sym("anchor"), Sym("circle")]],
        [
            Sym("primitives"),
            [Sym("gr_poly"), _pts(rel), [Sym("width"), 0], [Sym("fill"), Sym("yes")]],
        ],
    ]


def via_pad(
    at: Point,
    *,
    number: str = "1",
    drill: float = 0.3,
    diameter: float = 0.6,
    layers: Sequence[str] = ("*.Cu", "*.Mask"),
) -> list:
    """Build a plated thru-hole via pad that ties F.Cu to B.Cu for one net.

    Used by the trackpad to bridge a Tx column over an Rx neck: a B.Cu strap
    between two such vias carries the link on the back layer. Sharing *number*
    with the net's copper pads makes KiCad treat it as the same net, so the via
    completes the cross-layer connection (verified: DRC reports the net connected
    only when the via is present).
    """
    ax, ay = at
    return [
        Sym("pad"),
        number,
        Sym("thru_hole"),
        Sym("circle"),
        [Sym("at"), ax, ay],
        [Sym("size"), diameter, diameter],
        [Sym("drill"), drill],
        [Sym("layers"), *layers],
        [Sym("remove_unused_layers"), Sym("no")],
    ]


def _header(name: str, value: str, ref_at: float, val_at: float) -> list:
    return [
        [Sym("version"), FOOTPRINT_VERSION],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), __version__],
        [Sym("layer"), "F.Cu"],
        _property("Reference", "REF**", (0, ref_at, 0), "F.SilkS"),
        _property("Value", value, (0, val_at, 0), "F.Fab"),
        [Sym("attr"), Sym("smd")],
    ]


# --------------------------------------------------------------------------- #
# Phase 0 spike: a single electrode from one polygon (kept for the format gate)
# --------------------------------------------------------------------------- #
def electrode_footprint(name: str, polygon: Sequence[Point], *, value: str | None = None) -> list:
    """Build a footprint node containing a single custom-polygon electrode pad."""
    return [
        Sym("footprint"),
        name,
        *_header(name, value or name, -1, 1),
        custom_polygon_pad(polygon, number="1"),
        [Sym("embedded_fonts"), Sym("no")],
    ]


def footprint_text(name: str, polygon: Sequence[Point], *, value: str | None = None) -> str:
    """Serialise an electrode footprint to `.kicad_mod` text (trailing newline)."""
    return sexpr.dumps(electrode_footprint(name, polygon, value=value)) + "\n"


# --------------------------------------------------------------------------- #
# Widget footprint: one custom pad per electrode + courtyard + fab outline
# --------------------------------------------------------------------------- #
def widget_footprint(geo: WidgetGeometry) -> list:
    """Build a footprint node for any widget (slider, wheel, …) from its geometry.

    The documentation outline (``F.Fab``) and courtyard (``F.CrtYd``) come from
    the geometry's own ``fab_primitives`` / ``courtyard_outline`` (rectangles for
    a slider, circles for a wheel), so each widget draws the right shape while the
    pad/courtyard machinery stays shared.
    """
    name = geo.params.name
    minx, miny, maxx, maxy = geo.bounds
    ref_y = miny - 1.5
    val_y = maxy + 1.5

    fab = [_emit_outline(p, layer="F.Fab", width=FAB_WIDTH) for p in geo.fab_primitives]
    courtyard = _emit_outline(
        _expand_outline(geo.courtyard_outline, COURTYARD_MARGIN),
        layer="F.CrtYd",
        width=COURTYARD_WIDTH,
    )
    pads = [
        custom_polygon_pad(e.points, number=e.pad_number, at=e.anchor)
        for e in geo.electrodes
    ]

    return [
        Sym("footprint"),
        name,
        *_header(name, name, ref_y, val_y),
        *fab,
        courtyard,
        *pads,
        [Sym("embedded_fonts"), Sym("no")],
    ]


def widget_footprint_text(geo: WidgetGeometry) -> str:
    """Serialise any widget footprint to `.kicad_mod` text (trailing newline)."""
    return sexpr.dumps(widget_footprint(geo)) + "\n"


# Backwards-compatible / explicit per-widget aliases.
def slider_footprint(geo: SliderGeometry) -> list:
    """Build a slider footprint node (see :func:`widget_footprint`)."""
    return widget_footprint(geo)


def slider_footprint_text(geo: SliderGeometry) -> str:
    """Serialise a slider footprint to `.kicad_mod` text (trailing newline)."""
    return widget_footprint_text(geo)


def wheel_footprint(geo: WheelGeometry) -> list:
    """Build a wheel footprint node (see :func:`widget_footprint`)."""
    return widget_footprint(geo)


def wheel_footprint_text(geo: WheelGeometry) -> str:
    """Serialise a wheel footprint to `.kicad_mod` text (trailing newline)."""
    return widget_footprint_text(geo)


# --------------------------------------------------------------------------- #
# Trackpad footprint: a two-layer diamond matrix with via bridges
# --------------------------------------------------------------------------- #
# A trackpad net (Rx row / Tx column) spans many polygons across two layers, so
# it cannot use the one-pad-per-electrode `widget_footprint`. Each net emits one
# custom pad per F.Cu piece, one per B.Cu strap, and one thru-hole via pad per
# bridge — all sharing the net's pad number, so KiCad reads them as one net and
# the vias complete the cross-layer connection.
def trackpad_footprint(geo: TrackpadGeometry) -> list:
    """Build a footprint node for a trackpad from its :class:`TrackpadGeometry`."""
    name = geo.params.name
    minx, miny, maxx, maxy = geo.bounds
    ref_y = miny - 1.5
    val_y = maxy + 1.5
    p = geo.params

    fab = [_emit_outline(pr, layer="F.Fab", width=FAB_WIDTH) for pr in geo.fab_primitives]
    courtyard = _emit_outline(
        _expand_outline(geo.courtyard_outline, COURTYARD_MARGIN),
        layer="F.CrtYd",
        width=COURTYARD_WIDTH,
    )

    pads: list = []
    for net in geo.nets:
        for poly in net.fcu:
            pts = polygon_points(poly)
            pads.append(custom_polygon_pad(pts, number=net.pad_number,
                                           at=anchor_point(poly), layer="F.Cu"))
        for poly in net.bcu:
            pts = polygon_points(poly)
            pads.append(custom_polygon_pad(pts, number=net.pad_number,
                                           at=anchor_point(poly), layer="B.Cu"))
        for via in net.vias:
            pads.append(via_pad(via.at, number=net.pad_number,
                                 drill=p.via_drill, diameter=p.via_diameter))

    return [
        Sym("footprint"),
        name,
        *_header(name, name, ref_y, val_y),
        *fab,
        courtyard,
        *pads,
        [Sym("embedded_fonts"), Sym("no")],
    ]


def trackpad_footprint_text(geo: TrackpadGeometry) -> str:
    """Serialise a trackpad footprint to `.kicad_mod` text (trailing newline)."""
    return sexpr.dumps(trackpad_footprint(geo)) + "\n"
