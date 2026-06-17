"""Emit a KiCad schematic symbol library (`.kicad_sym`) for a touch widget.

Phase 0 emits a single one-pin symbol; later phases add one pin per electrode
(plus ground/shield pins) so the symbol's pins map 1:1 to the footprint's pads.
Output targets the KiCad 9.0 symbol-library format (``version 20241209``).
"""

from __future__ import annotations

from .. import __version__, sexpr
from ..sexpr import Sym

# KiCad 9.0 .kicad_sym S-expression format version (date token).
SYMBOL_LIB_VERSION = 20241209
GENERATOR = "kicad-captouch"


def _effects(size: float = 1.27, *, hide: bool = False) -> list:
    eff = [Sym("effects"), [Sym("font"), [Sym("size"), size, size]]]
    if hide:
        eff.append([Sym("hide"), Sym("yes")])
    return eff


def _property(name: str, value: str, at: tuple[float, float, float], *, hide: bool = False) -> list:
    x, y, rot = at
    return [Sym("property"), name, value, [Sym("at"), x, y, rot], _effects(hide=hide)]


def _pin(
    name: str,
    number: str,
    at: tuple[float, float, float],
    *,
    length: float = 2.54,
    etype: str = "passive",
    style: str = "line",
) -> list:
    x, y, rot = at
    return [
        Sym("pin"),
        Sym(etype),
        Sym(style),
        [Sym("at"), x, y, rot],
        [Sym("length"), length],
        [Sym("name"), name, _effects()],
        [Sym("number"), number, _effects()],
    ]


def one_pin_symbol(name: str) -> list:
    """Build a minimal single-pin symbol with a rectangular body."""
    body = [
        Sym("symbol"),
        f"{name}_0_1",
        [
            Sym("rectangle"),
            [Sym("start"), -2.54, 2.54],
            [Sym("end"), 2.54, -2.54],
            [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]],
            [Sym("fill"), [Sym("type"), Sym("none")]],
        ],
    ]
    pins = [Sym("symbol"), f"{name}_1_1", _pin("1", "1", (-5.08, 0, 0))]
    return [
        Sym("symbol"),
        name,
        [Sym("pin_names"), [Sym("offset"), 0]],
        [Sym("exclude_from_sim"), Sym("no")],
        [Sym("in_bom"), Sym("yes")],
        [Sym("on_board"), Sym("yes")],
        _property("Reference", "U", (0, 3.81, 0)),
        _property("Value", name, (0, 0, 0)),
        _property("Footprint", "", (0, -3.81, 0), hide=True),
        body,
        pins,
    ]


def symbol_lib(name: str) -> list:
    """Build a symbol-library node containing a single symbol."""
    return [
        Sym("kicad_symbol_lib"),
        [Sym("version"), SYMBOL_LIB_VERSION],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), __version__],
        one_pin_symbol(name),
    ]


def symbol_lib_text(name: str) -> str:
    """Serialise a one-symbol library to `.kicad_sym` text (trailing newline)."""
    return sexpr.dumps(symbol_lib(name)) + "\n"
