"""Shared geometry primitives for every widget (slider, wheel, …).

Both widgets reduce to the same construction: lay copper, cut uniform-width gap
strips, and label the resulting electrodes. The pieces common to that — the
:class:`Electrode` record, the anchor-point picker, corner rounding, and the
tessellation constants — live here so each widget module only holds its own
shape-specific layout.

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.ops import split

__all__ = [
    "Point",
    "Electrode",
    "GeometryError",
    "ANCHOR_RADIUS",
    "COURTYARD_MARGIN",
    "RRECT_ARC_SEGS",
    "round_corners",
    "anchor_point",
    "hole_free_parts",
    "polygon_points",
    "rounded_rect_points",
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

# Courtyard inflation (mm) around the copper/outline bounding shape. Lives here
# (not in the exporter) so the geometry layer — including the support-copper zone
# builder — can size a matching courtyard. Re-exported by the footprint exporter.
COURTYARD_MARGIN = 0.25

# Segments per 90° quarter-arc when polyline-approximating a rounded-rectangle
# *outline* (F.Fab / silk / courtyard). These are documentation lines, not
# copper, so they can be smoother than the lean ARC_QUAD_SEGS used for pad fillets.
RRECT_ARC_SEGS = 12


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


def polygon_points(poly: Polygon) -> list[Point]:
    """A polygon's exterior ring as rounded ``(x, y)`` vertices, no closing dup.

    The standalone form of :attr:`Electrode.points`, reused by widgets (e.g. the
    trackpad) whose copper is not a single :class:`Electrode`.
    """
    coords = list(poly.exterior.coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(round(x, ROUND), round(y, ROUND)) for x, y in coords]


def hole_free_parts(poly: Polygon) -> list[Polygon]:
    """Split *poly* into hole-free polygons whose union is *poly*.

    A KiCad custom-pad primitive is a simple outline, so copper with holes (a framed
    trackpad electrode) is emitted as several primitives of one pad, which KiCad
    merges back with the holes intact. Each hole is cut by a vertical line through
    an interior point of it; the pieces abut exactly along the cuts. A hole-free
    *poly* comes back as ``[poly]`` unchanged.
    """
    if not poly.interiors:
        return [poly]
    pending, out = [poly], []
    while pending:
        g = pending.pop()
        if not g.interiors:
            out.append(g)
            continue
        hx = Polygon(g.interiors[0]).representative_point().x
        _, miny, _, maxy = g.bounds
        cut = LineString([(hx, miny - 1.0), (hx, maxy + 1.0)])
        pending.extend(p for p in split(g, cut).geoms if isinstance(p, Polygon))
    return sorted(out, key=lambda p: (p.bounds[0], p.bounds[1]))


def rounded_rect_points(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    segs: int = RRECT_ARC_SEGS,
) -> list[Point]:
    """Vertices of a rounded rectangle ``[x1,x2]×[y1,y2]`` with corner radius *r*.

    Returns a closed ring of ``(x, y)`` points (no duplicate closing vertex),
    clockwise in KiCad coordinates (y down). Each 90° corner is approximated by
    *segs* line segments; the four straight edges are the implicit polygon edges
    between consecutive corner arcs. *r* is clamped to half the shorter side.

    Shared by the footprint exporter and the GUI preview so the emitted outline
    and the previewed outline match vertex-for-vertex.
    """
    r = min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0)
    if r <= 0:
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    quarter = math.pi / 2.0
    # (center_x, center_y, start_angle) per corner, each swept +90° clockwise.
    # With y increasing downward, increasing the math-convention angle traces a
    # visually clockwise path: −90°→top, 0°→right, +90°→bottom, 180°→left.
    corners = [
        (x2 - r, y1 + r, -quarter),  # top-right
        (x2 - r, y2 - r, 0.0),  # bottom-right
        (x1 + r, y2 - r, quarter),  # bottom-left
        (x1 + r, y1 + r, math.pi),  # top-left
    ]
    pts: list[Point] = []
    for cx, cy, a0 in corners:
        for i in range(segs + 1):
            a = a0 + quarter * i / segs
            pts.append((round(cx + r * math.cos(a), ROUND), round(cy + r * math.sin(a), ROUND)))
    return pts


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
