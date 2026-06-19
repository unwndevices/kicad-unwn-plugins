# Touch Footprint Generator — v2 Roadmap (post-MVP)

**Status:** Track A (Phases 6–7) **complete**; Track B (Phases 8–9) **complete**; Track C (Phases 10–13) **in progress** — Phases 10–12 complete. Compiled 2026-06-18; Phase 9 landed 2026-06-19; Phase 10 landed 2026-06-19; Phase 11 landed 2026-06-19; Phase 12 landed 2026-06-19. Builds on [`plan.md`](./plan.md) (Phases 0–5 **complete**: a feature-complete electrodes-only generator for sliders, wheels, and XY diamond trackpads, with a live GUI, vendor presets, fab-rule guards, and standalone binaries).

This milestone extends the shipped tool along four tracks the v1 scope deliberately excluded or deferred:

1. **Optional board-level support copper** — hatched ground, guard/ESD rings, and design advisories, all **opt-in, default-off, and configurable**.
2. **Quick correctness & UX wins** — semantic symbol pins, GUI presets, JSON parameter save/load, preview image export, inline help/validation.
3. **Robustness & developer hygiene** — lint/type gates in CI, emit-time S-expression validation, non-finite input guards.
4. **Reach** — two new sensor types (mutual-cap slider, button/keypad grid), DXF export, and an in-KiCad Action Plugin.

**Companion docs:** [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md) (the numbers these features consume) and [`touch-footprint-tools-landscape.md`](./touch-footprint-tools-landscape.md).

---

## 1. Decisions & principles for v2

| Decision | Choice | Why |
|---|---|---|
| **Board-level copper, reversed but gated** | v1 §1 locked *"no board-level support copper — the user adds those per their board."* v2 **adds** hatched ground, guard rings, etc., but every such feature is **off by default and individually toggleable + configurable**. | The clean drop-in electrode part stays the default behaviour (and the golden files stay byte-identical when features are off). Users who want the silent-failure-mode mitigations (ground, guarding) get them without hand-drawing; users who don't pay nothing. |
| **Support copper = zones, not pads** | Electrodes remain custom-shape **pads** (carry nets + DRC). Hatched ground and guard rings are emitted as KiCad **`zone`** objects *inside the footprint*. | Zones give DRC-aware, net-tied fill with real hatch parameters. Footprints have supported embedded `zone` tokens since KiCad 7; ESCPT is prior art for DRC-clean touch zones (already cited in `plan.md` risks). |
| **Sensitivity / Cp / sizing checks are advisories** | They reuse the existing **fab-rule warning channel**: warn by default, `--strict` can promote to a hard block. | Consistent UX with the shipped fab guards (amber GUI banner / exit-3 in CLI). These are guidance, not manufacturability errors. |
| **Series resistor = advisory + symbol/silk, not footprint pads** | Recommend the value (560 Ω self / 2 kΩ mutual / vendor range) in advisory output and optionally on silk; **do not** stamp resistor SMD pads into the electrode footprint. | A series R sits ~10 mm from the *MCU*, not the electrode — copper pads in the sensor footprint would be physically misplaced. (Open: a symbol-level R is possible later; see §6.) |
| **Direct emission stays the core; the plugin is a thin wrapper** | The Action Plugin calls the same engine and uses KiCad's IPC API (kicad-python / `kipy`, stable in KiCad 9/10) only to *place* the result into an open board. | Keeps the version-resilient text emitter as the single source of truth; resolves v1's "insert directly into open board" open question without coupling generation to the API. |

---

## 2. Architecture deltas

The v1 pipeline is unchanged; v2 adds three things to it:

```
            params  ──►  geometry  ──►  ┌── export.kicad_mod (pads  + NEW: zones)
   (+ optional support     (shapely)    ├── export.kicad_sym (NEW: semantic pins)
      copper + overlay)        │        ├── export.dxf        (NEW)
                               │        └── export.svg/png    (NEW: preview capture)
                      ┌────────┴────────┐
              advisory checks      gui (PySide6)  ──► NEW: presets, JSON I/O, image export
        (overlay / Cp / sizing)    cli (argparse) ──► NEW: --params-json, advisory flags
                                        │
                                   NEW: kicad-plugin (IPC wrapper → place into open board)
```

