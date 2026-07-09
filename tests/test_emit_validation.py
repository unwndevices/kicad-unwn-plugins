"""Emit-time structural validation of footprint / symbol nodes.

These guard against emitter bugs: a malformed node must raise here rather than
be written to a ``.kicad_mod`` / ``.kicad_sym`` that only fails in KiCad.
"""

from __future__ import annotations

import pytest

from captouch.export import footprint, symbol
from captouch.export.footprint import FootprintError, validate_footprint
from captouch.export.symbol import SymbolError, validate_symbol_lib
from captouch.geometry import build_slider, build_trackpad
from captouch.params import SliderParams, TrackpadParams
from kicad_core.sexpr import Sym


def _tri():
    return footprint.custom_polygon_pad([(0, 0), (1, 0), (1, 1)])


# --- footprint -------------------------------------------------------------- #
def test_real_footprints_validate():
    validate_footprint(footprint.widget_footprint(build_slider(SliderParams())))
    validate_footprint(footprint.trackpad_footprint(build_trackpad(TrackpadParams())))


def test_footprint_wrong_head_rejected():
    with pytest.raises(FootprintError, match="footprint"):
        validate_footprint([Sym("module"), "X"])


def test_footprint_empty_name_rejected():
    node = [Sym("footprint"), "", [Sym("version"), 1], [Sym("generator"), "g"], _tri()]
    with pytest.raises(FootprintError, match="name"):
        validate_footprint(node)


def test_footprint_missing_version_rejected():
    node = [Sym("footprint"), "X", [Sym("generator"), "g"], _tri()]
    with pytest.raises(FootprintError, match="version"):
        validate_footprint(node)


def test_footprint_without_pads_rejected():
    node = [Sym("footprint"), "X", [Sym("version"), 1], [Sym("generator"), "g"]]
    with pytest.raises(FootprintError, match="no pads"):
        validate_footprint(node)


def test_footprint_degenerate_polygon_pad_rejected():
    # A custom pad whose polygon was reduced below 3 points.
    bad_pad = [
        Sym("pad"),
        "1",
        Sym("smd"),
        Sym("custom"),
        [Sym("at"), 0, 0],
        [Sym("layers"), "F.Cu"],
        [Sym("primitives"), [Sym("gr_poly"), [Sym("pts"), [Sym("xy"), 0, 0]]]],
    ]
    node = [Sym("footprint"), "X", [Sym("version"), 1], [Sym("generator"), "g"], bad_pad]
    with pytest.raises(FootprintError, match="point"):
        validate_footprint(node)


# --- symbol library --------------------------------------------------------- #
def test_real_symbol_lib_validates():
    validate_symbol_lib(symbol.widget_symbol_lib(build_slider(SliderParams())))
    validate_symbol_lib(symbol.symbol_lib("CT_Spike"))


def test_symbol_lib_wrong_head_rejected():
    with pytest.raises(SymbolError, match="kicad_symbol_lib"):
        validate_symbol_lib([Sym("foo"), "X"])


def test_symbol_lib_without_symbols_rejected():
    node = [Sym("kicad_symbol_lib"), [Sym("version"), 1], [Sym("generator"), "g"]]
    with pytest.raises(SymbolError, match="no symbols"):
        validate_symbol_lib(node)
