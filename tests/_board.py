"""Test-only helper: wrap a generated footprint into a minimal DRC-able board.

This is *not* part of the product surface (the tool emits a footprint + symbol,
not boards). It exists so the test suite can place a slider on a trivial
single-layer board with a board outline and run ``kicad-cli pcb drc`` against
it — the "it opens and passes DRC in KiCad" gate from the roadmap.
"""

from __future__ import annotations

from captouch import sexpr
from captouch.export import footprint
from captouch.geometry import TrackpadGeometry
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


def _embed(fp_node: list, at: tuple[float, float], net_of: dict | None = None) -> list:
    """Adapt a standalone footprint node for embedding in a board.

    If *net_of* (``{pad_number: (index, name)}``) is given, each pad is stamped
    with its ``(net …)`` so DRC checks clearance/connectivity per real net rather
    than treating all copper as one netless blob.
    """
    drop = ("version", "generator", "generator_version", "layer")
    body = [c for c in fp_node[2:] if not (isinstance(c, list) and sexpr.head(c) in drop)]
    if net_of:
        body = [_stamp_net(c, net_of) if sexpr.head(c) == "pad" else c for c in body]
    return [
        Sym("footprint"),
        fp_node[1],
        [Sym("layer"), "F.Cu"],
        [Sym("uuid"), "00000000-0000-0000-0000-000000000001"],
        [Sym("at"), at[0], at[1]],
        *body,
    ]


def _stamp_net(pad: list, net_of: dict) -> list:
    """Append a ``(net index name)`` child to *pad* from its pad number."""
    number = sexpr.children(pad)[0]
    entry = net_of.get(number)
    if entry is None:
        return pad
    index, name = entry
    return [*pad, [Sym("net"), index, name]]


def trackpad_net_map(geo: TrackpadGeometry) -> dict:
    """``{pad_number: (net_index, net_name)}`` — one distinct net per Rx/Tx line."""
    return {n.pad_number: (i + 1, n.pin_name) for i, n in enumerate(geo.nets)}


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
    geo,
    *,
    at: tuple[float, float] = (100.0, 100.0),
    margin: float = 8.0,
    nets: dict | None = None,
) -> str:
    """Serialise a minimal board with the widget placed and a board outline.

    *nets* (``{pad_number: (index, name)}``, e.g. from :func:`trackpad_net_map`)
    assigns a real net per pad number so DRC genuinely checks inter-net clearance
    and cross-layer connectivity. Omitted (slider/wheel) → all copper is netless,
    which KiCad still clearance-checks.
    """
    if isinstance(geo, TrackpadGeometry):
        fp_node = footprint.trackpad_footprint(geo)
    else:
        fp_node = footprint.widget_footprint(geo)
    fp = _embed(fp_node, at, nets)

    net_decls = [[Sym("net"), 0, ""]]
    if nets:
        for index, name in sorted(set(nets.values())):
            net_decls.append([Sym("net"), index, name])

    board = [
        Sym("kicad_pcb"),
        [Sym("version"), footprint.FOOTPRINT_VERSION],
        [Sym("generator"), "kicad-captouch"],
        [Sym("generator_version"), "0.1.0"],
        [Sym("general"), [Sym("thickness"), 1.6]],
        [Sym("paper"), "A4"],
        _layers(),
        [Sym("setup")],
        *net_decls,
        _edge_cuts(geo, at, margin),
        fp,
    ]
    return sexpr.dumps(board) + "\n"


# Back-compat alias: the slider tests call this name.
slider_board_text = widget_board_text


# --------------------------------------------------------------------------- #
# Support copper (Phase 8): lift embedded zones to board level so DRC fills them
# --------------------------------------------------------------------------- #
# kicad-cli `pcb drc --refill-zones` only refills *board-level* zones, not zones
# embedded in a footprint. To verify the support-copper geometry (fill, clearance,
# and that the GND net-tie actually ties the filled pour), the test board pulls
# the footprint's zones out, translates them to the placed position, stamps the
# GND net, and drops them at board level — where the filler runs for real.
def _translate(node: list, dx: float, dy: float) -> list:
    """Recursively shift every ``(xy x y)`` in *node* by (dx, dy)."""
    out: list = []
    for c in node:
        if isinstance(c, list):
            if sexpr.head(c) == "xy":
                out.append([Sym("xy"), c[1] + dx, c[2] + dy])
            else:
                out.append(_translate(c, dx, dy))
        else:
            out.append(c)
    return out