| Module (`src/captouch/…`) | v2 change |
|---|---|
| `params/` | New optional fields per widget: `ground_*` (hatch fill %, line width, pitch, enable), `guard_*` (ring width, gap, mask, net), `overlay_thickness`, `overlay_er`. All default to "feature off" / sentinel. New `advisory.py` for sensitivity/Cp/sizing checks (mirrors `fab.py`). |
| `geometry/` | New `zones.py`: `params → shapely polygons` for hatched ground and guard rings (pure, no KiCad/Qt). Reused by every widget. |
| `export/footprint.py` | Emit embedded `zone` tokens (hatch fill, net, no-mask) alongside pads. New emit-time **structure validation** (required fields/children present) before serialize. |
| `export/symbol.py` | **Semantic pin names** (`Rx0…/Tx0…`, `Seg_0…`, `Ground`, `Shield`) replacing `Pin_N`. |
| `export/dxf.py` | New: geometry → DXF for mechanical/CAD handoff. |
| `gui/` | Preset dropdown per panel; JSON save/load; preview → PNG/SVG; per-field tooltips + inline invalid-field highlighting; toggles for the optional support-copper features. |
| `cli/` | `--params-json IN/OUT`; advisory flags (`--overlay-thickness`, `--ground-hatch`, `--guard-ring`, …); `--strict` extends to advisories. |
| `kicad_plugin/` | New: `pcbnew`/IPC Action Plugin that runs the engine and places the footprint into the open board. Ships separately from the standalone binary. |

---

## 3. Roadmap (phased, each independently verifiable)

> Verification discipline carries over from v1: every opt-in feature must prove **(a)** that with the feature *off*, output is byte-identical to the current golden files, and **(b)** that with it *on*, `kicad-cli pcb drc` is clean. Phases are largely independent and may be reordered; the sequence below front-loads the cheap, de-risking work.

