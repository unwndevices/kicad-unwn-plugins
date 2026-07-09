"""Build slider electrode polygons from :class:`SliderParams`.

Construction (single source of truth for both exporters and the GUI preview):

1. Lay ``M = num_segments + 2*end_dummies`` segment cells of width ``W`` edge to
   edge, separated by gap ``A`` (centre pitch ``W + A``), centred on the origin.
2. For each of the ``M-1`` inter-segment boundaries, build a waveform polyline
   (straight / triangle / square per shape) and buffer it by ``A/2`` into a
   uniform-width "gap strip". Round joins give the gap rounded corners — the ESD
   relief vendors recommend (guidelines section 2.2 / 5.8) — for free.
3. Subtract the union of the strips from the slider rectangle. The result is
   exactly ``M`` interlocking electrodes, each separated from its neighbours by
   ``A`` everywhere.

The gap is therefore guaranteed uniform (it is an offset of the boundary),
sidestepping the variable clearance a naive horizontal shift would produce.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, box
from shapely.ops import unary_union

from ..params import SliderParams, validate_slider
from . import waveform
from ._base import (
    ANCHOR_RADIUS,
    ARC_QUAD_SEGS,
    ROUND,
    SHAPE_TO_KIND,
    Electrode,
    GeometryError,
    anchor_point,
    round_corners,
    tip_relief_radius,
)

__all__ = ["Electrode", "SliderGeometry", "build_slider", "GeometryError", "ANCHOR_RADIUS"]


@dataclass(frozen=True)
class SliderGeometry:
    """The complete geometric model of a slider."""

    electrodes: list[Electrode]
    bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    params: SliderParams

    @property
    def active(self) -> list[Electrode]:
        return [e for e in self.electrodes if e.role == "active"]

    @property
    def dummies(self) -> list[Electrode]:
        return [e for e in self.electrodes if e.role == "dummy"]

    # -- documentation outline (shared exporter / preview, see export module) - #
    @property
    def fab_primitives(self) -> list[tuple]:
        """F.Fab documentation shapes: the bounding rectangle."""
        minx, miny, maxx, maxy = self.bounds
        return [("rect", minx, miny, maxx, maxy)]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin."""
        minx, miny, maxx, maxy = self.bounds
        return ("rect", minx, miny, maxx, maxy)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin ``(number, name)`` lists: active left, GND right."""
        left = [(e.pad_number, e.pin_name) for e in self.active]
        right = [(e.pad_number, e.pin_name) for e in self.dummies]
        return left, right


def _role_and_naming(params: SliderParams) -> list[tuple[str, str, str]]:
    """Return ``(role, pad_number, pin_name)`` per physical segment, left to right.

    Active electrodes take pad numbers ``1..N`` and pin names ``E1..EN``; end
    dummies take the following numbers and are all named ``GND``.
    """
    n = params.num_segments
    d = params.end_dummies
    m = params.num_physical_segments

    out: list[tuple[str, str, str]] = []
    active_idx = 0
    dummy_idx = 0
    for s in range(m):
        is_active = d <= s < d + n
        if is_active:
            active_idx += 1
            out.append(("active", str(active_idx), f"E{active_idx}"))
        else:
            dummy_idx += 1
            out.append(("dummy", str(n + dummy_idx), "GND"))
    return out


def build_slider(params: SliderParams) -> SliderGeometry:
    """Build a :class:`SliderGeometry` from validated *params*."""
    validate_slider(params)

    w = params.width
    a = params.air_gap
    h = params.segment_height
    m = params.num_physical_segments
    amp = params.amplitude
    kind = SHAPE_TO_KIND[params.segment_shape]

    total = params.total_length
    x_off = -total / 2.0  # centre the slider on the origin
    rect = box(x_off, -h / 2.0, x_off + total, h / 2.0)

    # Inter-segment boundaries, buffered into uniform gap strips.
    ext = a  # extend boundaries past the rectangle so strips cut cleanly
    strips = []
    for k in range(m - 1):
        x_nom = x_off + (k + 1) * (w + a) - a / 2.0
        pts = waveform.boundary_points(
            x_nom, amp, params.num_fingers, -h / 2.0 - ext, h / 2.0 + ext, kind
        )
        strip = LineString(pts).buffer(
            a / 2.0, cap_style="flat", join_style="round", quad_segs=ARC_QUAD_SEGS
        )
        strips.append(strip)

    copper = rect.difference(unary_union(strips)) if strips else rect

    parts = list(copper.geoms) if isinstance(copper, MultiPolygon) else [copper]
    if len(parts) != m:
        raise GeometryError(
            f"expected {m} segments but geometry produced {len(parts)}; "
            f"reduce tooth_depth (must stay below W/2 = {w / 2.0:.3f} mm)"
        )
    parts.sort(key=lambda g: g.centroid.x)

    # Round convex corners: chevron tips get at least tip_radius; other shapes
    # use only corner_radius (see tip_relief_radius).
    r_corner = tip_relief_radius(params.segment_shape, params.corner_radius, params.tip_radius)
    parts = round_corners(parts, r_corner)

    naming = _role_and_naming(params)
    electrodes = [
        Electrode(
            polygon=poly,
            pad_number=num,
            pin_name=name,
            role=role,
            anchor=anchor_point(poly),
        )
        for poly, (role, num, name) in zip(parts, naming)
    ]

    union = unary_union(parts)
    minx, miny, maxx, maxy = union.bounds
    bounds = (round(minx, ROUND), round(miny, ROUND), round(maxx, ROUND), round(maxy, ROUND))
    return SliderGeometry(electrodes=electrodes, bounds=bounds, params=params)
