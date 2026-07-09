"""Emit a KiCad footprint (`.kicad_mod`) for a touch widget.

Each electrode is a single **custom-shaped SMD copper pad** on ``F.Cu`` (so it
carries a net and DRC sees it), whose outline is a closed polygon. The pad is
anchored at an interior point of its own copper and its primitive polygon is
emitted relative to that anchor, so the mandatory anchor pad adds no copper
outside the electrode and never shorts neighbouring pads at the origin.

A slider footprint is the electrodes plus a courtyard (``F.CrtYd``) and a
documentation outline (``F.Fab``). Output targets the KiCad 9.0 footprint format
(``version 20241229``), which both KiCad 9 and 10 accept.
"""

from __future__ import annotations

from typing import Sequence, Union

from .. import __version__, sexpr
from ..geometry import (
    KeypadGeometry,
    SliderGeometry,
    SupportCopper,
    TrackpadGeometry,
    WheelGeometry,
    build_support,
)
from ..geometry._base import (
    ANCHOR_RADIUS,
    COURTYARD_MARGIN,
    anchor_point,
    polygon_points,
    rounded_rect_points,
)
from ..geometry.zones import NETTIE_DIAMETER, NETTIE_DRILL
from ..params.support import SupportParams
from ..sexpr import Sym

#: Any widget geometry the exporter can serialise (duck-typed: ``electrodes``,
#: ``bounds``, ``params.name``, ``fab_primitives``, ``courtyard_outline``).
WidgetGeometry = Union[SliderGeometry, WheelGeometry, TrackpadGeometry, KeypadGeometry]
# Widgets whose copper is one custom pad per electrode (slider, wheel, keypad). The
# trackpad's copper spans many polygons per net, so it has its own exporter.
ElectrodeGeometry = Union[SliderGeometry, WheelGeometry, KeypadGeometry]

# KiCad 9.0 footprint/board S-expression format version (date token). KiCad 10
# reads and upgrades it; emitting a newer token would make KiCad 9 reject it.
FOOTPRINT_VERSION = 20241229
GENERATOR = "kicad-captouch"

COURTYARD_WIDTH = 0.05
FAB_WIDTH = 0.1
SILK_WIDTH = 0.12

Point = tuple[float, float]


def _effects(size: float = 1.0, thickness: float = 0.15) -> list:
    return [
        Sym("effects"),
        [Sym("font"), [Sym("size"), size, size], [Sym("thickness"), thickness]],
    ]


def _property(name: str, value: str, at: tuple[float, float, float], layer: str) -> list:
    x, y, rot = at
    return [
        Sym("property"),
        name,
        value,
        [Sym("at"), x, y, rot],
        [Sym("layer"), layer],
        _effects(),
    ]


def _pts(points: Sequence[Point]) -> list:
    return [Sym("pts"), *[[Sym("xy"), x, y] for (x, y) in points]]


