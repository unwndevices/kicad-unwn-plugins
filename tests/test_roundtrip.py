"""Phase 0 self-validation: S-expression round-trip and structural checks.

These verify our emitter is internally consistent. The authoritative
"opens in KiCad" gate is the separate kicad-cli check (see README)."""

from __future__ import annotations

from captouch.export import footprint, symbol
from kicad_core import sexpr

SQUARE = [(-3, -3), (3, -3), (3, 3), (-3, 3)]


def test_sexpr_roundtrip_is_idempotent():
    # Parsing then re-serialising must reproduce the exact text we emit.
    for text in (footprint.footprint_text("X", SQUARE), symbol.symbol_lib_text("X")):
        assert sexpr.dumps(sexpr.loads(text)) + "\n" == text


def test_footprint_has_custom_polygon_pad():
    node = sexpr.loads(footprint.footprint_text("CT_Spike_Pad", SQUARE))
    assert sexpr.head(node) == "footprint"

    version = sexpr.find(node, "version")
    assert version is not None and version[1] == sexpr.Sym("20241229")

    pad = sexpr.find(node, "pad")
    assert pad is not None
    flags = [c.name for c in sexpr.children(pad) if isinstance(c, sexpr.Sym)]
    assert "custom" in flags

    primitives = sexpr.find(pad, "primitives")
    assert primitives is not None
    poly = sexpr.find(primitives, "gr_poly")
    assert poly is not None
    pts = sexpr.find(poly, "pts")
    assert pts is not None and len(sexpr.find_all(pts, "xy")) == len(SQUARE)


def test_symbol_has_single_pin():
    node = sexpr.loads(symbol.symbol_lib_text("CT_Spike_Pad"))
    assert sexpr.head(node) == "kicad_symbol_lib"

    version = sexpr.find(node, "version")
    assert version is not None and version[1] == sexpr.Sym("20241209")

    sym = sexpr.find(node, "symbol")
    assert sym is not None

    pins = []
    for sub in sexpr.find_all(sym, "symbol"):
        pins += sexpr.find_all(sub, "pin")
    assert len(pins) == 1
