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
)

__all__ = ["WheelGeometry", "build_wheel"]

# Minimum convex rounding applied to chevron tooth-tips regardless of the user's
# corner_radius. A wheel's short ring makes triangle-wave tips acute enough to
# taper to sub-fab-resolution copper slivers (KiCad DRC flags these); ~0.1 mm of
# tip relief removes them. Square (interdigitated) and straight (rectangular)
# boundaries have no acute tips and are left untouched. (The slider does not need
# this at its default proportions, so it keeps sharp tips.)
_CHEVRON_TIP_RELIEF = 0.12


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


def build_wheel(params: WheelParams) -> WheelGeometry:
    """Build a :class:`WheelGeometry` from validated *params*."""
    validate_wheel(params)

    m = params.num_segments
    a = params.air_gap
    ri = params.inner_radius
    ro = params.outer_radius
    rm = params.mean_radius
    amp_ang = (params.amplitude / rm) if rm > 0 else 0.0  # angular half-amplitude
    kind = SHAPE_TO_KIND[params.segment_shape]
    q = params.arc_resolution

    # Annulus: outer disk minus the centre keep-out.
    outer = Point(0.0, 0.0).buffer(ro, quad_segs=q)
    inner = Point(0.0, 0.0).buffer(ri, quad_segs=q)
    annulus = outer.difference(inner)

    ext = a  # extend boundaries past both ring edges so strips cut cleanly
    r_lo = max(0.0, ri - ext)
    r_hi = ro + ext
    step = 2.0 * math.pi / m

    strips = []
    for k in range(m):
        theta = (k + 0.5) * step  # boundary sits between two segment centres
        # waveform in (angular-offset, radius) space, then mapped to cartesian.
        wf = waveform.boundary_points(0.0, amp_ang, params.num_fingers, r_lo, r_hi, kind)
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

    # Chevron tips are acute on a short ring; blunt them to stay DRC-clean even
    # when the user leaves corner_radius at 0 (see _CHEVRON_TIP_RELIEF).
    r_corner = params.corner_radius
    if params.segment_shape == "chevron":
        r_corner = max(r_corner, _CHEVRON_TIP_RELIEF)
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