def _fp_rect(p1: Point, p2: Point, *, layer: str, width: float) -> list:
    return [
        Sym("fp_rect"),
        [Sym("start"), p1[0], p1[1]],
        [Sym("end"), p2[0], p2[1]],
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_circle(center: Point, radius: float, *, layer: str, width: float) -> list:
    cx, cy = center
    return [
        Sym("fp_circle"),
        [Sym("center"), cx, cy],
        [Sym("end"), round(cx + radius, 6), cy],  # a point on the circle
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_poly(points: Sequence[Point], *, layer: str, width: float, fill: bool = False) -> list:
    return [
        Sym("fp_poly"),
        _pts(points),
        [Sym("stroke"), [Sym("width"), width], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("yes") if fill else Sym("no")],
        [Sym("layer"), layer],
    ]


def _fp_rrect(p1: Point, p2: Point, r: float, *, layer: str, width: float) -> list:
    """A rounded rectangle. KiCad has no filleted-rect primitive, so it is emitted
    as a polyline ``fp_poly`` whose corner arcs come from :func:`rounded_rect_points`."""
    pts = rounded_rect_points(p1[0], p1[1], p2[0], p2[1], r)
    return _fp_poly(pts, layer=layer, width=width)


def _expand_outline(prim: tuple, margin: float) -> tuple:
    """Grow a documentation primitive outward by *margin* (for the courtyard)."""
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


def _emit_outline(prim: tuple, *, layer: str, width: float) -> list:
    """Render a ``("rect"|"rrect"|"circle"|"poly", …)`` primitive on *layer*."""
    kind = prim[0]
    if kind == "rect":
        _, x1, y1, x2, y2 = prim
        return _fp_rect((x1, y1), (x2, y2), layer=layer, width=width)
    if kind == "rrect":
        _, x1, y1, x2, y2, r = prim
        return _fp_rrect((x1, y1), (x2, y2), r, layer=layer, width=width)
    if kind == "circle":
        _, cx, cy, r = prim
        return _fp_circle((cx, cy), r, layer=layer, width=width)
    if kind == "poly":  # a ready-made vertex ring (e.g. a grown support outline)
        return _fp_poly(prim[1], layer=layer, width=width)
    raise ValueError(f"unknown outline primitive: {prim!r}")


def custom_polygon_pad(
    points: Sequence[Point],
    *,
    number: str = "1",
    at: Point = (0.0, 0.0),
    layer: str = "F.Cu",
    anchor: float = 2 * ANCHOR_RADIUS,
) -> list:
    """Build a custom-shape SMD pad from a closed polygon outline.

    *points* are absolute (geometry-space) coordinates; they are emitted relative
    to *at*, which becomes the pad position. *at* must lie inside the polygon.
    """
    if len(points) < 3:
        raise ValueError("a polygon pad needs at least 3 points")
    ax, ay = at
    rel = [(round(x - ax, 6), round(y - ay, 6)) for (x, y) in points]
    return [
        Sym("pad"),
        number,
        Sym("smd"),
        Sym("custom"),
        [Sym("at"), ax, ay],
        [Sym("size"), anchor, anchor],
        [Sym("layers"), layer],
        [Sym("options"), [Sym("clearance"), Sym("outline")], [Sym("anchor"), Sym("circle")]],
        [
            Sym("primitives"),
            [Sym("gr_poly"), _pts(rel), [Sym("width"), 0], [Sym("fill"), Sym("yes")]],
        ],
    ]


def via_pad(
    at: Point,
    *,
    number: str = "1",
    drill: float = 0.3,
    diameter: float = 0.6,
    layers: Sequence[str] = ("*.Cu", "*.Mask"),
) -> list:
    """Build a plated thru-hole via pad that ties F.Cu to B.Cu for one net.

    Used by the trackpad to bridge a Tx column over an Rx neck: a B.Cu strap
    between two such vias carries the link on the back layer. Sharing *number*
    with the net's copper pads makes KiCad treat it as the same net, so the via
    completes the cross-layer connection (verified: DRC reports the net connected
    only when the via is present).
    """
    ax, ay = at
    return [
        Sym("pad"),
        number,
        Sym("thru_hole"),
        Sym("circle"),
        [Sym("at"), ax, ay],
        [Sym("size"), diameter, diameter],
        [Sym("drill"), drill],
        [Sym("layers"), *layers],
        [Sym("remove_unused_layers"), Sym("no")],
    ]


# --------------------------------------------------------------------------- #
# Support copper (Phase 8): hatched ground / guard ring as embedded zones
# --------------------------------------------------------------------------- #
# Emitted as KiCad `zone` objects inside the footprint and tied to a single GND
# net via one thru-hole net-tie pad (+ a GND symbol pin). The zone *outline*,
# net-tie position, and grown fab/courtyard come from geometry/zones.py; KiCad's
# own zone filler does the hatch meshing and clearance-aware fill on the board.
# NOTE: `kicad-cli pcb drc --refill-zones` does not refill footprint-embedded
# zones (only board-level ones), so the DRC tests lift these zones to board level
# to verify fill/clearance/connectivity; `fp export svg` covers "loads in KiCad".
def _zone(
    points: Sequence[Point],
    *,
    layer: str,
    min_thickness: float,
    hatch: tuple[float, float] | None = None,
    connect_clearance: float = 0.25,
) -> list:
    """Build an embedded copper ``zone`` from a closed polygon outline.

    *hatch* ``(line_width, gap)`` makes it a hatched (meshed) pour; ``None`` fills
    solid. Emitted net-less (``net 0`` / ``net_name ""``) — the standard for a
    library footprint zone: KiCad assigns its net when the footprint is placed
    (tie it to the GND pin / net-tie pad's net). A baked ``net_name "GND"`` on a
    ``net 0`` zone segfaults ``kicad-cli fp export svg`` (net-index / net-name
    mismatch with no board net table), so we never bake a name. ``connect_pads
    yes`` gives the net-tie pad a solid (not thermal) connection once tied.
    """
    fill: list = [Sym("fill"), Sym("yes")]
    if hatch is not None:
        fill.append([Sym("mode"), Sym("hatch")])
    fill += [[Sym("thermal_gap"), 0.25], [Sym("thermal_bridge_width"), 0.25]]
    if hatch is not None:
        line_w, gap = hatch
        fill += [
            [Sym("hatch_thickness"), line_w],
            [Sym("hatch_gap"), gap],
            [Sym("hatch_orientation"), 0.0],
            [Sym("smoothing"), Sym("none")],
        ]
    fill += [[Sym("island_removal_mode"), 1], [Sym("island_area_min"), 0.0]]
    return [
        Sym("zone"),
        [Sym("net"), 0],
        [Sym("net_name"), ""],
        [Sym("layer"), layer],
        [Sym("hatch"), Sym("edge"), 0.5],
        [Sym("connect_pads"), Sym("yes"), [Sym("clearance"), connect_clearance]],
        [Sym("min_thickness"), min_thickness],
        fill,
        [Sym("polygon"), _pts(points)],
    ]


def _support_extra_nodes(sc: SupportCopper, params: SupportParams) -> list:
    """Zones + F.Mask aperture + GND net-tie pad for one widget's support copper."""
    nodes: list = []
    # Net-tie pad first (a real component pad → maps to the GND symbol pin). When a
    # hatched ground pour is present the pad must span the mesh pitch — a pad wider
    # than the hatch gap cannot fall entirely between lines, so it always overlaps
    # copper and reliably ties the pour to GND (a smaller pad can land in a gap and
    # leave the pour floating).
    number, at = sc.net_tie
    diameter = (
        max(NETTIE_DIAMETER, params.ground_hatch_pitch) if params.ground_hatch else NETTIE_DIAMETER
    )
    nodes.append(via_pad(at, number=number, drill=NETTIE_DRILL, diameter=diameter))
    if sc.ground is not None:
        gap = round(params.ground_hatch_pitch - params.ground_hatch_width, 6)
        nodes.append(
            _zone(
                polygon_points(sc.ground),
                layer="B.Cu",
                hatch=(params.ground_hatch_width, gap),
                min_thickness=min(0.25, params.ground_hatch_width),
            )
        )
    if sc.guard is not None:
        nodes.append(
            _zone(
                polygon_points(sc.guard),
                layer="F.Cu",
                min_thickness=min(0.25, params.guard_width),
            )
        )
    if sc.mask_open is not None:  # expose the guard ring (no solder mask) — §4.6
        nodes.append(_fp_poly(polygon_points(sc.mask_open), layer="F.Mask", width=0, fill=True))
    return nodes


def _fab_courtyard_nodes(geo: WidgetGeometry, sc: SupportCopper | None) -> tuple[list, list]:
    """The F.Fab outline node(s) + the single F.CrtYd node.

    Without support copper, the widget's own ``fab_primitives`` / ``courtyard_outline``
    (byte-identical to before). With it, the grown outlines that enclose the zones.
    """
    if sc is None:
        fab = [_emit_outline(p, layer="F.Fab", width=FAB_WIDTH) for p in geo.fab_primitives]
        courtyard = _emit_outline(
            _expand_outline(geo.courtyard_outline, COURTYARD_MARGIN),
            layer="F.CrtYd",
            width=COURTYARD_WIDTH,
        )
        return fab, courtyard
    fab = [_emit_outline(p, layer="F.Fab", width=FAB_WIDTH) for p in sc.fab_outlines]
    courtyard = _fp_poly(sc.courtyard_pts, layer="F.CrtYd", width=COURTYARD_WIDTH)
    return fab, courtyard


def _ref_val_y(miny: float, maxy: float, sc: SupportCopper | None) -> tuple[float, float]:
    """Reference (top) / Value (bottom) silk Y positions.

    Without support copper, just outside the electrode extent (unchanged). With it,
    beyond the grown courtyard so the Reference silk never sits over the mask-opened
    guard ring (a ``silk_over_copper`` violation otherwise).
    """
    if sc is None:
        return miny - 1.5, maxy + 1.5
    ys = [y for _, y in sc.courtyard_pts]
    return min(ys) - 1.0, max(ys) + 1.0


def _header(name: str, value: str, ref_at: float, val_at: float) -> list:
    return [
        [Sym("version"), FOOTPRINT_VERSION],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), __version__],
        [Sym("layer"), "F.Cu"],
        _property("Reference", "REF**", (0, ref_at, 0), "F.SilkS"),
        _property("Value", value, (0, val_at, 0), "F.Fab"),
        [Sym("attr"), Sym("smd")],
    ]


