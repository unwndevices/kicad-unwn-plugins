# Touch Footprint Generator — Approach, Stack & Roadmap

**Status:** in progress. Compiled 2026-06-17. **Phases 0–1 complete** (headless slider engine ships rectangular / chevron / interdigitated sliders, DRC-clean in KiCad 10); Phase 2 (GUI) is next.
**Companion docs:** [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md) (the numbers the generator consumes) and [`touch-footprint-tools-landscape.md`](./touch-footprint-tools-landscape.md) (prior art and gaps this fills).

A standalone, vendor-agnostic desktop tool that parametrically generates **capacitive-touch interface footprints** (sliders, wheels, XY diamond pads) for KiCad — with a **live visual preview**, emitting a ready-to-use **footprint (`.kicad_mod`) plus a matching schematic symbol (`.kicad_sym`)**. The landscape survey confirms nothing like this exists today: vendor tools are silicon-locked and geometry-blind, KiCad's own touch wizards are archived (2023) and cover only slider + mutual-cap button, and the few open generators are tiny and dormant.

---

## 1. Decisions locked (with rationale)

| Decision | Choice | Why |
|---|---|---|
| Generation mechanism | **Direct S-expression emission** (write `.kicad_mod` / `.kicad_sym` text directly) | KiCad's SWIG `pcbnew` Python API is deprecated and slated for removal in KiCad 11; the new IPC API does not yet confirm footprint-library authoring. The maintained coil/NFC generators prove direct `.kicad_mod` emission is the stable, version-resilient pattern. |
| Delivery | **Standalone cross-platform desktop GUI** | Modifying slider/wheel/pad parameters needs immediate visual feedback so small refinements are visible at once. A standalone app gives full control over a polished live-preview canvas and is decoupled from KiCad's in-flux plugin API. |
| Output | **Electrode footprint + matching schematic symbol** | A complete, drop-in KiCad part. No board-level support copper (hatched ground, ESD ring, escape routing, series resistors) in v1 — the user adds those per their board. |
| First widget | **Slider** | Foundational: its 1-D segment geometry + interpolation logic is reused by the wheel (a slider bent into a ring) and informs the diamond pad. Self-cap, single-layer, simplest to get correct. |
| Target KiCad | **KiCad 9 and 10** | As of 2026-06, **KiCad 10.0.x is the current stable** (10.0.0 Mar 2026, 10.0.3 May 2026); 9.0.x is still maintained (9.0.9 Apr 2026). The footprint/symbol S-expr format is stable across both; we pin the `version` token and validate against both. |

---

## 2. Proposed stack

Whole stack is **Python** — it is the language of every relevant prior-art generator, the KiCad tooling, and the best 2D-geometry libraries.

