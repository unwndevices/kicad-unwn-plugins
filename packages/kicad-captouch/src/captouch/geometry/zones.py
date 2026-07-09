"""Optional support-copper geometry: hatched ground pour + guard / ESD ring.

Pure ``params -> shapely polygons`` for the two opt-in, default-off features
described in :mod:`captouch.params.support`. The exporters turn these polygons
into KiCad ``zone`` objects (+ a net-tie pad + a ``GND`` symbol pin); the GUI
preview draws them. Built off each widget's own ``courtyard_outline`` primitive,
so the ground pour and guard ring follow the widget's shape (rect / rounded-rect
/ circle) automatically.

Layout (all offsets measured outward from the electrode outline):

* **guard ring** — an F.Cu band from ``guard_gap`` to ``guard_gap + guard_width``
  out, with a small break at the top so it is not a closed loop (§4.6);
* **ground pour** — a B.Cu region out to ``ground_margin`` (or far enough to cover
  the guard ring, so the single thru-hole net-tie reaches both layers), the wheel
  centre hole punched out;
* **fab / courtyard** — grown to enclose whichever support copper is present
  (only when a feature is on; default-off output is unchanged).

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from shapely.geometry import Point as GeoPoint
from shapely.geometry import Polygon, box

from ..params import has_support
from ._base import COURTYARD_MARGIN, ROUND, Point, polygon_points, rounded_rect_points
from .keypad import KeypadGeometry
from .slider import SliderGeometry
from .trackpad import TrackpadGeometry
from .wheel import WheelGeometry

__all__ = ["SupportCopper", "build_support", "net_tie_number"]

#: Geometry whose support copper we can build (shares ``params``, ``bounds``,
#: ``courtyard_outline``).
SupportGeometry = Union[SliderGeometry, WheelGeometry, TrackpadGeometry, KeypadGeometry]

#: Quarter-circle segments for buffering the support-copper outlines. These are
#: real copper edges (the guard band) / documentation, so smooth but not extreme.
_QUAD_SEGS = 12

#: ``GND`` net-tie pad finished hole + outer copper diameter (mm). 0.3 mm drill is
#: a conservative fab floor (matches the trackpad via default); the ring carries
#: only ground, so it is generous.
NETTIE_DRILL = 0.3
NETTIE_DIAMETER = 0.6


@dataclass(frozen=True)
class SupportCopper:
    """The realised support-copper geometry for one widget.

    All polygons are in geometry millimetres, same frame as the electrodes.
    ``None`` means that feature is disabled.
    """

    ground: Polygon | None  # B.Cu hatched ground pour outline
    guard: Polygon | None  # F.Cu guard / ESD ring band (broken, so an open C)
    mask_open: Polygon | None  # F.Mask aperture over the guard ring (or None)
    net_tie: tuple[str, Point]  # (pad_number, (x, y)) — ties both zones to GND
    #: F.Fab primitives that replace the widget's own, grown to enclose the
    #: support copper. ``("poly", [pts])`` plus, for a wheel, the centre hole.
    fab_outlines: list[tuple]
    #: F.CrtYd outline ring (already includes the courtyard margin).
    courtyard_pts: list[Point]


def net_tie_number(geo: SupportGeometry) -> str | None:
    """Pad/pin number for the ``GND`` net-tie, or ``None`` if no support copper.

    One past the highest electrode / net number, so it never collides. Shared by
    the footprint (pad) and symbol (pin) exporters so they stay 1:1.
    """
    if not has_support(geo.params):
        return None
    if isinstance(geo, TrackpadGeometry):
        nums = [int(n.pad_number) for n in geo.nets]
    else:
        nums = [int(e.pad_number) for e in geo.electrodes]
    return str(max(nums) + 1)


def _primitive_polygon(prim: tuple) -> Polygon:
    """Convert a ``("rect"|"rrect"|"circle", …)`` outline primitive to a Polygon."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        return box(x1, y1, x2, y2)
    if kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        return Polygon(rounded_rect_points(x1, y1, x2, y2, r))
    if kind == "circle":
        _, cx, cy, r = prim
        return GeoPoint(cx, cy).buffer(r, quad_segs=_QUAD_SEGS)
    raise ValueError(f"unknown outline primitive: {prim!r}")


def _grow(poly: Polygon, off: float) -> Polygon:
    """Buffer *poly* outward by *off* with rounded corners (ESD relief, §5.8)."""
    return poly.buffer(off, join_style="round", quad_segs=_QUAD_SEGS)


def build_support(geo: SupportGeometry) -> SupportCopper | None:
    """Build the support-copper geometry for *geo*, or ``None`` if both off.

    Pure: no KiCad/Qt. The result feeds both the footprint exporter (zones +
    net-tie pad + F.Mask aperture + grown fab/courtyard) and the GUI preview.
    """
    p = geo.params
    if not has_support(p):
        return None

    base = _primitive_polygon(geo.courtyard_outline)
    bx0, by0, bx1, by1 = base.bounds

    guard_inner = p.guard_gap
    guard_outer = p.guard_gap + p.guard_width
    # The ground pour reaches at least its own margin and, when a guard ring is
    # present, far enough to sit under it — so the single thru-hole net-tie (placed
    # on the guard band) lands on the ground pour too and bridges both layers.
    ground_off = (
        max(p.ground_margin, guard_outer if p.guard_ring else 0.0) if p.ground_hatch else 0.0
    )
    outer_off = max(ground_off, guard_outer if p.guard_ring else 0.0)

    ground: Polygon | None = None
    if p.ground_hatch:
        g = _grow(base, ground_off)
        if isinstance(geo, WheelGeometry):  # keep the centre keep-out clear of copper
            g = g.difference(GeoPoint(0.0, 0.0).buffer(geo.inner_radius, quad_segs=_QUAD_SEGS))
        ground = g

    guard: Polygon | None = None
    if p.guard_ring:
        band = _grow(base, guard_outer).difference(_grow(base, guard_inner))
        # Break the ring at the top centre (x=0) so it is an open C, never a closed
        # loop antenna (§4.6) — and so it is a single hole-free polygon we can emit
        # as one zone outline. The notch overshoots the band on both sides to cut
        # cleanly.
        notch = box(
            -p.guard_break / 2.0,
            by0 - guard_outer - 1.0,
            p.guard_break / 2.0,
            by0 - guard_inner + 1.0,
        )
        guard = band.difference(notch)

    mask_open = guard if (p.guard_ring and p.guard_mask_open) else None

    number = net_tie_number(geo)
    assert number is not None  # has_support(p) is True here
    if p.guard_ring:  # on the guard band, at the bottom (opposite the top break)
        tie_at = (0.0, by1 + p.guard_gap + p.guard_width / 2.0)
    else:  # only ground: in the bottom margin band, clear of the electrodes
        tie_at = (0.0, by1 + ground_off / 2.0)
    net_tie = (number, (round(tie_at[0], ROUND), round(tie_at[1], ROUND)))

    outer = _grow(base, outer_off)
    fab_outlines: list[tuple] = [("poly", polygon_points(outer))]
    if isinstance(geo, WheelGeometry):
        fab_outlines.append(("circle", 0.0, 0.0, round(geo.inner_radius, ROUND)))
    courtyard_pts = polygon_points(_grow(outer, COURTYARD_MARGIN))

    return SupportCopper(
        ground=ground,
        guard=guard,
        mask_open=mask_open,
        net_tie=net_tie,
        fab_outlines=fab_outlines,
        courtyard_pts=courtyard_pts,
    )
