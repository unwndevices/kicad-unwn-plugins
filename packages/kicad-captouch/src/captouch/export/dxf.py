"""Export a touch widget's geometry to a DXF drawing for mechanical / CAD handoff.

Direct text emission of an ASCII DXF — the same hand-rolled, dependency-free
approach the project takes for KiCad S-expressions (see :mod:`kicad_core.sexpr`):
the runtime needs only Shapely, no DXF library. The file targets **R12 / AC1009**,
the most broadly readable DXF flavour (LibreCAD, FreeCAD, QCAD, Inkscape, and
AutoCAD all open it), using only ``POLYLINE`` (closed rings) and ``CIRCLE``
entities — the lowest-common-denominator subset every reader supports.

The drawing carries the *same* millimetre geometry the footprint serialises (the
single-source-of-truth model the GUI also previews), organised onto layers that
mirror the footprint's:

* ``F.Cu`` — front copper (electrodes / diamonds / Rx-Tx rows, the guard ring);
* ``B.Cu`` — back copper (trackpad via-bridge straps, the hatched ground pour);
* ``F.Fab`` — the documentation outline;
* ``F.CrtYd`` — the courtyard;
* ``Vias`` — via copper rings and the GND net-tie.

**Y is negated** so the part reads upright in a conventional y-up CAD coordinate
system (KiCad's own board → DXF export flips Y the same way; the geometry and the
footprint are y-down, like the screen). The export is faithful to the previewed
copper, just expressed in the CAD convention.

**No KiCad or Qt imports.** Depends only on the geometry layer (Shapely).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from ..geometry import (
    KeypadGeometry,
    SliderGeometry,
    TrackpadGeometry,
    WheelGeometry,
    build_support,
)
from ..geometry._base import COURTYARD_MARGIN, ROUND, polygon_points, rounded_rect_points
from ..geometry.zones import NETTIE_DIAMETER

#: Any widget geometry the DXF exporter can serialise (duck-typed on ``params``,
#: ``bounds``, ``fab_primitives``, ``courtyard_outline``, and either ``electrodes``
#: or ``nets``). ``MutualSliderGeometry`` is a ``TrackpadGeometry`` subtype.
WidgetGeometry = Union[SliderGeometry, WheelGeometry, TrackpadGeometry, KeypadGeometry]

Point = tuple[float, float]

#: ASCII DXF version token. R12 is the most portable flavour and needs no entity
#: handles, so a hand-written file stays minimal yet opens everywhere.
DXF_VERSION = "AC1009"

#: Layer name -> AutoCAD Color Index (ACI). Only layers that carry geometry are
#: written; this fixes their order and colour when they are. Mirrors the footprint
#: layer set so a CAD user can recognise (and selectively hide) each.
_LAYERS: tuple[tuple[str, int], ...] = (
    ("F.Cu", 2),  # yellow
    ("B.Cu", 4),  # cyan
    ("F.Fab", 8),  # grey
    ("F.CrtYd", 6),  # magenta
    ("Vias", 1),  # red
)
_LAYER_COLOR = dict(_LAYERS)


def _num(v: float) -> str:
    """Format a coordinate as a DXF real (fixed 6 dp; geometry is rounded to 4).

    ``+ 0.0`` normalises a negative zero (which the Y flip produces at ``y == 0``)
    to ``0.000000`` — valid either way, but tidier.
    """
    return f"{float(v) + 0.0:.6f}"


class _Drawing:
    """Accumulates DXF entities (Y-flipped) and renders a complete R12 document.

    Callers pass geometry-space ``(x, y)`` millimetres; this negates Y on the way
    in, tracks the drawing extents, and records which layers are used so the
    header ``$EXTMIN``/``$EXTMAX`` and the ``LAYER`` table come out right.
    """

    def __init__(self) -> None:
        self._tags: list[tuple[int, object]] = []
        self._used: set[str] = set()
        self._minx = self._miny = float("inf")
        self._maxx = self._maxy = float("-inf")

    # -- geometry in (geometry-space mm; Y negated here) -------------------- #
    def polyline(self, points: Sequence[Point], layer: str, *, closed: bool = True) -> None:
        """Add a (closed) polyline ring from ``(x, y)`` vertices."""
        pts = [(x, -y) for (x, y) in points]
        if len(pts) < 2:
            return
        self._used.add(layer)
        self._tags += [
            (0, "POLYLINE"),
            (8, layer),
            (66, 1),  # "vertices follow" — required in R12
            (70, 1 if closed else 0),  # bit 1 = closed
            (10, _num(0.0)),
            (20, _num(0.0)),
            (30, _num(0.0)),
        ]
        for x, y in pts:
            self._tags += [(0, "VERTEX"), (8, layer), (10, _num(x)), (20, _num(y)), (30, _num(0.0))]
            self._grow(x, y)
        self._tags += [(0, "SEQEND"), (8, layer)]

    def circle(self, center: Point, radius: float, layer: str) -> None:
        """Add a circle of *radius* about *center*."""
        cx, cy = center[0], -center[1]
        self._used.add(layer)
        self._tags += [
            (0, "CIRCLE"),
            (8, layer),
            (10, _num(cx)),
            (20, _num(cy)),
            (30, _num(0.0)),
            (40, _num(radius)),
        ]
        self._grow(cx - radius, cy - radius)
        self._grow(cx + radius, cy + radius)

    def _grow(self, x: float, y: float) -> None:
        self._minx, self._miny = min(self._minx, x), min(self._miny, y)
        self._maxx, self._maxy = max(self._maxx, x), max(self._maxy, y)

    # -- serialisation ----------------------------------------------------- #
    def render(self) -> str:
        """Assemble the full DXF text (HEADER + TABLES + ENTITIES + EOF)."""
        if not self._used:  # nothing emitted: keep the extents finite
            self._minx = self._miny = self._maxx = self._maxy = 0.0
        tags: list[tuple[int, object]] = []
        tags += self._header_tags()
        tags += self._tables_tags()
        tags += [(0, "SECTION"), (2, "ENTITIES")]
        tags += self._tags
        tags += [(0, "ENDSEC"), (0, "EOF")]
        return "".join(f"{code}\n{value}\n" for code, value in tags)

    def _header_tags(self) -> list[tuple[int, object]]:
        return [
            (0, "SECTION"),
            (2, "HEADER"),
            (9, "$ACADVER"),
            (1, DXF_VERSION),
            (9, "$INSUNITS"),
            (70, 4),  # 4 = millimetres
            (9, "$MEASUREMENT"),
            (70, 1),  # 1 = metric
            (9, "$EXTMIN"),
            (10, _num(self._minx)),
            (20, _num(self._miny)),
            (9, "$EXTMAX"),
            (10, _num(self._maxx)),
            (20, _num(self._maxy)),
            (0, "ENDSEC"),
        ]

    def _tables_tags(self) -> list[tuple[int, object]]:
        layers = [(name, color) for name, color in _LAYERS if name in self._used]
        tags: list[tuple[int, object]] = [
            (0, "SECTION"),
            (2, "TABLES"),
            (0, "TABLE"),
            (2, "LAYER"),
            (70, len(layers)),
        ]
        for name, color in layers:
            tags += [(0, "LAYER"), (2, name), (70, 0), (62, color), (6, "CONTINUOUS")]
        tags += [(0, "ENDTAB"), (0, "ENDSEC")]
        return tags


def _polygon_rings(poly) -> list[list[Point]]:
    """A shapely polygon's exterior + interior rings as ``(x, y)`` vertex lists."""
    rings = [polygon_points(poly)]
    for interior in poly.interiors:
        coords = list(interior.coords)
        if coords and coords[0] == coords[-1]:
            coords = coords[:-1]
        rings.append([(round(x, ROUND), round(y, ROUND)) for x, y in coords])
    return rings


