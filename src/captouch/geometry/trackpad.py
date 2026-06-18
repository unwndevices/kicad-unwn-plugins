"""Build mutual-cap XY diamond trackpad geometry from :class:`TrackpadParams`.

Two interlocking diamond sub-lattices, offset by half a pitch on both axes, tile
the panel rectangle (see ``params/trackpad.py`` for the topology and the numbers):

1. **Rx rows** (horizontal, *continuous* on F.Cu): per row, diamonds centred at
   ``(x0 + c·P, y)`` for ``c = 0..C`` (the two end ones halved by the panel edge)
   joined edge-to-edge by F.Cu **necks** → one connected F.Cu polygon per row.
2. **Tx columns** (vertical, *bridged* on B.Cu): per column, diamonds centred at
   ``(x, y0 + k·P)`` for ``k = 0..R`` (ends halved). On F.Cu these stay separate
   islands; each consecutive pair is linked by a **B.Cu strap between two
   thru-hole vias** that hops over the Rx neck crossing it.

A net (one Rx or Tx line) is therefore multi-polygon and, for Tx, multi-layer —
which is why the trackpad uses its own :class:`TrackpadNet` rather than the
single-polygon :class:`~captouch.geometry._base.Electrode`. The diamond
half-diagonal ``d = (P − A·√2)/2`` makes every Rx/Tx facing-edge gap exactly the
nominal ``A``; the connecting necks pinch tighter (~``A/√2``), as in any diamond
pattern, which is why the DRC gate is the real correctness check.

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import MultiPolygon, Point as GeoPoint, Polygon, box
from shapely.ops import unary_union

from ..params import TrackpadError, TrackpadParams, validate_trackpad
from ._base import ARC_QUAD_SEGS, ROUND, GeometryError, Point, anchor_point

__all__ = ["Via", "TrackpadNet", "TrackpadGeometry", "build_trackpad"]

#: Polygons below this area (mm²) after clipping are discarded as fab/DRC slivers.
_SLIVER_AREA = 1e-3

#: Quarter-circle segments for the curved mask boundary (disk / rounded-rect
#: clip). Finer than the lean pad fillets so the clipped copper edge and the
#: F.Fab outline read as smooth curves, not coarse facets.
_CLIP_QUAD_SEGS = 16


@dataclass(frozen=True)
class Via:
    """A plated thru-hole that ties a net's F.Cu copper to its B.Cu strap."""

    at: Point


@dataclass(frozen=True)
class TrackpadNet:
    """One electrode line (an Rx row or a Tx column) and how it maps to a pad/pin.

    A line is one net: all its copper shares ``pad_number`` and one symbol pin.
    """

    pad_number: str
    pin_name: str  # "Rx1".."RxR" / "Tx1".."TxC"
    role: str  # "rx" | "tx"
    fcu: list[Polygon]  # F.Cu copper (diamonds, + necks for Rx)
    bcu: list[Polygon] = field(default_factory=list)  # B.Cu straps (Tx only)
    vias: list[Via] = field(default_factory=list)  # thru-hole bridges (Tx only)
    anchor: Point = (0.0, 0.0)  # interior point of the largest F.Cu piece


@dataclass(frozen=True)
class TrackpadGeometry:
    """The complete geometric model of a trackpad."""

    nets: list[TrackpadNet]
    bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)
    params: TrackpadParams

    @property
    def rx_nets(self) -> list[TrackpadNet]:
        return [n for n in self.nets if n.role == "rx"]

    @property
    def tx_nets(self) -> list[TrackpadNet]:
        return [n for n in self.nets if n.role == "tx"]

    # -- documentation outline (shared exporter / preview) ----------------- #
    @property
    def fab_primitives(self) -> list[tuple]:
        """F.Fab documentation shape, following the configured ``mask_shape``."""
        return [self._mask_outline()]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin.

        Follows ``mask_shape`` (the same outline as F.Fab): now that the copper is
        clipped to the mask, a shaped courtyard bounds it tightly. The expanded
        outline still encloses all copper — the circle uses the nominal mask
        radius, which the clipped diamonds never exceed.
        """
        return self._mask_outline()

    def _mask_outline(self) -> tuple:
        """The mask outline primitive (``rect`` / ``rrect`` / ``circle``)."""
        minx, miny, maxx, maxy = self.bounds
        shape = self.params.mask_shape
        if shape == "circle":
            return ("circle", 0.0, 0.0, round(self.params.effective_radius, ROUND))
        if shape == "rrect":
            return ("rrect", minx, miny, maxx, maxy,
                    round(self.params.corner_radius, ROUND))
        return ("rect", minx, miny, maxx, maxy)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin lists: Rx (sense) on the left, Tx (drive) right."""
        left = [(n.pad_number, n.pin_name) for n in self.rx_nets]
        right = [(n.pad_number, n.pin_name) for n in self.tx_nets]
        return left, right


