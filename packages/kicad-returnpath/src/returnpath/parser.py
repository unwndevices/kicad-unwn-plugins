"""Board parser — the §3 parser contract.

Reads a ``.kicad_pcb`` with the shared :mod:`kicad_core.sexpr` parser and pulls out
the two things the geometry engine needs: routed **traces** (as Shapely
``LineString``s) and **reference planes** (per-layer unions of a reference net's
``filled_polygon`` islands).

The contract this build pins (validated by the real-board retest, spec §3):

* **Nets are name-based everywhere** — ``(net "GND")``, never ``(net 1)`` and never a
  zone ``(net_name ...)`` child. A board that references nets by *number* (the
  pre-KiCad-10 schema) is **rejected** with :class:`ParserContractError` rather than
  silently parsed to an empty plane and a false "clean" pass.
* **A single zone can span multiple layers** — ``(layers "F.Cu" "In2.Cu" "B.Cu")``.
  The reference plane is selected **per** ``filled_polygon`` **layer**, not per zone.
* **Antipads/thermal reliefs are baked into the island geometry** — the parser takes
  each ``filled_polygon`` verbatim; the clearances are already carved in.

Target baseline: KiCad file version ``20260206`` (KiCad 10).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from kicad_core.sexpr import Node, Sym, find, find_all, head, loads

from .stackup import Stackup, parse_stackup

BASELINE_VERSION = "20260206"


class ParserContractError(Exception):
    """The board violates the §3 parser contract (e.g. pre-KiCad-10 numeric nets)."""


@dataclass(frozen=True)
class Trace:
    """One routed copper ``segment``: a straight run on ``layer`` carrying ``net``."""

    net: str
    layer: str
    width: float
    line: LineString


@dataclass(frozen=True)
class PlaneRef:
    """One reference plane, keyed by ``layer`` **and** ``net``.

    Where :func:`reference_planes` merges every reference net on a layer into a single
    union, a ``PlaneRef`` keeps the net identity — the detector needs it to tell a
    *reference-change* (GND → power along a segment, §4.4) from a clean solid plane.
    ``geom`` is the ``unary_union`` of that net's ``filled_polygon`` islands on that
    layer, antipads baked in (§3).
    """

    layer: str
    net: str
    geom: BaseGeometry


@dataclass(frozen=True)
class Board:
    """The parsed board: version, routed traces, reference planes, stackup, propagation.

    ``planes`` maps a copper layer name to the union of *all* reference nets'
    ``filled_polygon`` islands on that layer (built by :func:`reference_planes`) — the
    skeleton view. ``plane_refs`` is the richer net-identified view (§4) used by the
    four-bucket classifier. ``stackup`` gives physical layer adjacency (§4.3) and
    ``propagation`` holds any declared Track-Propagation references (§4.1), keyed by
    signal-layer name.
    """

    version: str
    traces: tuple[Trace, ...]
    planes: dict[str, BaseGeometry]
    plane_refs: tuple[PlaneRef, ...] = ()
    stackup: Stackup = Stackup(order=())
    propagation: dict[str, tuple[str, ...]] = field(default_factory=dict)
    net_classes: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# atom helpers
# --------------------------------------------------------------------------- #
def _tok(x: Node) -> str:
    return x.name if isinstance(x, Sym) else str(x)


def _num(x: Node) -> float:
    return float(_tok(x))


def _pts(node: Node | None) -> list[tuple[float, float]]:
    pts = find(node, "pts") if node is not None else None
    if pts is None:
        return []
    return [(_num(xy[1]), _num(xy[2])) for xy in find_all(pts, "xy")]


def _string_child(node: Node, name: str) -> str | None:
    """The single **quoted-string** value of child ``name`` — ``(net "GND")`` → ``GND``.

    Returns ``None`` if the child is absent. A *bare* (unquoted) value is the
    pre-KiCad-10 numeric form and is treated as absent here — the schema guard
    rejects it up front, so callers only ever see name-based values.
    """
    child = find(node, name)
    if child is None or len(child) < 2:
        return None
    value = child[1]
    return value if isinstance(value, str) else None


# --------------------------------------------------------------------------- #
# schema guard (§3)
# --------------------------------------------------------------------------- #
def _assert_name_based_schema(board: Node) -> None:
    """Reject a pre-KiCad-10 board before it can masquerade as a clean one.

    The retest failure mode: numeric nets / a zone ``net_name`` child parse to an
    empty reference plane and zero name-matched traces, so every check trivially
    passes. We refuse such a board rather than emit a false "clean" verdict.
    """
    for zone in find_all(board, "zone"):
        if find(zone, "net_name") is not None:
            raise ParserContractError(
                "zone carries a (net_name ...) child — pre-KiCad-10 schema; "
                "this checker targets name-based nets (file version 20260206)"
            )
    # A body net *reference* is `(net "GND")` (one string child). The pre-KiCad-10
    # form is `(net 1)` (one bare/numeric child). The top-level `(net 0 "")`
    # declaration table has two children and is ignored here.
    for holder in (*find_all(board, "segment"), *find_all(board, "via"), *find_all(board, "zone")):
        net = find(holder, "net")
        if net is not None and len(net) == 2 and isinstance(net[1], Sym):
            raise ParserContractError(
                f"net referenced by number ({'(net ' + net[1].name + ')'}) — "
                "pre-KiCad-10 schema; this checker targets name-based nets "
                "(file version 20260206)"
            )


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def parse_board(
    text: str,
    reference_nets: tuple[str, ...] = ("GND",),
    *,
    min_pour_area_mm2: float = 1.0,
) -> Board:
    """Parse ``.kicad_pcb`` *text* into a :class:`Board`, enforcing the §3 contract.

    ``reference_nets`` selects which nets form the reference planes (default GND);
    it must match the set the detector skips, or a non-GND reference net would build
    no plane and every trace against it would falsely read clean. ``min_pour_area_mm2``
    is the §5.2 plane-qualification floor (config-overridable via §6).
    """
    root = loads(text)
    if head(root) != "kicad_pcb":
        raise ParserContractError("not a kicad_pcb file (missing top-level (kicad_pcb ...))")

    _assert_name_based_schema(root)

    version_node = find(root, "version")
    version = _tok(version_node[1]) if version_node and len(version_node) > 1 else "?"

    traces: list[Trace] = []
    for seg in find_all(root, "segment"):
        net = _string_child(seg, "net")
        layer = _string_child(seg, "layer")
        start, end = find(seg, "start"), find(seg, "end")
        width_node = find(seg, "width")
        if net is None or layer is None or start is None or end is None:
            continue
        width = _num(width_node[1]) if width_node and len(width_node) > 1 else 0.0
        line = LineString([(_num(start[1]), _num(start[2])), (_num(end[1]), _num(end[2]))])
        traces.append(Trace(net=net, layer=layer, width=width, line=line))

    planes = reference_planes(root, reference_nets, min_pour_area_mm2=min_pour_area_mm2)
    plane_refs = reference_plane_refs(root, reference_nets, min_pour_area_mm2=min_pour_area_mm2)
    return Board(
        version=version,
        traces=tuple(traces),
        planes=planes,
        plane_refs=plane_refs,
        stackup=parse_stackup(root),
        propagation=parse_propagation(root),
        net_classes=parse_net_classes(root),
    )


def reference_planes(
    board: Node,
    reference_nets: tuple[str, ...],
    *,
    min_pour_area_mm2: float = 1.0,
) -> dict[str, BaseGeometry]:
    """Build one reference plane per copper layer, keyed by layer name.

    A plane is the ``unary_union`` of every reference-net ``filled_polygon`` on that
    layer (§3: selected *per filled_polygon layer*, since one zone spans several).
    Islands are taken **verbatim** — the antipad/thermal clearances are already carved
    in (§3) — and a layer whose reference copper totals less than ``min_pour_area_mm2``
    isn't a plane, so it's omitted (§5.2). Bridging-sliver suppression is a *span*-level
    concern and lives in the detector, not here.
    """
    per_layer: dict[str, list[Polygon]] = {}
    for zone in find_all(board, "zone"):
        if _string_child(zone, "net") not in reference_nets:
            continue
        for fp in find_all(zone, "filled_polygon"):
            layer = _string_child(fp, "layer")
            pts = _pts(fp)
            if layer is None or len(pts) < 3:
                continue
            per_layer.setdefault(layer, []).append(Polygon(pts))

    planes: dict[str, BaseGeometry] = {}
    for layer, polys in per_layer.items():
        union = unary_union(polys)
        if union.area >= min_pour_area_mm2:
            planes[layer] = union
    return planes


def reference_plane_refs(
    board: Node,
    reference_nets: tuple[str, ...],
    *,
    min_pour_area_mm2: float = 1.0,
) -> tuple[PlaneRef, ...]:
    """Build one :class:`PlaneRef` per (layer, reference-net) pour above the area floor.

    Unlike :func:`reference_planes` (which merges every reference net on a layer), this
    keeps GND and a power net on the *same* layer as **separate** planes — the net
    identity the four-bucket classifier needs for reference-change (§4.4). The
    ``min_pour_area_mm2`` floor (§5.2) is applied **per** (layer, net) plane, so a sliver
    power pour is excluded on its own merit even where a large GND plane shares the layer.
    """
    per_key: dict[tuple[str, str], list[Polygon]] = {}
    for zone in find_all(board, "zone"):
        net = _string_child(zone, "net")
        if net is None or net not in reference_nets:
            continue
        for fp in find_all(zone, "filled_polygon"):
            layer = _string_child(fp, "layer")
            pts = _pts(fp)
            if layer is None or len(pts) < 3:
                continue
            per_key.setdefault((layer, net), []).append(Polygon(pts))

    refs: list[PlaneRef] = []
    for (layer, net), polys in per_key.items():
        union = unary_union(polys)
        if union.area >= min_pour_area_mm2:
            refs.append(PlaneRef(layer=layer, net=net, geom=union))
    return tuple(refs)


def parse_propagation(board: Node) -> dict[str, tuple[str, ...]]:
    """Read the declared Track-Propagation references (§4.1), keyed by signal layer.

    KiCad 10 lets a stackup declare a Bottom/Top Reference plane per signal layer. We
    read it from ``(setup (track_propagation (layer "B.Cu" (top_reference "In2.Cu")) …))``
    — folding each layer's ``top_reference`` / ``bottom_reference`` children into the set
    of declared reference-layer names. A layer absent from the table is *silent*: the
    detector falls back to geometric stackup adjacency (§4.3) for it. Geometric coverage
    is re-checked regardless, so a void carved in a *declared* plane is still caught.

    The table is optional; a board without one yields ``{}``.
    """
    setup = find(board, "setup")
    table = find(setup, "track_propagation") if setup is not None else None
    if table is None:
        return {}

    declared: dict[str, tuple[str, ...]] = {}
    for entry in find_all(table, "layer"):
        signal_layer = entry[1] if len(entry) > 1 and isinstance(entry[1], str) else None
        if signal_layer is None:
            continue
        refs: list[str] = []
        for ref_kind in ("top_reference", "bottom_reference"):
            ref_layer = _string_child(entry, ref_kind)
            if ref_layer is not None:
                refs.append(ref_layer)
        if refs:
            declared[signal_layer] = tuple(refs)
    return declared


def parse_net_classes(board: Node) -> dict[str, str]:
    """Map each net to its netclass name from any ``(net_class …)`` blocks (§6.1).

    KiCad boards that carry netclass membership in the ``.kicad_pcb`` do so as
    ``(net_class "HighSpeed" … (add_net "DDR_CLK") …)`` — one block per class, listing its
    member nets. Boards whose membership lives only in the ``.kicad_pro`` project file (the
    KiCad-10 default) yield ``{}``; netclass-keyed exclusion then simply never fires, and
    net-name selection still works. The last block naming a net wins.
    """
    mapping: dict[str, str] = {}
    for block in find_all(board, "net_class"):
        name = block[1] if len(block) > 1 and isinstance(block[1], str) else None
        if name is None:
            continue
        for add in find_all(block, "add_net"):
            net = add[1] if len(add) > 1 and isinstance(add[1], str) else None
            if net is not None:
                mapping[net] = name
    return mapping