# --------------------------------------------------------------------------- #
# Emit-time structural validation
# --------------------------------------------------------------------------- #
class FootprintError(ValueError):
    """Raised when an assembled footprint node is structurally malformed."""


def _validate_pad(pad: list) -> None:
    kids = sexpr.children(pad)
    num = kids[0] if kids else None
    if not isinstance(num, str) or not num:
        raise FootprintError(f"pad needs a string number, got {num!r}")
    for token in ("at", "layers"):
        if sexpr.find(pad, token) is None:
            raise FootprintError(f"pad {num!r} missing ({token} …)")
    # A custom (polygon) pad must carry a polygon of at least 3 points.
    prims = sexpr.find(pad, "primitives")
    if prims is not None:
        gr_poly = sexpr.find(prims, "gr_poly")
        pts = sexpr.find(gr_poly, "pts") if gr_poly is not None else None
        n = len(sexpr.find_all(pts, "xy")) if pts is not None else 0
        if n < 3:
            raise FootprintError(f"pad {num!r} polygon has {n} point(s), need >= 3")


def _validate_zone(zone: list) -> None:
    for token in ("layer", "polygon"):
        if sexpr.find(zone, token) is None:
            raise FootprintError(f"zone missing ({token} …)")
    poly = sexpr.find(zone, "polygon")
    pts = sexpr.find(poly, "pts") if poly is not None else None
    n = len(sexpr.find_all(pts, "xy")) if pts is not None else 0
    if n < 3:
        raise FootprintError(f"zone polygon has {n} point(s), need >= 3")


