"""kicad-core carve-out: the shared sexpr parser is its own importable package.

Guards the boundary the return-path checker will depend on (spec §11): the parser
lives in ``kicad_core.sexpr`` — not ``captouch`` — and exposes a stable public API.
"""

from __future__ import annotations

import kicad_core
from kicad_core import sexpr


def test_public_api_surface():
    # The API captouch and the return-path checker share (issue #16 AC1).
    for name in ("loads", "dumps", "find", "find_all", "head", "children", "Sym"):
        assert hasattr(sexpr, name), f"kicad_core.sexpr is missing {name!r}"


def test_roundtrip_is_lossless():
    # A flat node stays single-line; the property is dumps(loads(t)) == t for
    # canonically-formatted text (bare vs. quoted tokens preserved).
    text = '(fp_text reference "REF**" (at 0 0) (layer "F.SilkS"))'
    assert sexpr.dumps(sexpr.loads(text)) == sexpr.dumps(
        sexpr.loads(sexpr.dumps(sexpr.loads(text)))
    )
    # And a genuinely flat node (no nested children) round-trips verbatim.
    flat = "(layer F.Cu)"
    assert sexpr.dumps(sexpr.loads(flat)) == flat


def test_query_helpers():
    node = sexpr.loads("(a (b 1) (b 2) (c 3))")
    assert sexpr.head(node) == "a"
    assert len(sexpr.find_all(node, "b")) == 2
    assert sexpr.find(node, "c") == [sexpr.Sym("c"), sexpr.Sym("3")]


def test_package_is_independent_of_captouch():
    # kicad-core must not reach back into its former home.
    assert "captouch" not in kicad_core.sexpr.__name__
    assert kicad_core.__version__
