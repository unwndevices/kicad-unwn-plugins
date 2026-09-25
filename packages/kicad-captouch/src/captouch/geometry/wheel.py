"""Build wheel electrode polygons from :class:`WheelParams`.

The wheel is the slider construction bent into polar coordinates — the same
"cut uniform gap strips out of the copper" idea, around a ring instead of along
a bar:

1. Build a tessellated **annulus**: outer disk (radius ``outer_radius``) minus a
   centre keep-out disk (radius ``inner_radius``). KiCad custom-pad polygons
   cannot hold true arcs, so the circles are approximated as polylines at
   ``arc_resolution`` segments per quarter turn.
2. For each of the ``M = num_segments`` boundaries (a *closed* ring has M, not
   M-1), build a **radial** waveform that runs from the hole outward and
   oscillates *angularly*: the slider's 1-D waveform reused with its oscillation
   mapped to angle (half-amplitude ``amplitude / mean_radius`` radians) and its
   span mapped to radius. Buffer each by ``A/2`` into a uniform gap strip.
3. Subtract the union of the strips from the annulus → exactly ``M`` wedge
   electrodes, separated by a uniform ``A`` gap. Wheels are continuous, so every
   electrode is active (no end dummies).

The gap is an offset of the boundary, so — as for the slider — it is uniform in
millimetres everywhere (not in angle).

The wheel-only ``"spiral"`` shape replaces the angular oscillation with a steady
**twist**: each boundary is a radial polyline whose angular offset ramps linearly
from 0 at the inner radius to ``spiral_angle`` (degrees) at the outer radius, so
the electrodes interleave into a smooth iPod-style swirl. Because every spiral
boundary is a rigid rotation of one another they never cross, and the same
buffer-and-subtract construction yields exactly ``M`` swirled wedges. Spiral is
toothless (``num_fingers`` / ``tooth_depth`` ignored, ``amplitude`` is ``0``).

When ``teeth_follow_curve`` is set, the same chevron / interdigitated waveforms
are tessellated in polar coordinates so **constant-radius runs become circular
arcs** (and mixed r/θ runs become short Archimedean spirals) instead of cutting
cartesian chords across the ring. That is the Microchip-style circumferential
interleave a 3-channel QT2120 wheel needs: tines follow the annulus, so
interpolation stays continuous instead of leaving mid-pad dead zones. The flag
is a no-op on rectangular (already a radial line) and ignored for spiral
(already a polar curve).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, Point
from shapely.ops import unary_union

from ..params import WheelParams, validate_wheel
from . import waveform
from ._base import (
    ARC_QUAD_SEGS,
    ROUND,
    SHAPE_TO_KIND,
    Electrode,
    GeometryError,
    anchor_point,
    round_corners,
    tip_relief_radius,
)

__all__ = ["WheelGeometry", "build_wheel"]


@dataclass(frozen=True)
class WheelGeometry:
    """The complete geometric model of a wheel."""

    electrodes: list[Electrode]
    bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    params: WheelParams
    inner_radius: float
    outer_radius: float
    mean_radius: float

    @property
    def active(self) -> list[Electrode]:
        return list(self.electrodes)  # a wheel is continuous: all active

    @property
    def dummies(self) -> list[Electrode]:
        return []

    # -- documentation outline (shared exporter / preview, see export module) - #
    @property
    def fab_primitives(self) -> list[tuple]:
        """F.Fab shapes: the outer edge and the centre keep-out hole."""
        return [
            ("circle", 0.0, 0.0, self.outer_radius),
            ("circle", 0.0, 0.0, self.inner_radius),
        ]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin."""
        return ("circle", 0.0, 0.0, self.outer_radius)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin lists: the ring's electrodes split into halves."""
        pairs = [(e.pad_number, e.pin_name) for e in self.electrodes]
        half = (len(pairs) + 1) // 2
        return pairs[:half], pairs[half:]


def _polar_to_cartesian(
    theta: float,
    wf: list[tuple[float, float]],
    quad_segs: int,
) -> list[tuple[float, float]]:
    """Map a polar ``(angular-offset, radius)`` polyline to cartesian.

    Spans that change angle are tessellated at ``quad_segs`` segments per 90°
    so constant-radius runs become circular arcs (and mixed r/θ runs become
    short Archimedean spirals) instead of a single cartesian chord. Radial
    spans (constant angle) stay two-point lines.
    """
    if not wf:
        return []
    da0, r0 = wf[0]
    pts = [(r0 * math.cos(theta + da0), r0 * math.sin(theta + da0))]
    quarter = math.pi / 2.0
    for da1, r1 in wf[1:]:
        dtheta = da1 - da0
        if abs(dtheta) < 1e-15:
            pts.append((r1 * math.cos(theta + da1), r1 * math.sin(theta + da1)))
        else:
            n = max(1, round(quad_segs * abs(dtheta) / quarter))
            for i in range(1, n + 1):
                t = i / n
                da = da0 + t * dtheta
                rho = r0 + t * (r1 - r0)
                pts.append((rho * math.cos(theta + da), rho * math.sin(theta + da)))
        da0, r0 = da1, r1
    return pts