def validate_footprint(node: list) -> list:
    """Check *node* is a well-formed footprint before serialisation.

    A guard against emitter bugs: rather than write a malformed ``.kicad_mod``
    that only fails when KiCad opens it, fail loudly here. Returns *node*
    unchanged so it can be used inline.
    """
    if sexpr.head(node) != "footprint":
        raise FootprintError(f"footprint must start with 'footprint', got {sexpr.head(node)!r}")
    kids = sexpr.children(node)
    if not kids or not isinstance(kids[0], str) or not kids[0]:
        raise FootprintError("footprint needs a non-empty name as its first element")
    for token in ("version", "generator"):
        if sexpr.find(node, token) is None:
            raise FootprintError(f"footprint missing ({token} …)")
    pads = sexpr.find_all(node, "pad")
    if not pads:
        raise FootprintError("footprint has no pads")
    for pad in pads:
        _validate_pad(pad)
    for zone in sexpr.find_all(node, "zone"):  # optional support-copper zones
        _validate_zone(zone)
    return node


def _serialize_footprint(node: list) -> str:
    """Validate then serialise a footprint node to text (trailing newline)."""
    return sexpr.dumps(validate_footprint(node)) + "\n"


# --------------------------------------------------------------------------- #
# Phase 0 spike: a single electrode from one polygon (kept for the format gate)
# --------------------------------------------------------------------------- #
def electrode_footprint(name: str, polygon: Sequence[Point], *, value: str | None = None) -> list:
    """Build a footprint node containing a single custom-polygon electrode pad."""
    return [
        Sym("footprint"),
        name,
        *_header(name, value or name, -1, 1),
        custom_polygon_pad(polygon, number="1"),
        [Sym("embedded_fonts"), Sym("no")],
    ]


def footprint_text(name: str, polygon: Sequence[Point], *, value: str | None = None) -> str:
    """Serialise an electrode footprint to `.kicad_mod` text (trailing newline)."""
    return _serialize_footprint(electrode_footprint(name, polygon, value=value))


# --------------------------------------------------------------------------- #
# Widget footprint: one custom pad per electrode + courtyard + fab outline
# --------------------------------------------------------------------------- #
def widget_footprint(geo: ElectrodeGeometry) -> list:
    """Build a footprint node for any widget (slider, wheel, …) from its geometry.

    The documentation outline (``F.Fab``) and courtyard (``F.CrtYd``) come from
    the geometry's own ``fab_primitives`` / ``courtyard_outline`` (rectangles for
    a slider, circles for a wheel), so each widget draws the right shape while the
    pad/courtyard machinery stays shared.
    """
    name = geo.params.name
    minx, miny, maxx, maxy = geo.bounds
    sc = build_support(geo)
    ref_y, val_y = _ref_val_y(miny, maxy, sc)
    fab, courtyard = _fab_courtyard_nodes(geo, sc)
    pads = [custom_polygon_pad(e.points, number=e.pad_number, at=e.anchor) for e in geo.electrodes]
    extra = _support_extra_nodes(sc, geo.params) if sc is not None else []

    return [
        Sym("footprint"),
        name,
        *_header(name, name, ref_y, val_y),
        *fab,
        courtyard,
        *pads,
        *extra,
        [Sym("embedded_fonts"), Sym("no")],
    ]


