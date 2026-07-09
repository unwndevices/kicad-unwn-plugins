# kicad-core

Lean shared primitives for the [kicad-unwn-plugins](../../README.md) tools.

Today this is a single module — `kicad_core.sexpr`, a minimal KiCad-flavoured
S-expression model, serialiser, and parser (`loads` / `dumps` / `find` /
`find_all` / `head` / `children` / `Sym`). KiCad files (`.kicad_mod`,
`.kicad_sym`, `.kicad_pcb`) are S-expressions; this parser round-trips them
losslessly (`dumps(loads(text)) == text` for text we emit), so the same code
serves both footprint/symbol emission (`kicad-captouch`) and board reading
(`kicad-returnpath`).

Carved out of `kicad-captouch` once a second consumer needed it, per
[`docs/return-path-checker-v1-spec.md`](../../docs/return-path-checker-v1-spec.md) §11.
Kept deliberately minimal — only what more than one tool genuinely shares.

Licensed GPL-3.0-or-later.
