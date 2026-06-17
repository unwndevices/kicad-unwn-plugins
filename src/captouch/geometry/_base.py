"""Shared geometry primitives for every widget (slider, wheel, …).

Both widgets reduce to the same construction: lay copper, cut uniform-width gap
strips, and label the resulting electrodes. The pieces common to that — the
:class:`Electrode` record, the anchor-point picker, corner rounding, and the
tessellation constants — live here so each widget module only holds its own
shape-specific layout.

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon

__all__ = [
    "Point",
    "Electrode",
    "GeometryError",
    "ANCHOR_RADIUS",
    "round_corners",
    "anchor_point",
    "tip_relief_radius",
]

Point = tuple[float, float]

# Maps the user-facing shape name to the waveform kind.
SHAPE_TO_KIND = {
    "rectangular": "rectangular",
    "chevron": "triangle",
    "interdigitated": "square",
}

# Quarter-circle segments for gap-strip round joins (and ESD rounding). 2 keeps
# emitted pads lean while still rounding gap corners; finer than the fab can
# resolve at a 0.25 mm fillet anyway.
ARC_QUAD_SEGS = 2

# Coordinate rounding (mm). 1e-4 mm = 0.1 um, far below fab resolution; keeps
# emitted coordinates and golden files stable.
ROUND = 4

# Anchor circle radius (mm) for the custom pads (see exporter). The interior
# point each electrode exposes must comfortably contain this.
ANCHOR_RADIUS = 0.25


class GeometryError(ValueError):
    """Raised when widget geometry cannot be built as expected."""


@dataclass(frozen=True)
class Electrode:
    """One physical electrode and how it maps to a pad / symbol pin."""

    polygon: Polygon
    pad_number: str
    pin_name: str
    role: str  # "active" | "dummy"
    anchor: Point  # interior point for the custom-pad anchor

    @property
    def points(self) -> list[Point]:
        """Exterior ring as ``(x, y)`` vertices, no duplicate closing point."""
        coords = list(self.polygon.exterior.coords)
        if coords and coords[0] == coords[-1]:
            coords = coords[:-1]
        return [(round(x, ROUND), round(y, ROUND)) for x, y in coords]


def anchor_point(poly: Polygon) -> Point:
    """An interior point comfortably containing the anchor circle."""
    inner = poly.buffer(-ANCHOR_RADIUS, quad_segs=ARC_QUAD_SEGS)
    src = poly if inner.is_empty else inner
    p = src.representative_point()
    return (round(p.x, ROUND), round(p.y, ROUND))


def tip_relief_radius(segment_shape: str, corner_radius: float, tip_radius: float) -> float:
    """Convex-rounding radius to apply to an electrode's corners.

    Chevron tooth-tips are acute and taper to fab-resolution copper slivers, so
    they get at least ``tip_radius`` of rounding (a chevron stays DRC-clean even
    when ``corner_radius`` is 0). Square (interdigitated) and straight
    (rectangular) boundaries have no acute tips, so only the user's explicit
    ``corner_radius`` applies — rounding them by ``tip_radius`` would needlessly
    erode fine comb teeth.
    """
    if segment_shape == "chevron":
        return max(corner_radius, tip_radius)
    return corner_radius


# Descending fractions of the requested radius to try per segment. A
# morphological open can erase or split a thin feature, and GEOS does so
# non-monotonically (a radius may fail while both a larger and a smaller one
# succeed), so we fall back to progressively gentler rounding rather than crash.
_ROUND_FALLBACKS = (1.0, 0.8, 0.6, 0.4, 0.2)


def round_corners(parts: list[Polygon], r: float) -> list[Polygon]:
    """ESD relief: round convex (outer) corners via a morphological open.

    Best-effort and never raises: each segment is rounded by the largest sampled
    radius up to *r* that still yields a single valid polygon; a segment too thin
    for any rounding is left as built (sharp). This keeps the live GUI preview
    robust to any radius the user dials in.
    """
    if r <= 0:
        return parts
    rounded: list[Polygon] = []
    for g in parts:
        rounded.append(_round_one(g, r))
    return rounded


def _round_one(g: Polygon, r: float) -> Polygon:
    for factor in _ROUND_FALLBACKS:
        rr = r * factor
        g2 = g.buffer(-rr, quad_segs=ARC_QUAD_SEGS).buffer(rr, quad_segs=ARC_QUAD_SEGS)
        if (not g2.is_empty) and g2.geom_type == "Polygon" and g2.area > 0:
            return g2
    return g  # too thin to round at all — keep the sharp original