def widget_footprint_text(geo: ElectrodeGeometry) -> str:
    """Serialise any widget footprint to `.kicad_mod` text (trailing newline)."""
    return _serialize_footprint(widget_footprint(geo))


# Backwards-compatible / explicit per-widget aliases.
def slider_footprint(geo: SliderGeometry) -> list:
    """Build a slider footprint node (see :func:`widget_footprint`)."""
    return widget_footprint(geo)


def slider_footprint_text(geo: SliderGeometry) -> str:
    """Serialise a slider footprint to `.kicad_mod` text (trailing newline)."""
    return widget_footprint_text(geo)


def wheel_footprint(geo: WheelGeometry) -> list:
    """Build a wheel footprint node (see :func:`widget_footprint`)."""
    return widget_footprint(geo)


def wheel_footprint_text(geo: WheelGeometry) -> str:
    """Serialise a wheel footprint to `.kicad_mod` text (trailing newline)."""
    return widget_footprint_text(geo)


# A keypad is one custom pad per button electrode (an ElectrodeGeometry), so its
# footprint is emitted by the shared electrode path; these aliases just read clearly.
def keypad_footprint(geo: KeypadGeometry) -> list:
    """Build a keypad footprint node (see :func:`widget_footprint`)."""
    return widget_footprint(geo)


def keypad_footprint_text(geo: KeypadGeometry) -> str:
    """Serialise a keypad footprint to `.kicad_mod` text (trailing newline)."""
    return widget_footprint_text(geo)


# --------------------------------------------------------------------------- #
# Trackpad footprint: a two-layer diamond matrix with via bridges
# --------------------------------------------------------------------------- #
# A trackpad net (Rx row / Tx column) spans many polygons across two layers, so
# it cannot use the one-pad-per-electrode `widget_footprint`. Each net emits one
# custom pad per F.Cu piece, one per B.Cu strap, and one thru-hole via pad per
# bridge — all sharing the net's pad number, so KiCad reads them as one net and
# the vias complete the cross-layer connection.
def trackpad_footprint(geo: TrackpadGeometry) -> list:
    """Build a footprint node for a trackpad from its :class:`TrackpadGeometry`."""
    name = geo.params.name
    minx, miny, maxx, maxy = geo.bounds
    p = geo.params

    sc = build_support(geo)
    ref_y, val_y = _ref_val_y(miny, maxy, sc)
    fab, courtyard = _fab_courtyard_nodes(geo, sc)

    pads: list = []
    for net in geo.nets:
        for poly in net.fcu:
            pts = polygon_points(poly)
            pads.append(
                custom_polygon_pad(pts, number=net.pad_number, at=anchor_point(poly), layer="F.Cu")
            )
        for poly in net.bcu:
            pts = polygon_points(poly)
            pads.append(
                custom_polygon_pad(pts, number=net.pad_number, at=anchor_point(poly), layer="B.Cu")
            )
        for via in net.vias:
            pads.append(
                via_pad(via.at, number=net.pad_number, drill=p.via_drill, diameter=p.via_diameter)
            )

    extra = _support_extra_nodes(sc, geo.params) if sc is not None else []

    return [
        Sym("footprint"),
        name,
        *_header(name, name, ref_y, val_y),
        *fab,
        courtyard,
        *pads,
        *extra,
        [Sym("embedded_fonts"), Sym("no")],
    ]


def trackpad_footprint_text(geo: TrackpadGeometry) -> str:
    """Serialise a trackpad footprint to `.kicad_mod` text (trailing newline)."""
    return _serialize_footprint(trackpad_footprint(geo))


# A mutual-cap slider is a 1-row trackpad (its geometry is a TrackpadGeometry), so
# its footprint is emitted by the trackpad path; these aliases just read clearly.
def mutual_slider_footprint(geo: TrackpadGeometry) -> list:
    """Build a mutual-cap slider footprint node (see :func:`trackpad_footprint`)."""
    return trackpad_footprint(geo)


def mutual_slider_footprint_text(geo: TrackpadGeometry) -> str:
    """Serialise a mutual-cap slider footprint to `.kicad_mod` text (trailing newline)."""
    return trackpad_footprint_text(geo)