def build_wheel(params: WheelParams) -> WheelGeometry:
    """Build a :class:`WheelGeometry` from validated *params*."""
    validate_wheel(params)

    m = params.num_segments
    a = params.air_gap
    ri = params.inner_radius
    ro = params.outer_radius
    rm = params.mean_radius
    amp_ang = (params.amplitude / rm) if rm > 0 else 0.0  # angular half-amplitude
    q = params.arc_resolution

    # Annulus: outer disk minus the centre keep-out.
    outer = Point(0.0, 0.0).buffer(ro, quad_segs=q)
    inner = Point(0.0, 0.0).buffer(ri, quad_segs=q)
    annulus = outer.difference(inner)

    ext = a  # extend boundaries past both ring edges so strips cut cleanly
    r_lo = max(0.0, ri - ext)
    r_hi = ro + ext
    step = 2.0 * math.pi / m

    shape = params.segment_shape
    spiral = shape == "spiral"
    follow_curve = bool(params.teeth_follow_curve) and not spiral
    if spiral:
        # A spiral boundary is a radial polyline whose angular offset ramps
        # linearly from 0 at r_lo to spiral_angle (rad) at r_hi — a steady twist
        # instead of an oscillation. Every boundary is the same (da, rho) polyline
        # rotated, so build it once. Tessellate finely enough that the swirl reads
        # smooth, with a handful of points even for a tiny twist.
        twist = math.radians(params.spiral_angle)
        nsamp = max(8, round(params.arc_resolution * abs(params.spiral_angle) / 90.0))
        spiral_wf: list[tuple[float, float]] = [
            (twist * i / nsamp, r_lo + (r_hi - r_lo) * i / nsamp) for i in range(nsamp + 1)
        ]
    else:
        kind = SHAPE_TO_KIND[shape]

    strips = []
    for k in range(m):
        theta = (k + 0.5) * step  # boundary sits between two segment centres
        # waveform in (angular-offset, radius) space, then mapped to cartesian.
        if spiral:
            wf = spiral_wf
        else:
            wf = waveform.boundary_points(0.0, amp_ang, params.num_fingers, r_lo, r_hi, kind)
        if follow_curve:
            pts = _polar_to_cartesian(theta, wf, q)
        else:
            pts = [(rho * math.cos(theta + da), rho * math.sin(theta + da)) for (da, rho) in wf]
        strip = LineString(pts).buffer(
            a / 2.0, cap_style="flat", join_style="round", quad_segs=ARC_QUAD_SEGS
        )
        strips.append(strip)

    copper = annulus.difference(unary_union(strips))
    parts = list(copper.geoms) if isinstance(copper, MultiPolygon) else [copper]
    if len(parts) != m:
        raise GeometryError(
            f"expected {m} wheel segments but geometry produced {len(parts)}; "
            f"reduce tooth_depth or num_segments, or widen the ring"
        )

    # Order the wedges around the ring (CCW from the +x axis) so pad numbering is
    # consistent; assign each to its nearest segment-centre index (noise-robust).
    def seg_index(g) -> int:
        ang = math.atan2(g.centroid.y, g.centroid.x)
        return round(ang / step) % m

    parts.sort(key=seg_index)

    # Round convex corners: chevron tips get at least tip_radius (acute on a
    # short ring, else they sliver); other shapes use only corner_radius.
    r_corner = tip_relief_radius(params.segment_shape, params.corner_radius, params.tip_radius)
    parts = round_corners(parts, r_corner)

    electrodes = [
        Electrode(
            polygon=poly,
            pad_number=str(i + 1),
            pin_name=f"E{i + 1}",
            role="active",
            anchor=anchor_point(poly),
        )
        for i, poly in enumerate(parts)
    ]

    union = unary_union(parts)
    minx, miny, maxx, maxy = union.bounds
    bounds = (round(minx, ROUND), round(miny, ROUND), round(maxx, ROUND), round(maxy, ROUND))
    return WheelGeometry(
        electrodes=electrodes,
        bounds=bounds,
        params=params,
        inner_radius=round(ri, ROUND),
        outer_radius=round(ro, ROUND),
        mean_radius=round(rm, ROUND),
    )
