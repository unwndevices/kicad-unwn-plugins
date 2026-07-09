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

from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from kicad_core.sexpr import Node, Sym, find, find_all, head, loads

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
class Board:
    """The parsed board: its file version, routed traces, and per-layer planes.

    ``planes`` maps a copper layer name to the union of a reference net's
    ``filled_polygon`` islands on that layer (built by :func:`reference_planes`).
    """

    version: str
    traces: tuple[Trace, ...]
    planes: dict[str, BaseGeometry]


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
def parse_board(text: str, reference_nets: tuple[str, ...] = ("GND",)) -> Board:
    """Parse ``.kicad_pcb`` *text* into a :class:`Board`, enforcing the §3 contract.

    ``reference_nets`` selects which nets form the reference planes (default GND);
    it must match the set the detector skips, or a non-GND reference net would build
    no plane and every trace against it would falsely read clean.
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

    planes = reference_planes(root, reference_nets)
    return Board(version=version, traces=tuple(traces), planes=planes)


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