def _diamond(cx: float, cy: float, d: float) -> Polygon:
    """A rhombus (square rotated 45°) of half-diagonal *d* centred at (cx, cy)."""
    return Polygon([(cx - d, cy), (cx, cy - d), (cx + d, cy), (cx, cy + d)])


def _normalize(geom, min_width: float = 0.0) -> list[Polygon]:
    """Clip leftovers → a list of non-sliver Polygons (drops empties / lines).

    With ``min_width > 0`` each surviving part is also morphologically *opened*
    (erode then dilate by ``min_width/2``): a fragment thinner than ``min_width``
    everywhere vanishes, and acute tips/crescents left where a curved mask grazes
    a diamond are trimmed back to ``min_width`` — the area filter alone keeps such
    tips. ``min_width == 0`` (the rect mask) is the original behaviour exactly.
    """
    if geom.is_empty:
        return []
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    out: list[Polygon] = []
    for g in parts:
        if not (isinstance(g, Polygon) and not g.is_empty and g.area >= _SLIVER_AREA):
            continue
        if min_width > 0:
            out.extend(_open_or_drop(g, min_width))
        else:
            out.append(g)
    return out


def _open_or_drop(g: Polygon, w: float) -> list[Polygon]:
    """Morphologically open *g* by ``w/2``; return the non-sliver pieces (possibly
    none, or several if the open severs a thin waist)."""
    opened = g.buffer(-w / 2.0, quad_segs=ARC_QUAD_SEGS).buffer(w / 2.0, quad_segs=ARC_QUAD_SEGS)
    if opened.is_empty:
        return []
    pieces = list(opened.geoms) if isinstance(opened, MultiPolygon) else [opened]
    return [p for p in pieces if isinstance(p, Polygon) and p.area >= _SLIVER_AREA]


def _mask_clip(params: TrackpadParams, x0: float, y0: float, x1: float, y1: float):
    """The Shapely region the diamond lattice is intersected with, per ``mask_shape``.

    ``rect`` is the exact panel box (so rect output is byte-identical). ``rrect``
    is that box with ``corner_radius`` fillets. ``circle`` is a disk *inset* by
    ``min_feature/2`` from :attr:`effective_radius`, so the boundary never cuts a
    diamond thinner than the fab minimum.
    """
    shape = params.mask_shape
    if shape == "circle":
        r_eff = params.effective_radius - params.min_feature / 2.0
        return GeoPoint(0.0, 0.0).buffer(r_eff, quad_segs=_CLIP_QUAD_SEGS)
    if shape == "rrect":
        cr = params.corner_radius
        return box(x0 + cr, y0 + cr, x1 - cr, y1 - cr).buffer(
            cr, quad_segs=_CLIP_QUAD_SEGS, join_style="round")
    return box(x0, y0, x1, y1)


