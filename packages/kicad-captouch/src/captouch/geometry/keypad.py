"""Build keypad electrode polygons from :class:`KeypadParams`.

A keypad is the simplest construction: an ``R×C`` grid of identical, independent
button electrodes laid on a square pitch of ``button_size + gap``, centred on the
origin. Each button is one self-cap electrode → one custom pad → one symbol pin
(no interpolation, no shared rows/columns), so — unlike the slider/wheel (which
*cut* gap strips out of continuous copper) — the buttons are simply placed; the
uniform ``gap`` falls out of the pitch.

Three button shapes (all optionally ESD-corner-rounded):

* ``"rect"`` — a square pad of side ``button_size``;
* ``"circle"`` — a round pad of diameter ``button_size`` (polyline-approximated,
  since KiCad custom-pad polygons hold no true arcs);
* ``"diamond"`` — a square rotated 45°, full diagonal ``button_size``.

Buttons are numbered row-major (top row first, left to right) as pads ``1..N`` /
pins ``K1..KN``. The result is an :class:`Electrode`-list geometry, so it reuses
the shared electrode footprint/symbol exporters and the live preview verbatim.

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from ..params import KeypadParams, validate_keypad
from ._base import (
    ROUND,
    Electrode,
    anchor_point,
    round_corners,
)
from ._base import (
    Point as XY,
)

__all__ = ["KeypadGeometry", "build_keypad"]

#: Quarter-circle segments for a round button (buffer ``quad_segs``); 16 → a 64-gon,
#: smooth at any sensible button size while keeping the emitted pad lean.
CIRCLE_QUAD_SEGS = 16


@dataclass(frozen=True)
class KeypadGeometry:
    """The complete geometric model of a keypad (button grid)."""

    electrodes: list[Electrode]
    centers: list[XY]  # nominal button centres, parallel to ``electrodes``
    bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    params: KeypadParams

    @property
    def active(self) -> list[Electrode]:
        return list(self.electrodes)  # every button is an active electrode

    @property
    def dummies(self) -> list[Electrode]:
        return []  # a keypad has no grounded dummy electrodes

    # -- documentation outline (shared exporter / preview, see export module) - #
    @property
    def fab_primitives(self) -> list[tuple]:
        """F.Fab documentation shapes: one nominal outline per button."""
        p = self.params
        return [_fab_primitive(p.button_shape, c, p.button_size) for c in self.centers]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin."""
        minx, miny, maxx, maxy = self.bounds
        return ("rect", minx, miny, maxx, maxy)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin lists: the grid's buttons split into halves."""
        pairs = [(e.pad_number, e.pin_name) for e in self.electrodes]
        half = (len(pairs) + 1) // 2
        return pairs[:half], pairs[half:]


def _button_polygon(shape: str, cx: float, cy: float, size: float) -> Polygon:
    """One button electrode polygon of *shape*, centred on ``(cx, cy)``."""
    h = size / 2.0
    if shape == "circle":
        return Point(cx, cy).buffer(h, quad_segs=CIRCLE_QUAD_SEGS)
    if shape == "diamond":  # square rotated 45°, full diagonal = size
        return Polygon([(cx, cy - h), (cx + h, cy), (cx, cy + h), (cx - h, cy)])
    return box(cx - h, cy - h, cx + h, cy + h)  # rect (square)


def _fab_primitive(shape: str, center: XY, size: float) -> tuple:
    """The nominal F.Fab outline primitive for a button of *shape* at *center*."""
    cx, cy = center
    h = size / 2.0
    if shape == "circle":
        return ("circle", round(cx, ROUND), round(cy, ROUND), round(h, ROUND))
    if shape == "diamond":
        pts = [(cx, cy - h), (cx + h, cy), (cx, cy + h), (cx - h, cy)]
        return ("poly", [(round(x, ROUND), round(y, ROUND)) for x, y in pts])
    return (
        "rect",
        round(cx - h, ROUND),
        round(cy - h, ROUND),
        round(cx + h, ROUND),
        round(cy + h, ROUND),
    )


def build_keypad(params: KeypadParams) -> KeypadGeometry:
    """Build a :class:`KeypadGeometry` from validated *params*."""
    validate_keypad(params)

    shape = params.button_shape
    size = params.button_size
    pitch = params.pitch
    # Centre the grid on the origin; row 0 is the top (smallest y, KiCad y-down).
    x0 = -(params.num_cols - 1) * pitch / 2.0
    y0 = -(params.num_rows - 1) * pitch / 2.0

    electrodes: list[Electrode] = []
    centers: list[XY] = []
    n = 0
    for r in range(params.num_rows):
        cy = y0 + r * pitch
        for c in range(params.num_cols):
            cx = x0 + c * pitch
            n += 1
            poly = _button_polygon(shape, cx, cy, size)
            # ESD relief on the (square / rhombus) corners; a circle is already round.
            if shape != "circle" and params.corner_radius > 0:
                poly = round_corners([poly], params.corner_radius)[0]
            electrodes.append(
                Electrode(
                    polygon=poly,
                    pad_number=str(n),
                    pin_name=f"K{n}",
                    role="active",
                    anchor=anchor_point(poly),
                )
            )
            centers.append((round(cx, ROUND), round(cy, ROUND)))

    union = unary_union([e.polygon for e in electrodes])
    minx, miny, maxx, maxy = union.bounds
    bounds = (round(minx, ROUND), round(miny, ROUND), round(maxx, ROUND), round(maxy, ROUND))
    return KeypadGeometry(electrodes=electrodes, centers=centers, bounds=bounds, params=params)
