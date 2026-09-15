"""Build a single self-cap button electrode from :class:`ButtonParams`.

The button is one (or two, with a ground hat) custom pad clipped to a square or
circle outline. Patterned styles are built as **positive copper** — hub, legs,
rim, comb fingers, hatch lines — then intersected with the outline so a square
and a circle share the same construction.

* ``solid`` — the outline, optionally corner-rounded.
* ``radial`` — hub + radiating legs; without a hat the outer rim joins them into
  a snowflake; with a hat the rim and the inter-leg pies become the ``GND`` pad.
* ``interdigitated`` / ``chevron`` — parallel or zigzag fingers. Without a hat
  the rim keeps one connected sense pad; with a hat a gap strip splits the
  outline into sense + ``GND``.
* ``hatch`` — a two-direction mesh unioned with the rim (always one pad).

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..params import ButtonParams, validate_button
from ._base import (
    ROUND,
    Electrode,
    GeometryError,
    anchor_point,
    round_corners,
)
from .waveform import boundary_points

__all__ = ["ButtonGeometry", "build_button"]

#: Quarter-circle segments for a round outline / hub (16 → a 64-gon).
CIRCLE_QUAD_SEGS = 16

#: Radial spoke length as a fraction of :attr:`ButtonParams.size`. 0.75 covers a
#: square's half-diagonal (√2/2 ≈ 0.707) so legs reach the corners, then clip.
_SPOKE_REACH = 0.75


@dataclass(frozen=True)
class ButtonGeometry:
    """The complete geometric model of a single self-cap button."""

    electrodes: list[Electrode]
    bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    params: ButtonParams

    @property
    def active(self) -> list[Electrode]:
        return [e for e in self.electrodes if e.role == "active"]

    @property
    def dummies(self) -> list[Electrode]:
        return [e for e in self.electrodes if e.role == "dummy"]

    @property
    def fab_primitives(self) -> list[tuple]:
        """F.Fab documentation shapes: the nominal outline."""
        return [_fab_primitive(self.params)]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin."""
        return _fab_primitive(self.params)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin lists: sense on the left, hat ``GND`` on the right."""
        left = [(e.pad_number, e.pin_name) for e in self.active]
        right = [(e.pad_number, e.pin_name) for e in self.dummies]
        return left, right


def _outline(params: ButtonParams) -> Polygon:
    """The square or circular clipping outline, ESD-rounded when asked."""
    h = params.size / 2.0
    if params.outline == "circle":
        return Point(0.0, 0.0).buffer(h, quad_segs=CIRCLE_QUAD_SEGS)
    poly: Polygon = box(-h, -h, h, h)
    if params.corner_radius > 0:
        poly = round_corners([poly], params.corner_radius)[0]
    return poly


def _fab_primitive(params: ButtonParams) -> tuple:
    """Nominal F.Fab outline matching :attr:`ButtonParams.outline`."""
    h = params.size / 2.0
    if params.outline == "circle":
        return ("circle", 0.0, 0.0, round(h, ROUND))
    return ("rect", round(-h, ROUND), round(-h, ROUND), round(h, ROUND), round(h, ROUND))


def _rim(outline: Polygon, width: float) -> Polygon | None:
    """Outer frame of *width*, or ``None`` when *width* is 0 / would swallow the pad."""
    if width <= 0:
        return None
    inner = outline.buffer(-width)
    if inner.is_empty:
        return None
    rim = outline.difference(inner)
    return None if rim.is_empty else rim


def _as_polygon(g: BaseGeometry, label: str) -> Polygon:
    """Require a single non-empty polygon; MultiPolygons are a geometry failure."""
    if g.is_empty:
        raise GeometryError(f"{label} is empty — reduce num_legs / air_gap, or enlarge the button")
    if isinstance(g, Polygon):
        return g
    if isinstance(g, MultiPolygon):
        raise GeometryError(
            f"{label} split into {len(g.geoms)} pieces — reduce num_legs or air_gap"
        )
    raise GeometryError(f"{label} is not a polygon ({g.geom_type})")


def _union(parts: list[BaseGeometry | None]) -> BaseGeometry:
    live = [p for p in parts if p is not None and not p.is_empty]
    if not live:
        return Polygon()
    return unary_union(live)


def _spoke(ang: float, r0: float, r1: float, width: float) -> Polygon:
    """A constant-width radial copper leg from *r0* to *r1* at angle *ang*."""
    p0 = (r0 * math.cos(ang), r0 * math.sin(ang))
    p1 = (r1 * math.cos(ang), r1 * math.sin(ang))
    return LineString([p0, p1]).buffer(width / 2.0, cap_style="square")


def _spokes(n: int, r0: float, r1: float, width: float, *, phase: float = 0.0) -> list[Polygon]:
    return [_spoke(2.0 * math.pi * (i + phase) / n, r0, r1, width) for i in range(n)]


def _radial(params: ButtonParams, outline: Polygon) -> BaseGeometry:
    """Hub + radiating legs, optionally joined by the outer rim (no hat)."""
    hub_r = params.effective_hub_diameter / 2.0
    hub = Point(0.0, 0.0).buffer(hub_r, quad_segs=CIRCLE_QUAD_SEGS)
    reach = params.size * _SPOKE_REACH
    w = params.effective_leg_width
    n = params.num_legs
    rim_w = params.effective_rim_width
    legs = _spokes(n, 0.0, reach, w)
    if params.ground_hat:
        # Keep sense inside the hat ring so the rim stays one connected GND piece.
        keepout = outline.buffer(-(rim_w + params.air_gap))
        if keepout.is_empty:
            keepout = outline.buffer(-rim_w)
        clip = keepout if not keepout.is_empty else outline
        return _union([hub, *legs]).intersection(clip)
    rim = _rim(outline, rim_w)
    return _union([hub, *legs, rim]).intersection(outline)


def _radial_hat(params: ButtonParams, outline: Polygon, sense: BaseGeometry) -> BaseGeometry:
    """Outer rim plus inward hat-legs, offset between the sense spokes."""
    rim_w = params.effective_rim_width
    w = params.effective_leg_width
    n = params.num_legs
    reach = params.size * _SPOKE_REACH
    r_start = params.effective_hub_diameter / 2.0 + params.air_gap
    rim = _rim(outline, rim_w)
    hat = _union([rim, *_spokes(n, r_start, reach, w, phase=0.5)]).intersection(outline)
    # Gap is already in the spoke offset / keepout; only subtract actual sense copper.
    return hat.difference(sense)


def _parallel_slots(params: ButtonParams, outline: Polygon, kind: str) -> Polygon:
    """Unipolar comb / chevron: cut gap strips that stop inside the rim."""
    rim_w = params.effective_rim_width
    inner = outline.buffer(-max(rim_w, 0.01))
    if inner.is_empty:
        return outline
    h = params.size / 2.0
    n = params.num_legs
    gap = params.air_gap
    # n copper fingers → n-1 slots between them, plus we leave the rim intact.
    if kind == "chevron":
        amp = max(h - rim_w - gap, h * 0.3)
        pts = boundary_points(0.0, amp, n, -h - gap, h + gap, "triangle")
        strip = LineString(pts).buffer(gap / 2.0, cap_style="flat", join_style="round")
        slots = strip.intersection(inner)
    else:
        # Evenly spaced horizontal slots across the inner region.
        span = params.size - 2.0 * rim_w
        pitch = span / n
        slots_g = []
        minx, miny, maxx, maxy = inner.bounds
        for i in range(1, n):
            y = -h + rim_w + i * pitch
            slots_g.append(box(minx - 1.0, y - gap / 2.0, maxx + 1.0, y + gap / 2.0))
        slots = _union(slots_g).intersection(inner)
    if slots.is_empty:
        return outline
    return outline.difference(slots)


def _split_hat(params: ButtonParams, outline: Polygon, kind: str) -> tuple[Polygon, Polygon]:
    """Bipolar comb: a gap strip splits the outline into sense + hat."""
    h = params.size / 2.0
    gap = params.air_gap
    amp = max(h - params.effective_rim_width - gap, h * 0.3)
    wave = "triangle" if kind == "chevron" else "square"
    pts = boundary_points(0.0, amp, params.num_legs, -h - gap, h + gap, wave)
    strip = LineString(pts).buffer(gap / 2.0, cap_style="flat", join_style="round")
    copper = outline.difference(strip)
    parts = list(copper.geoms) if isinstance(copper, MultiPolygon) else [copper]
    parts = [p for p in parts if not p.is_empty and p.area > 0]
    if len(parts) < 2:
        raise GeometryError(
            "ground hat split the button into fewer than 2 pieces; "
            "reduce num_legs or air_gap, or enlarge the button"
        )
    parts.sort(key=lambda g: g.centroid.x)
    return parts[0], parts[-1]


def _hatch(params: ButtonParams, outline: Polygon) -> BaseGeometry:
    """Two-direction mesh plus rim, clipped to the outline (one connected pad)."""
    w = params.effective_leg_width
    pitch = w + params.air_gap
    if pitch <= 0:
        return outline
    half = params.size
    lines = []
    t = -half
    while t <= half + 1e-9:
        lines.append(LineString([(t, -half), (t, half)]).buffer(w / 2.0, cap_style="flat"))
        lines.append(LineString([(-half, t), (half, t)]).buffer(w / 2.0, cap_style="flat"))
        t += pitch
    mesh = _union(lines)
    rim = _rim(outline, params.effective_rim_width)
    return _union([mesh, rim]).intersection(outline)


def _copper(params: ButtonParams, outline: Polygon) -> tuple[BaseGeometry, BaseGeometry | None]:
    """Return ``(sense, hat)``; *hat* is ``None`` when :attr:`ground_hat` is off."""
    style = params.style
    if style == "solid":
        return outline, None
    if style == "radial":
        sense = _radial(params, outline)
        hat = _radial_hat(params, outline, sense) if params.ground_hat else None
        return sense, hat
    if style == "hatch":
        return _hatch(params, outline), None
    if style in ("interdigitated", "chevron"):
        if params.ground_hat:
            return _split_hat(params, outline, style)
        return _parallel_slots(params, outline, style), None
    raise GeometryError(f"unknown button style {style!r}")


def build_button(params: ButtonParams) -> ButtonGeometry:
    """Build a :class:`ButtonGeometry` from validated *params*."""
    validate_button(params)
    outline = _outline(params)
    sense_raw, hat_raw = _copper(params, outline)
    sense = _as_polygon(sense_raw, "sense electrode")
    electrodes = [
        Electrode(
            polygon=sense,
            pad_number="1",
            pin_name="BTN",
            role="active",
            anchor=anchor_point(sense),
        )
    ]
    if hat_raw is not None:
        hat = _as_polygon(hat_raw, "ground hat")
        electrodes.append(
            Electrode(
                polygon=hat,
                pad_number="2",
                pin_name="GND",
                role="dummy",
                anchor=anchor_point(hat),
            )
        )

    union = unary_union([e.polygon for e in electrodes])
    minx, miny, maxx, maxy = union.bounds
    bounds = (round(minx, ROUND), round(miny, ROUND), round(maxx, ROUND), round(maxy, ROUND))
    return ButtonGeometry(electrodes=electrodes, bounds=bounds, params=params)