| Layer | Choice | Why / maturity | Alternatives considered |
|---|---|---|---|
| Language | **Python 3.11+** | Matches all prior art (KiCad wizards, coil generators, kicad-footprint-generator); best geometry ecosystem. | Rust (egui/Slint) — faster, but no KiCad/geometry ecosystem and splits from the `.kicad_mod` text problem. |
| 2D geometry | **Shapely 2.x** | Robust, widely-used polygon ops: `buffer` (gaps, rounded corners, 2 mm ESD tip truncation), boolean ops (interdigitation), validity checks. Mature, GEOS-backed. | `pyclipper` (offsetting only); `gdsfactory` (powerful but chip-oriented, GDS-first, no `.kicad_mod`). |
| Arc handling | **Polyline tessellation** (in-house, resolution param) | KiCad custom-pad polygons **cannot contain arcs**, so wheel arcs / rounded shapes are approximated as polylines (mirrors ESCPT's "corner resolution" knob). | — |
| KiCad emission | **Thin in-house S-expression writer** targeting KiCad 9/10 footprint + symbol format; `sexpdata` for low-level serialize/round-trip | Honors the "direct emission" decision; zero dependency on an unstable API; we control the `version`/`generator` tokens. | **`kiutils`** — handles both fp+sym but is **inactive** (v1.4.8, >12 mo no release) → not load-bearing; **`KicadModTree`** — official, active, but **footprint-only** (no symbols) and library-convention-bound; **`kicad-skip`** — maintained but built for *editing existing* files, not greenfield authoring. |
| GUI | **PySide6** (Qt 6) + **`QGraphicsView` / `QGraphicsScene`** | The standard Qt 2D vector framework: zoom/pan, layer-colored items, smooth repaint on parameter change. PySide6 6.11.x, **LGPLv3** (distribution-friendly for open source, unlike PyQt6's GPL). | PyQt6 (GPL/commercial), Tkinter/Kivy (weaker vector canvas), web/Electron (rejected: awkward local-file export + KiCad round-trip). |
| CLI | **Thin `argparse`/Click frontend** over the same engine | Near-zero cost, and *no CLI exists anywhere* in this space — a clean differentiator for automation, regression tests, and parametric sweeps. | — |
| Validation | **`kicad-cli`** (`fp export svg`, `sym export svg`, `pcb drc`) | Headless rendering + DRC of generated files in CI → golden-image diffs and a real "it opens and passes DRC in KiCad 9 *and* 10" gate. | Manual open in KiCad (kept as the human acceptance step). |
| Packaging | **PyInstaller** or **Briefcase** for binaries; **pip/pipx** for developers | Cross-platform standalone executables for non-Python users. | — |
| Tests | **pytest** + golden-file `.kicad_mod` snapshots + `kicad-cli` render/DRC diff | Geometry layer is pure functions → fully unit-testable; exporters tested by snapshot + round-trip. | — |

---

## 3. Architecture

**Core principle — one source of truth.** A single parametric geometry model produces the polygons; the Qt preview and the KiCad exporters both consume *the same* model, guaranteeing the preview is byte-faithful to the exported copper (WYSIWYG).

```
            params  ──►  geometry  ──►  ┌── export.kicad_mod (footprint)
         (dataclasses)  (shapely)       ├── export.kicad_sym (symbol)
                                        └── export.svg / dxf (optional)
                                  ▲
                    ┌─────────────┴─────────────┐
                  gui (PySide6)             cli (argparse)
            live QGraphicsView preview    headless file output
```

| Module (`src/captouch/…`) | Responsibility | Dependencies |
|---|---|---|
| `params/` | One dataclass per widget (`SliderParams`, `WheelParams`, `TrackpadParams`) with **vendor-default presets** (from the guidelines doc) and **constraint validation** (e.g. enforce Infineon's `W + 2A ≈ finger_diameter`). | none |
| `geometry/` | Pure functions `params → shapely polygons` for electrodes, courtyard, silkscreen, keep-outs; interdigitation; arc tessellation; corner rounding / tip truncation. **No KiCad or Qt imports.** | shapely |
| `export/` | Geometry → `.kicad_mod` (electrodes as **custom-shape SMD copper pads** so they carry nets and DRC sees them; silk via `fp_poly`; courtyard), → `.kicad_sym` (N-pin part, pins 1:1 with pads), → optional SVG/DXF. Pins format `version`. | sexpdata |
| `gui/` | PySide6 parameter panel ↔ live `QGraphicsScene` preview, layer toggles, export dialog. | PySide6 |
| `cli/` | Same engine; params from flags/JSON → files. | — |

**Key technical notes**
- **Electrodes = custom-shape pads, not graphics.** One pad per slider segment (+ ground/shield), each on `F.Cu`, so each electrode has a pad number that maps 1:1 to a symbol pin and participates in DRC. (Board-level fills like a future hatched ground would instead be zones — out of v1 scope.)
- **Arcs → polylines** for wheels and rounded edges (custom-pad polygon arc limitation).
- **ESD/robustness geometry** (rounded corners, ~2 mm truncated tips) realized via `shapely.buffer`.

---

## 4. Roadmap (phased, each phase independently verifiable)

> Verification-first: Phase 0 attacks the single riskiest assumption — that our hand-emitted file opens cleanly and round-trips across KiCad 9 **and** 10 — before any feature work.

| Phase | Goal | Done when |
|---|---|---|
| **0 — Format spike** ✅ | Repo + packaging skeleton; emit one trivial `.kicad_mod` with a single custom-polygon copper pad and a one-pin `.kicad_sym`. | Opens without error in KiCad 9 and 10; `kicad-cli fp export svg` and `sym export svg` render it; round-trip parse is stable. |
| **1 — Slider engine (headless)** ✅ | `params`+`geometry`+`export` for rectangular → chevron/interdigitated slider; `W+2A` constraint; dummy end segments; CLI. | Golden-file snapshots stable; `kicad-cli pcb drc` clean on a test board; pads ↔ symbol pins correct. |
| **2 — Slider GUI** | PySide6 shell, parameter panel, **live preview**, export buttons; polished spacing/zoom/pan. | Editing any parameter updates the preview in real time; exported file matches the preview. |
| **3 — Wheel** | Reuse slider interpolation bent into an annulus; arc tessellation; center keep-out; continuous (no end dummies). | Generates a valid 3+-segment wheel; DRC-clean; previewed live. |
| **4 — XY diamond pad** | Mutual-cap diamond matrix; half-diamond edge termination; layer **bridges/vias**; Rx/Tx axis assignment. | Generates an N×M diamond pad with correct bridging; DRC-clean. (Highest complexity — may use zones for some fills.) |
| **5 — Polish & distribution** | Vendor presets, fab-min-rule guards, cross-platform binaries, user docs. | Installable binary; presets reproduce vendor reference dimensions. |

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| KiCad format drift (9 → 10 → 11) | Pin `version` token; CI validates with `kicad-cli` for each supported version; the thin exporter isolates format changes to one module. |
| `kiutils` inactivity | Not relied upon — we own the exporter. |
| SWIG removal / IPC immaturity | Avoided entirely by direct text emission. |
| Custom-pad polygons can't hold arcs | Tessellate to polylines with a resolution parameter. |
| DRC-clean copper for diamond bridges/vias is hard | Deferred to Phase 4; precedent exists (ESCPT emits KiCad zones for DRC-aware copper). |
| "Trivial" symbol generation still needs correct pin/unit mapping | Validate emitted `.kicad_sym` via `kicad-cli sym export svg` and pin-count assertions. |

---

## 6. Resolved decisions & remaining open questions

**Resolved (2026-06-17):**
- **License:** **GPL-3.0** — matches the KiCad ecosystem and prior art (KiCad wizards, ESCPT, coil generators are all GPL).
- **Slider sensing mode (v1):** **self-capacitance** (the standard slider topology); mutual exposed later.
- **Distribution:** **standalone binaries** for now (PyInstaller/Briefcase); PyPI and a KiCad Plugin Manager listing are deferred.

**Still open (resolve before/within the relevant phase):**
- **Post-MVP "insert directly into open board":** revisit once the KiCad IPC API matures (currently avoided).
- **Symbol style:** single multi-pin part vs multi-unit — leaning to a single part with one pin per electrode + ground/shield pins.

---

## 7. Key references

**This project's research**
- [`docs/capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md) — vendor-sourced numeric design rules + the derived parameter set.
- [`docs/touch-footprint-tools-landscape.md`](./touch-footprint-tools-landscape.md) — prior-art survey and the gap this fills.

**Stack**
- KiCad releases (10.0.x current, 9.0.x maintained): <https://www.kicad.org/blog/categories/Release-Notes/>
- KiCad footprint S-expr format: <https://dev-docs.kicad.org/en/file-formats/sexpr-footprint/index.html>
- `kicad-cli` (9.0): <https://docs.kicad.org/9.0/en/cli/cli.html> · (10.0): <https://docs.kicad.org/10.0/en/cli/cli.html>
- KicadModTree / kicad-footprint-generator (official, active): <https://gitlab.com/kicad/libraries/kicad-footprint-generator>
- kiutils (KiCad 6+ fp+sym; inactive): <https://github.com/mvnmgrx/kiutils>
- kicad-skip (editing existing files): <https://github.com/psychogenic/kicad-skip>
- Shapely: <https://shapely.readthedocs.io/>
- PySide6 (LGPLv3): <https://pypi.org/project/PySide6/> · QGraphics framework: <https://www.pythonguis.com/tutorials/pyside6-qgraphics-vector-graphics/>
- ESCPT (KiCad zones for touch pads — DRC-aware precedent): <https://github.com/hanya/ESCPT>