def _expand_primitive(prim: tuple, margin: float) -> tuple:
    """Grow a ``("rect"|"rrect"|"circle", …)`` outline outward by *margin*."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        return ("rect", x1 - margin, y1 - margin, x2 + margin, y2 + margin)
    if kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        return ("rrect", x1 - margin, y1 - margin, x2 + margin, y2 + margin, r + margin)
    if kind == "circle":
        _, cx, cy, r = prim
        return ("circle", cx, cy, r + margin)
    raise ValueError(f"unknown outline primitive: {prim!r}")


def _add_primitive(dwg: _Drawing, prim: tuple, layer: str) -> None:
    """Draw a ``("rect"|"rrect"|"circle"|"poly", …)`` outline primitive."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        dwg.polyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], layer)
    elif kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        dwg.polyline(rounded_rect_points(x1, y1, x2, y2, r), layer)
    elif kind == "circle":
        _, cx, cy, r = prim
        dwg.circle((cx, cy), r, layer)
    elif kind == "poly":  # a ready-made vertex ring (e.g. a grown support outline)
        dwg.polyline(prim[1], layer)
    else:
        raise ValueError(f"unknown outline primitive: {prim!r}")


def widget_dxf_text(geo: WidgetGeometry) -> str:
    """Serialise any widget's geometry to DXF text (one source of truth, Y-up).

    Handles every widget: an electrode geometry (slider / wheel / keypad — one
    closed ring per electrode on ``F.Cu``) or a trackpad / mutual-cap slider
    (multi-polygon, two-layer copper + via circles). Optional support copper —
    hatched ground (``B.Cu``), guard ring (``F.Cu``), GND net-tie (``Vias``) — and
    the grown fab/courtyard outlines are included exactly as the footprint emits
    them, so the DXF matches the previewed part.
    """
    dwg = _Drawing()
    sc = build_support(geo)

    # Documentation outline (F.Fab) + courtyard (F.CrtYd): the grown support
    # outlines when support copper is present, else the widget's own.
    fab_prims = sc.fab_outlines if sc is not None else geo.fab_primitives
    for prim in fab_prims:
        _add_primitive(dwg, prim, "F.Fab")
    if sc is not None:
        dwg.polyline(sc.courtyard_pts, "F.CrtYd")
    else:
        _add_primitive(dwg, _expand_primitive(geo.courtyard_outline, COURTYARD_MARGIN), "F.CrtYd")

    # Hatched ground pour (B.Cu), drawn under the copper.
    if sc is not None and sc.ground is not None:
        for ring in _polygon_rings(sc.ground):
            dwg.polyline(ring, "B.Cu")

    # Copper. The trackpad spans two layers (F.Cu diamonds + B.Cu straps + vias);
    # slider / wheel / keypad are one F.Cu ring per electrode.
    if isinstance(geo, TrackpadGeometry):
        for net in geo.nets:
            for poly in net.fcu:
                for ring in _polygon_rings(poly):
                    dwg.polyline(ring, "F.Cu")
            for poly in net.bcu:
                for ring in _polygon_rings(poly):
                    dwg.polyline(ring, "B.Cu")
            for via in net.vias:
                dwg.circle(via.at, geo.params.via_diameter / 2.0, "Vias")
    else:
        for e in geo.electrodes:
            dwg.polyline(e.points, "F.Cu")

    # Guard / ESD ring (F.Cu) + the single GND net-tie (Vias), over the copper.
    if sc is not None:
        if sc.guard is not None:
            for ring in _polygon_rings(sc.guard):
                dwg.polyline(ring, "F.Cu")
        _, tie_at = sc.net_tie
        dwg.circle(tie_at, NETTIE_DIAMETER / 2.0, "Vias")

    return dwg.render()


def write_widget_dxf(geo: WidgetGeometry, path: str | Path) -> Path:
    """Write *geo*'s DXF to *path* (UTF-8). Returns the path written."""
    path = Path(path)
    path.write_text(widget_dxf_text(geo), encoding="utf-8")
    return path
