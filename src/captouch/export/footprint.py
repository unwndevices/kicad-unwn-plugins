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

from .. import __version__, sexpr
from ..geometry import SliderGeometry
from ..geometry.slider import ANCHOR_RADIUS
from ..sexpr import Sym

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
# Slider: one custom pad per electrode + courtyard + fab outline
# --------------------------------------------------------------------------- #
def slider_footprint(geo: SliderGeometry) -> list:
    """Build a footprint node for a slider from its geometry."""
    name = geo.params.name
    minx, miny, maxx, maxy = geo.bounds
    ref_y = miny - 1.5
    val_y = maxy + 1.5

    pads = [
        custom_polygon_pad(e.points, number=e.pad_number, at=e.anchor)
        for e in geo.electrodes
    ]

    m = COURTYARD_MARGIN
    courtyard = _fp_rect(
        (minx - m, miny - m), (maxx + m, maxy + m), layer="F.CrtYd", width=COURTYARD_WIDTH
    )
    fab = _fp_rect((minx, miny), (maxx, maxy), layer="F.Fab", width=FAB_WIDTH)

    return [
        Sym("footprint"),
        name,
        *_header(name, name, ref_y, val_y),
        fab,
        courtyard,
        *pads,
        [Sym("embedded_fonts"), Sym("no")],
    ]


def slider_footprint_text(geo: SliderGeometry) -> str:
    """Serialise a slider footprint to `.kicad_mod` text (trailing newline)."""
    return sexpr.dumps(slider_footprint(geo)) + "\n"
