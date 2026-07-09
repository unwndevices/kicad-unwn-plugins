"""kicad-core — lean shared primitives for the kicad-unwn-plugins tools.

Currently exposes the KiCad-flavoured S-expression read/emit model (:mod:`kicad_core.sexpr`),
carved out of ``kicad-captouch`` so both the footprint emitter and the return-path
checker's board reader share one parser. Kept deliberately minimal — only what more
than one tool genuinely shares.
"""

__version__ = "0.1.0"
