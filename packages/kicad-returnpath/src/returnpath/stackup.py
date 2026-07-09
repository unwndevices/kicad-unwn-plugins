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

from kicad_core.sexpr import Node, Sym, children, find

# Copper-layer types in a KiCad `(layers …)` block. `user`/`Edge.Cuts` are excluded.
_COPPER_TYPES = {"signal", "power", "mixed", "jumper"}


def _tok(x: Node) -> str:
    return x.name if isinstance(x, Sym) else str(x)


@dataclass(frozen=True)
class Stackup:
    """The board's copper layers in physical order (top ``F.Cu`` → bottom ``B.Cu``)."""

    order: tuple[str, ...]

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


def parse_stackup(board: Node) -> Stackup:
    """Build the :class:`Stackup` from a ``.kicad_pcb`` root node.

    Reads ``(layers (0 "F.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal) …)``,
    keeps the copper entries (``F.Cu`` / ``In*.Cu`` / ``B.Cu`` with a copper type),
    and orders them by their canonical KiCad ordinal. A board without a ``(layers …)``
    section (e.g. a minimal inline fixture) yields an empty stackup.
    """
    layers_node = find(board, "layers")
    if layers_node is None:
        return Stackup(order=())

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
    return Stackup(order=tuple(name for _, name in ordered))