def _stamp_zone_net(zone: list, index: int, name: str) -> list:
    """Rewrite a zone's ``(net …)`` / ``(net_name …)`` to a real board net."""
    out: list = []
    for c in zone:
        if isinstance(c, list) and sexpr.head(c) == "net":
            out.append([Sym("net"), index])
        elif isinstance(c, list) and sexpr.head(c) == "net_name":
            out.append([Sym("net_name"), name])
        else:
            out.append(c)
    return out


_PROBE_NUMBER = "GNDPROBE"


def _probe_pad(at: tuple[float, float], diameter: float) -> list:
    """A thru-hole GND pad (geometry coords) injected into the widget footprint — a
    second GND point joinable only via the filled pour, so connectivity is a real
    check. Sized like the net-tie (≥ hatch pitch) so it reliably overlaps a hatched
    pour; being part of the widget footprint it sits in its own courtyard (no
    ``pth_inside_courtyard``)."""
    return [
        Sym("pad"),
        _PROBE_NUMBER,
        Sym("thru_hole"),
        Sym("circle"),
        [Sym("at"), at[0], at[1]],
        [Sym("size"), diameter, diameter],
        [Sym("drill"), 0.3],
        [Sym("layers"), "*.Cu", "*.Mask"],
        [Sym("remove_unused_layers"), Sym("no")],
    ]


def support_board_text(
    geo,
    *,
    with_zones: bool = True,
    probe_at: tuple[float, float] | None = None,
    at: tuple[float, float] = (100.0, 100.0),
    margin: float = 10.0,
) -> str:
    """Board placing *geo* with electrodes on distinct nets and the support-copper
    zones lifted to board level on the GND net (index 1).

    ``with_zones=False`` omits the lifted zones (negative control: the GND net-tie
    + *probe_at* pad can then only be unconnected). ``probe_at`` (geometry coords)
    injects a second GND thru-hole pad, reachable only through the filled pour.
    """
    from captouch.geometry import net_tie_number

    # Each electrode gets a unique synthetic net name ("N<pad>") — never "GND", so
    # the slider's grounded dummy pads (pin name "GND") don't merge with the support
    # GND net by name. Only the net-tie + lifted zones are GND.
    gnd = 1
    if isinstance(geo, TrackpadGeometry):
        fp_node = footprint.trackpad_footprint(geo)
        items = [n.pad_number for n in geo.nets]
    else:
        fp_node = footprint.widget_footprint(geo)
        items = [e.pad_number for e in geo.electrodes]
    net_of = {pad: (i + 2, f"N{pad}") for i, pad in enumerate(items)}
    tie = net_tie_number(geo)
    if tie is not None:
        net_of[tie] = (gnd, "GND")

    zones = [c for c in fp_node if isinstance(c, list) and sexpr.head(c) == "zone"]
    body = [c for c in fp_node if not (isinstance(c, list) and sexpr.head(c) == "zone")]
    if probe_at is not None:  # inject the GND probe pad into the footprint body
        net_of[_PROBE_NUMBER] = (gnd, "GND")
        pdiam = max(0.6, geo.params.ground_hatch_pitch) if geo.params.ground_hatch else 0.6
        body = [*body[:-1], _probe_pad(probe_at, pdiam), body[-1]]
    fp = _embed(body, at, net_of)

    extra: list = []
    if with_zones:
        extra += [_translate(_stamp_zone_net(z, gnd, "GND"), at[0], at[1]) for z in zones]

    net_decls = [[Sym("net"), 0, ""]]
    for index, name in sorted(set(net_of.values())):
        net_decls.append([Sym("net"), index, name])

    board = [
        Sym("kicad_pcb"),
        [Sym("version"), footprint.FOOTPRINT_VERSION],
        [Sym("generator"), "kicad-captouch"],
        [Sym("generator_version"), "0.1.0"],
        [Sym("general"), [Sym("thickness"), 1.6]],
        [Sym("paper"), "A4"],
        _layers(),
        [Sym("setup")],
        *net_decls,
        _edge_cuts(geo, at, margin),
        fp,
        *extra,
    ]
    return sexpr.dumps(board) + "\n"