| Phase | Goal | Done when |
|---|---|---|
| **6 — Robustness & hygiene** ✅ | Add `ruff` + `mypy` (+ coverage) gates to CI; emit-time S-expression structure validation in the exporters; reject non-finite (NaN/Inf) floats in param validation. | **Done:** ruff (lint + format, line-length 100), mypy, and pytest-coverage run in a new `ci.yml`; `validate_footprint` / `validate_symbol_lib` gate every serializer; `require_finite` rejects NaN/Inf in all three validators. No change to valid output; 383 tests green. |
| **7 — Quick wins (correctness + UX)** ✅ | Semantic symbol pin names; preset dropdown in each GUI panel; JSON parameter save/load (GUI + CLI); preview export to PNG/SVG; per-field tooltips + inline invalid-field highlighting; optional pin-name silk labels. | **Done:** semantic pins (`E*/GND`, `Rx*/Tx*`) and per-panel preset dropdowns were already shipped in v1 (verified). Added JSON save/load (CLI `--save-params` + `from-params` subcommand, GUI Save/Load buttons; byte-identical round-trip), preview PNG/SVG export, field tooltips, and inline field-outline validation. Optional silk pin-labels deferred — the symbol already carries the names. |
| **8 — Optional ground & guard copper** ✅ | New `geometry/zones.py` + footprint `zone` emission. Two opt-in, configurable features: **hatched ground fill** (opposite layer; configurable fill %, line width, pitch) and **guard / ESD ring** (configurable width, gap, mask-off, tied to a ground pin). Both **default off**. | **Done:** both features ship on slider/wheel/trackpad as embedded `zone`s tied to one thru-hole `GND` net-tie pad + a `GND` symbol pin (net wiring resolved → **GND-pin drop-in**, §6). Flat support fields per widget (D9) with shared defaults/validation in `params/support.py`; pure shapely outline builders in `geometry/zones.py` (D3 ground = the fab/courtyard grown by `ground_margin`, wheel hole punched; D5 guard = a broken band offset `guard_gap` outward, F.Mask aperture by default per D6); D7 thru-hole net-tie at a courtyard corner; D8 fab/courtyard grown to enclose the copper only when on. CLI flags (`--ground-hatch`/`--guard-ring` + knobs), GUI "Support copper" group, and preview layers added. Default-off output is **byte-identical** (asserted); each enabled feature is **DRC-clean in kicad-cli 10** via a board-level-lift gate (caveats below). All D1–D10 took the recommended option. 451 tests green. |
| **9 — Sensitivity & filtering advisories** ✅ | `overlay_thickness` + `overlay_er` params; advisory checks for electrode-vs-overlay sizing (Microchip: electrode ≥ finger + 2× overlay), Cp budget (≈30 pF self / 16 pF mutual), and recommended series-R value. Reuse the fab warn/`--strict` channel; optionally print recommendations on silk/`F.Fab`. | **Done:** new `params/advisory.py` (mirrors `fab.py`) returns per-widget `Advisory` items: the always-on **series-R** recommendation (560 Ω self / 2 kΩ mutual; §5.5), **overlay sizing** (self-cap transverse ≥ finger + 2·overlay for slider/wheel; the mutual trackpad — no finger param — uses the ~0.5–3 mm overlay window instead; §5.7), and a **parallel-plate Cp estimate** vs the 30 pF self / 16 pF mutual budgets (§5.10). Three shared, default-inert fields (`overlay_thickness` 0 = off, `overlay_er`, `board_thickness`) added per widget in `params/sensing.py` (mirrors `support.py`); CLI flags + `_report_advisories`; GUI overlay group + amber-banner/info-line wiring; `--strict` blocks on the actionable (sizing/Cp) advisories. Per the resolved §6 series-R question, the recommendation is **advisory-only plus a hidden `Series_R` symbol property** — no resistor copper in the footprint. Overlay params never change emitted geometry (asserted byte-identical for footprint + symbol). Silk/`F.Fab` printing deferred (the symbol already carries the note). 542 tests green. |
| **10 — Mutual-cap slider** ✅ | New `mutual-slider` widget reusing the trackpad diamond/bridge logic in a 1-D arrangement. CLI subcommand + GUI panel + preset(s) + tests. | **Done:** `MutualSliderParams` is a slider-flavoured façade over `TrackpadParams` (`to_trackpad()` maps `num_segments → num_cols`, `sense_rows → num_rows`); the trackpad's `MIN_LINES` guard was parameterized (`min_lines`, default unchanged) so `build_mutual_slider` reuses the diamond/neck/via-bridge engine with `min_lines=1` for the single sense row, returning a `MutualSliderGeometry` (a `TrackpadGeometry` subtype) — so the footprint/symbol exporters, live preview, and DRC harness are reused verbatim. `sense_rows` defaults to **1** (the canonical Microchip single-Y line; 2 = Infineon DSD). Registered in the serialize/advisory (mutual 2 kΩ)/fab dispatch, a `mutual-slider` CLI subcommand (`--num-segments` / `--length` / `--sense-rows` + diamond/bridge/via/support/sensing flags), and a GUI panel (appended to the widget switcher at index 3). Golden footprint+symbol + a kicad-cli DRC gate prove the two-layer bridges connect (`unconnected_items == []`); 607 tests green. |
| **11 — Button / keypad grid** ✅ | New `keypad` widget: parametric M×N array of discrete touch buttons (rect / circle / diamond shape), auto-spaced per overlay-thickness guidance. CLI subcommand + GUI panel + preset(s) + tests. | **Done:** `KeypadParams` is a standalone widget — an `R×C` grid of **discrete self-cap buttons**, one electrode = one custom pad = one `K*` pin (the *discrete* arm of the §6 open question; matrix-scanned row/col sharing is the trackpad's job and stays deferred). Three button shapes (`rect`/`circle`/`diamond`) via `build_keypad`, an `Electrode`-list geometry that reuses the shared electrode footprint/symbol exporters and the live preview verbatim (per-button `F.Fab` outlines; grid-bbox courtyard). `gap` is first-class geometry (default 4 mm = Microchip §1.2.2 self-cap separation); the overlay-aware `4 mm + overlay` separation and `3× overlay` button-size rules (TI) are enforced via the **advisory** channel, so — like every widget — the advisory-only overlay fields never change emitted geometry. Optional support copper works through the shared zone builder. A `keypad` CLI subcommand, a GUI panel (widget switcher index 4), three presets (numeric/round/compact, all shapes), golden footprint+symbol, and a kicad-cli DRC gate (each shape × grid size clearance-clean, with a sub-clearance negative control) all ship. 697 tests green. |
| **12 — DXF export** ✅ | `export/dxf.py`: geometry → DXF, wired into CLI (`--dxf`) and the GUI export menu. | **Done:** new `export/dxf.py` serialises any widget's geometry to an ASCII **DXF (R12/AC1009)** — hand-rolled like the S-expression emitter, so the runtime stays **Shapely-only** (no DXF library). Reuses the single-source-of-truth geometry: electrodes/diamonds/vias, the support copper (ground pour, guard ring, GND net-tie), and the grown fab/courtyard outlines, split onto footprint-style layers (`F.Cu`/`B.Cu`/`F.Fab`/`F.CrtYd`/`Vias`) in **millimetres**, with **Y negated** to a y-up CAD frame (matching KiCad's own board→DXF convention). Wired into every CLI generator + `from-params` via opt-in `--dxf` and a GUI **Export DXF…** button (byte-identical to the on-screen geometry). Round-trip proven by a tiny independent tag-stream reader (the analogue of the `sexpr` round-trip): structure, metric units, per-widget copper/outline counts, support-copper layering, and vertex-level geometry with the Y flip. 717 tests green. |
| **13 — KiCad Action Plugin (IPC)** | A `pcbnew`/IPC plugin that runs the engine and places the generated footprint into the **open board** — resolving v1's deferred "insert directly" question. Packaged for the KiCad Plugin Manager. | From inside KiCad 9/10, the plugin generates and drops a chosen widget into the current board; the placed footprint matches the standalone tool's output and passes DRC. |

