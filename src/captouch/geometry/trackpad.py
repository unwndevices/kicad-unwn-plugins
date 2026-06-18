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

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from ..params import TrackpadParams, validate_trackpad
from ._base import ROUND, GeometryError, Point, anchor_point

__all__ = ["Via", "TrackpadNet", "TrackpadGeometry", "build_trackpad"]

#: Polygons below this area (mm²) after clipping are discarded as fab/DRC slivers.
_SLIVER_AREA = 1e-3


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
        """F.Fab documentation shape: the panel rectangle."""
        minx, miny, maxx, maxy = self.bounds
        return [("rect", minx, miny, maxx, maxy)]

    @property
    def courtyard_outline(self) -> tuple:
        """Bounding shape the exporter expands by the courtyard margin."""
        minx, miny, maxx, maxy = self.bounds
        return ("rect", minx, miny, maxx, maxy)

    def symbol_columns(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(left, right)`` pin lists: Rx (sense) on the left, Tx (drive) right."""
        left = [(n.pad_number, n.pin_name) for n in self.rx_nets]
        right = [(n.pad_number, n.pin_name) for n in self.tx_nets]
        return left, right


def _diamond(cx: float, cy: float, d: float) -> Polygon:
    """A rhombus (square rotated 45°) of half-diagonal *d* centred at (cx, cy)."""
    return Polygon([(cx - d, cy), (cx, cy - d), (cx + d, cy), (cx, cy + d)])


def _normalize(geom) -> list[Polygon]:
    """Clip leftovers → a list of non-sliver Polygons (drops empties / lines)."""
    if geom.is_empty:
        return []
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    return [
        g for g in parts
        if isinstance(g, Polygon) and not g.is_empty and g.area >= _SLIVER_AREA
    ]


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
    clip = box(x0, y0, x1, y1)

    nets: list[TrackpadNet] = []

    # -- Rx rows: horizontal, continuous on F.Cu (diamonds + necks) -------- #
    # Ordered top→bottom (KiCad y is down, so row r=0 at y0 is the top row).
    for r in range(R):
        cy = y0 + (r + 0.5) * P
        pieces = [_diamond(x0 + c * P, cy, d) for c in range(C + 1)]
        for c in range(C):
            nx0 = x0 + c * P + d - bw
            nx1 = x0 + (c + 1) * P - d + bw
            pieces.append(box(nx0, cy - bw / 2.0, nx1, cy + bw / 2.0))
        fcu = _normalize(unary_union(pieces).intersection(clip))
        if len(fcu) != 1:
            raise GeometryError(
                f"Rx row {r} did not resolve to one connected polygon "
                f"({len(fcu)} pieces); check bridge_width vs diamond geometry"
            )
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
        diamonds = [_diamond(cx, y0 + k * P, d) for k in range(R + 1)]
        fcu = _normalize(unary_union(diamonds).intersection(clip))
        straps: list[Polygon] = []
        vias: list[Via] = []
        for k in range(R):
            yb = y0 + k * P  # lower diamond centre
            yt = y0 + (k + 1) * P  # upper diamond centre
            v_lo_y = yb + voff  # inside lower diamond, below its top vertex
            v_hi_y = yt - voff  # inside upper diamond, above its bottom vertex
            vias.append(Via((round(cx, ROUND), round(v_lo_y, ROUND))))
            vias.append(Via((round(cx, ROUND), round(v_hi_y, ROUND))))
            straps.append(box(
                cx - bw / 2.0, v_lo_y - via_d / 2.0,
                cx + bw / 2.0, v_hi_y + via_d / 2.0,
            ))
        bcu = _normalize(unary_union(straps).intersection(clip))
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
