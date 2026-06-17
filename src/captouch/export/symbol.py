"""Emit a KiCad schematic symbol library (`.kicad_sym`) for a touch widget.

A slider symbol is a single part with one pin per electrode pad: active
electrodes on the left (named ``E1..EN``), grounded end dummies on the right
(named ``GND``). Every pin **number** equals the corresponding footprint pad
number, so the symbol's pins map 1:1 to the footprint's pads. Output targets the
KiCad 9.0 symbol-library format (``version 20241209``).
"""

from __future__ import annotations

from typing import Union

from .. import __version__, sexpr
from ..geometry import SliderGeometry, WheelGeometry
from ..sexpr import Sym

WidgetGeometry = Union[SliderGeometry, WheelGeometry]

# KiCad 9.0 .kicad_sym S-expression format version (date token).
SYMBOL_LIB_VERSION = 20241209
GENERATOR = "kicad-captouch"

PIN_PITCH = 2.54
PIN_LENGTH = 2.54
BODY_HALF_WIDTH = 5.08


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
    length: float = PIN_LENGTH,
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


def _rectangle(half_w: float, half_h: float) -> list:
    return [
        Sym("rectangle"),
        [Sym("start"), -half_w, half_h],
        [Sym("end"), half_w, -half_h],
        [Sym("stroke"), [Sym("width"), 0.254], [Sym("type"), Sym("default")]],
        [Sym("fill"), [Sym("type"), Sym("none")]],
    ]


def _column_ys(count: int) -> list[float]:
    """Grid-aligned y positions, top to bottom, centred on the origin."""
    top = (count - 1) / 2.0 * PIN_PITCH
    return [top - i * PIN_PITCH for i in range(count)]


def _symbol_node(
    name: str,
    left: list[tuple[str, str]],
    right: list[tuple[str, str]],
    *,
    reference: str = "U",
) -> list:
    """Build a single multi-pin symbol; *left*/*right* are ``(number, name)``."""
    rows = max(len(left), len(right), 1)
    half_h = (rows - 1) / 2.0 * PIN_PITCH + PIN_PITCH
    x_end = BODY_HALF_WIDTH + PIN_LENGTH

    pins: list[list] = []
    for (num, pname), y in zip(left, _column_ys(len(left))):
        pins.append(_pin(pname, num, (-x_end, y, 0)))
    for (num, pname), y in zip(right, _column_ys(len(right))):
        pins.append(_pin(pname, num, (x_end, y, 180)))

    body = [Sym("symbol"), f"{name}_0_1", _rectangle(BODY_HALF_WIDTH, half_h)]
    pin_unit = [Sym("symbol"), f"{name}_1_1", *pins]

    return [
        Sym("symbol"),
        name,
        [Sym("pin_names"), [Sym("offset"), 0]],
        [Sym("exclude_from_sim"), Sym("no")],
        [Sym("in_bom"), Sym("yes")],
        [Sym("on_board"), Sym("yes")],
        _property("Reference", reference, (0, half_h + PIN_PITCH, 0)),
        _property("Value", name, (0, -half_h - PIN_PITCH, 0)),
        _property("Footprint", "", (0, -half_h - 2 * PIN_PITCH, 0), hide=True),
        body,
        pin_unit,
    ]


def _lib(*symbols: list) -> list:
    return [
        Sym("kicad_symbol_lib"),
        [Sym("version"), SYMBOL_LIB_VERSION],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), __version__],
        *symbols,
    ]


# --------------------------------------------------------------------------- #
# Phase 0 spike: a single one-pin symbol (kept for the format gate)
# --------------------------------------------------------------------------- #
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
    """Build a symbol-library node containing a single one-pin symbol."""
    return _lib(one_pin_symbol(name))


def symbol_lib_text(name: str) -> str:
    """Serialise a one-symbol library to `.kicad_sym` text (trailing newline)."""
    return sexpr.dumps(symbol_lib(name)) + "\n"


# --------------------------------------------------------------------------- #
# Widget symbol: one pin per electrode pad
# --------------------------------------------------------------------------- #
def widget_symbol(geo: WidgetGeometry) -> list:
    """Build a multi-pin symbol for any widget; pin numbers match pad numbers.

    The geometry chooses the two pin columns via ``symbol_columns`` (slider:
    active left / GND right; wheel: the ring's electrodes split into halves).
    """
    left, right = geo.symbol_columns()
    return _symbol_node(geo.params.name, left, right)


def widget_symbol_lib(geo: WidgetGeometry) -> list:
    """Build a symbol-library node containing the widget symbol."""
    return _lib(widget_symbol(geo))


def widget_symbol_lib_text(geo: WidgetGeometry) -> str:
    """Serialise a widget symbol library to `.kicad_sym` text (trailing newline)."""
    return sexpr.dumps(widget_symbol_lib(geo)) + "\n"


# Backwards-compatible / explicit per-widget aliases.
def slider_symbol(geo: SliderGeometry) -> list:
    """Build a slider symbol (see :func:`widget_symbol`)."""
    return widget_symbol(geo)


def slider_symbol_lib(geo: SliderGeometry) -> list:
    return _lib(widget_symbol(geo))


def slider_symbol_lib_text(geo: SliderGeometry) -> str:
    """Serialise a slider symbol library to `.kicad_sym` text (trailing newline)."""
    return widget_symbol_lib_text(geo)


def wheel_symbol(geo: WheelGeometry) -> list:
    """Build a wheel symbol (see :func:`widget_symbol`)."""
    return widget_symbol(geo)


def wheel_symbol_lib(geo: WheelGeometry) -> list:
    return _lib(widget_symbol(geo))


def wheel_symbol_lib_text(geo: WheelGeometry) -> str:
    """Serialise a wheel symbol library to `.kicad_sym` text (trailing newline)."""
    return widget_symbol_lib_text(geo)