---

## 4. Suggested grouping for delivery

- **Track A (cheap, do first):** Phases 6 + 7 — de-risk and polish before the heavier work; mostly independent commits.
- **Track B (highest domain value):** Phases 8 + 9 — the silent-failure-mode mitigations (ground, guarding, sizing). The largest new concept (zones) lands here.
- **Track C (reach):** Phases 10–13 — new sensors, formats, and integration. Each is self-contained and can ship on its own branch.

Per project etiquette (`CLAUDE.md`): one logical change per commit, land incrementally, branch off `main`.

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Embedded footprint `zone` tokens drift across KiCad 9/10/11 | Pin the `version` token (as v1 does); validate every zone-enabled output with `kicad-cli pcb drc` on both 9 and 10; isolate zone emission to one function. |
| **(Phase 8 caveat)** `kicad-cli pcb drc --refill-zones` does **not** refill footprint-*embedded* zones (only board-level ones), so a footprint zone never fills under the CLI | The DRC gate **lifts** each footprint zone onto a board on the `GND` net before refilling/checking; in-footprint loading is covered separately by `kicad-cli fp export svg`. The product ships zones inside the footprint as a drop-in (they fill once placed in KiCad). |
| **(Phase 8 caveat)** a baked `net_name` on a `net 0` zone **segfaults** `kicad-cli fp export svg` (net-index / net-name mismatch) | Library zones are emitted **net-less** (`net 0` / `net_name ""`, standard for footprint zones); KiCad assigns the net on the board via the net-tie pad + `GND` pin. Never bake a net name into a footprint zone. |
| Opt-in features silently change default output | Golden-file "feature-off ⇒ byte-identical" assertion is a required test for Phases 8–9 (see §3 verification rule). |
| Hatched-ground / guard-ring geometry breaks DRC (clearance, thermal relief) | Reuse the shipped `fab.py` clearance derivation to space fill from electrodes; negative-control test that an intentionally-too-close ring fails DRC. |
| Cp / sensitivity numbers are estimates, not measurements | Frame strictly as **advisories** (warn, never silently "correct"); cite the guideline source in the message; never block unless `--strict`. |
| IPC API surface changes (kicad-python / `kipy`) | The plugin is a thin placement wrapper; generation stays in the version-resilient text emitter, so an API break only affects placement, not output. |
| Scope creep across four tracks | Phases are independent and individually verifiable; ship per-branch; nothing here blocks the already-shipped v1. |

---

## 6. Open questions (resolve before/within the relevant phase)

- ~~**Series resistor representation**~~ — **Resolved (Phase 9): advisory + symbol note.** The recommended value (560 Ω self / 2 kΩ mutual) is reported in the CLI/GUI advisory channel and embedded as a hidden `Series_R` **property** on the emitted symbol (not a separate resistor unit, and no resistor copper in the footprint — a series R sits at the MCU, not the electrode).
- ~~**Ground/guard net wiring**~~ — **Resolved (Phase 8): GND-pin drop-in.** Support copper gets one **`GND`** symbol pin (numbered after the electrodes) + one thru-hole net-tie pad in the footprint; both zones tie to it and auto-connect when the pin is wired. No separate `Shield` pin and no manual zone-net assignment.
- ~~**Keypad addressing**~~ — **Resolved (Phase 11): discrete self-cap buttons (1 pin each).** Each button is its own electrode on its own pin — the simplest, most common keypad, matching the Phase 11 row's "discrete touch buttons / correct per-button pads/pins". A matrix-scanned variant (shared row/col pins) is electrically a mutual-cap grid — the trackpad already provides shared-row/col mutual sensing — so it is **deferred** rather than duplicated; it can return as a future phase if high-button-count pin-frugality is needed.
- **Plugin distribution** — bundle the IPC plugin with the standalone binary, or list it separately in the KiCad Plugin Manager (v1 deferred the Plugin Manager listing)? Decide in Phase 13.

---

## 7. Key references

Inherits v1's reference set ([`plan.md`](./plan.md) §7). New for v2:

- KiCad footprint `zone` token (embedded zones): <https://dev-docs.kicad.org/en/file-formats/sexpr-footprint/index.html>
- KiCad IPC API / kicad-python (`kipy`): <https://gitlab.com/kicad/code/kicad-python>
- ESCPT (DRC-aware touch **zones** precedent): <https://github.com/hanya/ESCPT>
- Overlay / Cp / sensitivity numbers: [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md) §§5.1, 5.5, 5.7, 5.10.
