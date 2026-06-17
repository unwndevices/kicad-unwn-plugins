"""Test-only helper: wrap a generated footprint into a minimal DRC-able board.

This is *not* part of the product surface (the tool emits a footprint + symbol,
not boards). It exists so the test suite can place a slider on a trivial
single-layer board with a board outline and run ``kicad-cli pcb drc`` against
it — the "it opens and passes DRC in KiCad" gate from the roadmap.
"""

from __future__ import annotations

from captouch import sexpr
from captouch.export import footprint
from captouch.sexpr import Sym

# Canonical KiCad layer table (the subset a board must declare).
_STD_LAYERS = [
    (0, "F.Cu", "signal"),
    (2, "B.Cu", "signal"),
    (9, "F.Adhes", "user", "F.Adhesive"),
    (11, "B.Adhes", "user", "B.Adhesive"),
    (13, "F.Paste", "user"),
    (15, "B.Paste", "user"),
    (5, "F.SilkS", "user", "F.Silkscreen"),
    (7, "B.SilkS", "user", "B.Silkscreen"),
    (1, "F.Mask", "user"),
    (3, "B.Mask", "user"),
    (17, "Dwgs.User", "user", "User.Drawings"),
    (19, "Cmts.User", "user", "User.Comments"),
    (21, "Eco1.User", "user", "User.Eco1"),
    (23, "Eco2.User", "user", "User.Eco2"),
    (25, "Edge.Cuts", "user"),
    (27, "Margin", "user"),
    (31, "F.CrtYd", "user", "F.Courtyard"),
    (29, "B.CrtYd", "user", "B.Courtyard"),
    (35, "F.Fab", "user"),
    (33, "B.Fab", "user"),
]


def _layers() -> list:
    out: list = [Sym("layers")]
    for row in _STD_LAYERS:
        extra = [row[3]] if len(row) > 3 else []
        out.append([row[0], row[1], Sym(row[2]), *extra])
    return out


def _embed(fp_node: list, at: tuple[float, float]) -> list:
    """Adapt a standalone footprint node for embedding in a board."""
    drop = ("version", "generator", "generator_version", "layer")
    body = [c for c in fp_node[2:] if not (isinstance(c, list) and sexpr.head(c) in drop)]
    return [
        Sym("footprint"),
        fp_node[1],
        [Sym("layer"), "F.Cu"],
        [Sym("uuid"), "00000000-0000-0000-0000-000000000001"],
        [Sym("at"), at[0], at[1]],
        *body,
    ]


def _edge_cuts(geo, at: tuple[float, float], margin: float) -> list:
    minx, miny, maxx, maxy = geo.bounds
    x0, y0 = at[0] + minx - margin, at[1] + miny - margin
    x1, y1 = at[0] + maxx + margin, at[1] + maxy + margin
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [
        Sym("gr_poly"),
        [Sym("pts"), *[[Sym("xy"), x, y] for x, y in pts]],
        [Sym("stroke"), [Sym("width"), 0.1], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), "Edge.Cuts"],
    ]


def widget_board_text(
    geo, *, at: tuple[float, float] = (100.0, 100.0), margin: float = 8.0
) -> str:
    """Serialise a minimal board with the widget placed and a board outline."""
    fp = _embed(footprint.widget_footprint(geo), at)
    board = [
        Sym("kicad_pcb"),
        [Sym("version"), footprint.FOOTPRINT_VERSION],
        [Sym("generator"), "kicad-captouch"],
        [Sym("generator_version"), "0.1.0"],
        [Sym("general"), [Sym("thickness"), 1.6]],
        [Sym("paper"), "A4"],
        _layers(),
        [Sym("setup")],
        [Sym("net"), 0, ""],
        _edge_cuts(geo, at, margin),
        fp,
    ]
    return sexpr.dumps(board) + "\n"


# Back-compat alias: the slider tests call this name.
slider_board_text = widget_board_text
