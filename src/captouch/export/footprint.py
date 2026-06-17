"""Emit a KiCad footprint (`.kicad_mod`) whose electrode is a custom-shape pad.

A touch electrode is represented as a single **custom-shaped SMD copper pad** on
``F.Cu`` (so it carries a net and DRC sees it), whose outline is a closed polygon
supplied as ``(x, y)`` points in millimetres. The output targets the KiCad 9.0
footprint format (``version 20241229``), which both KiCad 9 and 10 accept.

Phase 0 emits one pad from one polygon; the real per-widget geometry (chevron,
interdigitated, diamond) is produced by the geometry layer in later phases.
"""

from __future__ import annotations

from typing import Sequence

from .. import __version__, sexpr
from ..sexpr import Sym

# KiCad 9.0 footprint/board S-expression format version (date token). KiCad 10
# reads and upgrades it; emitting a newer token would make KiCad 9 reject it.
FOOTPRINT_VERSION = 20241229
GENERATOR = "kicad-captouch"

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


def custom_polygon_pad(
    points: Sequence[Point],
    *,
    number: str = "1",
    layer: str = "F.Cu",
    anchor: float = 0.5,
) -> list:
    """Build a custom-shape SMD pad node from a closed polygon outline."""
    if len(points) < 3:
        raise ValueError("a polygon pad needs at least 3 points")
    return [
        Sym("pad"),
        number,
        Sym("smd"),
        Sym("custom"),
        [Sym("at"), 0, 0],
        [Sym("size"), anchor, anchor],
        [Sym("layers"), layer],
        [Sym("options"), [Sym("clearance"), Sym("outline")], [Sym("anchor"), Sym("circle")]],
        [
            Sym("primitives"),
            [Sym("gr_poly"), _pts(points), [Sym("width"), 0], [Sym("fill"), Sym("yes")]],
        ],
    ]


def electrode_footprint(name: str, polygon: Sequence[Point], *, value: str | None = None) -> list:
    """Build a footprint node containing a single custom-polygon electrode pad."""
    return [
        Sym("footprint"),
        name,
        [Sym("version"), FOOTPRINT_VERSION],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), __version__],
        [Sym("layer"), "F.Cu"],
        _property("Reference", "REF**", (0, -1, 0), "F.SilkS"),
        _property("Value", value or name, (0, 1, 0), "F.Fab"),
        [Sym("attr"), Sym("smd")],
        custom_polygon_pad(polygon, number="1"),
        [Sym("embedded_fonts"), Sym("no")],
    ]


def footprint_text(name: str, polygon: Sequence[Point], *, value: str | None = None) -> str:
    """Serialise an electrode footprint to `.kicad_mod` text (trailing newline)."""
    return sexpr.dumps(electrode_footprint(name, polygon, value=value)) + "\n"