def build_trackpad(params: TrackpadParams) -> TrackpadGeometry:
    """Build a :class:`TrackpadGeometry` from validated *params*."""
    validate_trackpad(params)

    P = params.diamond_pitch
    d = params.half_diag
    bw = params.bridge_width
    R = params.num_rows
    C = params.num_cols
    via_d = params.via_diameter
    voff = d - via_d  # via centre offset from a diamond centre toward its vertex

    W = C * P
    H = R * P
    x0, y0 = -W / 2.0, -H / 2.0
    x1, y1 = W / 2.0, H / 2.0
    clip = _mask_clip(params, x0, y0, x1, y1)
    # A curved mask (circle/rrect) leaves thin tips where it grazes a diamond; the
    # rect mask cuts only clean half-diamonds and must stay byte-identical, so its
    # min-width guard is disabled (0).
    min_w = 0.0 if params.mask_shape == "rect" else params.min_feature

    # A diamond joins the pad only when its *centre* is inside the mask. This keeps
    # every surviving diamond at least ~half-present — enough to carry a bridge via
    # and to bridge contiguously to its neighbour — instead of leaving thin partial
    # fragments that float unconnected or crowd the perpendicular axis. The kept
    # diamonds are still clipped to the mask, so the copper boundary follows the
    # curve. For the rect mask every centre (incl. the edge half-diamonds, whose
    # centres lie on the panel edge) is inside, so the lattice is unchanged.
    def _inside(px: float, py: float) -> bool:
        return clip.covers(GeoPoint(px, py))

    nets: list[TrackpadNet] = []

    # -- Rx rows: horizontal, continuous on F.Cu (diamonds + necks) -------- #
    # Ordered top→bottom (KiCad y is down, so row r=0 at y0 is the top row).
    for r in range(R):
        cy = y0 + (r + 0.5) * P
        kept = {c for c in range(C + 1) if _inside(x0 + c * P, cy)}
        if not kept:
            raise TrackpadError(
                f"Rx row {r + 1} lies entirely outside the {params.mask_shape} mask "
                f"— use a larger radius or a more square matrix (num_rows ≈ num_cols)"
            )
        pieces = [_diamond(x0 + c * P, cy, d) for c in sorted(kept)]
        for c in range(C):  # neck only between two kept, adjacent diamonds
            if c in kept and c + 1 in kept:
                nx0 = x0 + c * P + d - bw
                nx1 = x0 + (c + 1) * P - d + bw
                pieces.append(box(nx0, cy - bw / 2.0, nx1, cy + bw / 2.0))
        fcu = _normalize(unary_union(pieces).intersection(clip), min_w)
        if params.mask_shape == "rect":
            if len(fcu) != 1:
                raise GeometryError(
                    f"Rx row {r} did not resolve to one connected polygon "
                    f"({len(fcu)} pieces); check bridge_width vs diamond geometry"
                )
        elif len(fcu) > 1:
            # A curved mask can still sever a boundary neck pinched by the open;
            # an Rx net is one galvanic F.Cu piece (no straps), so a detached arc
            # would be floating copper (ST AN2869). Keep the largest (the row
            # centreline) and drop the islands.
            fcu = [max(fcu, key=lambda g: g.area)]
        nets.append(TrackpadNet(
            pad_number=str(r + 1),
            pin_name=f"Rx{r + 1}",
            role="rx",
            fcu=fcu,
            anchor=anchor_point(max(fcu, key=lambda g: g.area)),
        ))

    # -- Tx columns: vertical, bridged on B.Cu (diamonds + straps + vias) -- #
    # Ordered left→right; pad numbers continue after the Rx rows.
    for c in range(C):
        cx = x0 + (c + 0.5) * P
        kept = {k for k in range(R + 1) if _inside(cx, y0 + k * P)}
        if not kept:
            raise TrackpadError(
                f"Tx column {c + 1} lies entirely outside the {params.mask_shape} mask "
                f"— use a larger radius or a more square matrix (num_rows ≈ num_cols)"
            )
        diamonds = [_diamond(cx, y0 + k * P, d) for k in sorted(kept)]
        fcu = _normalize(unary_union(diamonds).intersection(clip), min_w)
        straps: list[Polygon] = []
        vias: list[Via] = []
        for k in range(R):  # bridge only between two kept, adjacent diamonds
            if k not in kept or k + 1 not in kept:
                continue
            v_lo_y = y0 + k * P + voff  # inside lower diamond, below its top vertex
            v_hi_y = y0 + (k + 1) * P - voff  # inside upper diamond, above its bottom vertex
            vias.append(Via((round(cx, ROUND), round(v_lo_y, ROUND))))
            vias.append(Via((round(cx, ROUND), round(v_hi_y, ROUND))))
            straps.append(box(
                cx - bw / 2.0, v_lo_y - via_d / 2.0,
                cx + bw / 2.0, v_hi_y + via_d / 2.0,
            ))
        bcu = _normalize(unary_union(straps).intersection(clip), min_w) if straps else []
        nets.append(TrackpadNet(
            pad_number=str(R + c + 1),
            pin_name=f"Tx{c + 1}",
            role="tx",
            fcu=fcu,
            bcu=bcu,
            vias=vias,
            anchor=anchor_point(max(fcu, key=lambda g: g.area)),
        ))

    all_copper = unary_union(
        [g for n in nets for g in n.fcu] + [g for n in nets for g in n.bcu]
    )
    minx, miny, maxx, maxy = all_copper.bounds
    bounds = (round(minx, ROUND), round(miny, ROUND), round(maxx, ROUND), round(maxy, ROUND))
    return TrackpadGeometry(nets=nets, bounds=bounds, params=params)
