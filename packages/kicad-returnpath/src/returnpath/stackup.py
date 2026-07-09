"""Board stackup — the physical copper-layer order and adjacency (spec §4.3).

The reference plane for a trace lives on an **immediate stackup neighbour** — the
copper layer directly above or below the trace's own layer. This module reads the
board's ``(layers ...)`` declaration into that physical order so the detector can ask
"what copper is adjacent to a ``B.Cu`` trace?" (answer: the layer just above it).

KiCad numbers copper layers ``F.Cu`` = 0, ``In1.Cu`` … ``In30.Cu`` = 1 … 30, and
``B.Cu`` = 31, so sorting the copper entries by that ordinal yields the top→bottom
stack. Outer layers (``F.Cu`` / ``B.Cu``) have a single neighbour → **microstrip**;
an inner layer between two planes has two → **stripline** (§4.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from kicad_core.sexpr import Node, Sym, children, find, find_all

# Copper-layer types in a KiCad `(layers …)` block. `user`/`Edge.Cuts` are excluded.
_COPPER_TYPES = {"signal", "power", "mixed", "jumper"}


def _tok(x: Node) -> str:
    return x.name if isinstance(x, Sym) else str(x)


@dataclass(frozen=True)
class PhysicalLayer:
    """One entry of the physical build (a copper foil or a dielectric sub-layer).

    Read from ``(setup (stackup …))`` in board order (top → bottom). ``thickness`` is in
    millimetres; ``is_copper`` marks a copper foil (``*.Cu``) versus a dielectric.
    """

    name: str
    thickness: float
    is_copper: bool


@dataclass(frozen=True)
class Stackup:
    """The board's copper layers in physical order (top ``F.Cu`` → bottom ``B.Cu``).

    ``order`` is the copper-only sequence (from ``(layers …)``); ``build`` is the fuller
    physical stack including dielectric sub-layers with thicknesses (from
    ``(setup (stackup …))``), used to derive the per-trace dielectric height ``H`` for the
    §5.2 edge-clearance formula. ``build`` is empty when the board declares no stackup.
    """

    order: tuple[str, ...]
    build: tuple[PhysicalLayer, ...] = ()

    def __contains__(self, layer: str) -> bool:
        return layer in self.order

    def neighbours(self, layer: str) -> tuple[str | None, str | None]:
        """Return ``(above, below)`` copper-layer names for *layer* (``None`` at an edge).

        ``above`` is the layer one step toward ``F.Cu``; ``below`` one step toward
        ``B.Cu``. A layer not in the stack (or with no stack at all) returns
        ``(None, None)`` — the detector then falls back to its non-stackup rule.
        """
        try:
            i = self.order.index(layer)
        except ValueError:
            return (None, None)
        above = self.order[i - 1] if i > 0 else None
        below = self.order[i + 1] if i < len(self.order) - 1 else None
        return (above, below)

    def dielectric_height(self, layer_a: str, layer_b: str) -> float | None:
        """Dielectric height ``H`` between two copper layers, in mm (``None`` if unknown).

        Sums the thickness of every dielectric sub-layer physically **between** the two
        copper foils (§5.2: "H = dielectric height to the reference plane, from the
        stackup"). Returns ``None`` when the board carries no ``(setup (stackup …))`` build
        or either layer is absent — the edge-clearance formula then simply drops its ``3H``
        term and floors on ``max(90 mil, 1×W)``.
        """
        if not self.build:
            return None
        indices = {pl.name: i for i, pl in enumerate(self.build) if pl.is_copper}
        ia, ib = indices.get(layer_a), indices.get(layer_b)
        if ia is None or ib is None:
            return None
        lo, hi = (ia, ib) if ia < ib else (ib, ia)
        return sum(pl.thickness for pl in self.build[lo + 1 : hi] if not pl.is_copper)


def parse_stackup(board: Node) -> Stackup:
    """Build the :class:`Stackup` from a ``.kicad_pcb`` root node.

    Reads ``(layers (0 "F.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal) …)``,
    keeps the copper entries (``F.Cu`` / ``In*.Cu`` / ``B.Cu`` with a copper type),
    and orders them by their canonical KiCad ordinal. A board without a ``(layers …)``
    section (e.g. a minimal inline fixture) yields an empty stackup. The dielectric
    ``build`` is read separately from ``(setup (stackup …))`` when present.
    """
    build = _parse_build(board)
    layers_node = find(board, "layers")
    if layers_node is None:
        return Stackup(order=(), build=build)

    ordered: list[tuple[int, str]] = []
    for entry in children(layers_node):
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        ordinal, name, kind = entry[0], entry[1], entry[2]
        if not isinstance(name, str) or not name.endswith(".Cu"):
            continue
        if _tok(kind) not in _COPPER_TYPES:
            continue
        try:
            ordered.append((int(_tok(ordinal)), name))
        except ValueError:
            continue

    ordered.sort(key=lambda pair: pair[0])
    return Stackup(order=tuple(name for _, name in ordered), build=build)


def _parse_build(board: Node) -> tuple[PhysicalLayer, ...]:
    """Read the physical build from ``(setup (stackup (layer NAME (type …) (thickness …)) …))``.

    Copper foils are ``*.Cu``; everything else (``dielectric N``, ``core``, ``prepreg``) is a
    dielectric sub-layer. Order is preserved (top → bottom). A missing thickness is treated
    as ``0``. Absent ``(setup (stackup …))`` → an empty build (H then unknown, §5.2).
    """
    setup = find(board, "setup")
    stackup = find(setup, "stackup") if setup is not None else None
    if stackup is None:
        return ()

    build: list[PhysicalLayer] = []
    for entry in find_all(stackup, "layer"):
        name = entry[1] if len(entry) > 1 and isinstance(entry[1], str) else None
        if name is None:
            continue
        thickness_node = find(entry, "thickness")
        try:
            thickness = float(_tok(thickness_node[1])) if thickness_node else 0.0
        except (ValueError, IndexError):
            thickness = 0.0
        build.append(PhysicalLayer(name=name, thickness=thickness, is_copper=name.endswith(".Cu")))
    return tuple(build)
