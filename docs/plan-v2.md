# Touch Footprint Generator — v2 Roadmap (post-MVP)

**Status:** proposed. Compiled 2026-06-18. Builds on [`plan.md`](./plan.md) (Phases 0–5 **complete**: a feature-complete electrodes-only generator for sliders, wheels, and XY diamond trackpads, with a live GUI, vendor presets, fab-rule guards, and standalone binaries).

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
| **6 — Robustness & hygiene** | Add `ruff` + `mypy` (+ coverage) gates to CI; emit-time S-expression structure validation in the exporters; reject non-finite (NaN/Inf) floats in param validation. | CI fails on lint/type errors; a deliberately broken footprint node raises before serialize (tested); NaN/Inf params are rejected with a clear message (tested). No change to emitted output for valid inputs. |
| **7 — Quick wins (correctness + UX)** | Semantic symbol pin names; preset dropdown in each GUI panel; JSON parameter save/load (GUI + CLI `--params-json`); preview export to PNG/SVG; per-field tooltips + inline invalid-field highlighting; optional pin-name silk labels. | Symbols carry semantic names (asserted in tests, pins still 1:1 with pads); GUI round-trips a parameter set through JSON byte-faithfully; preview saves an image; each field has a hover hint; invalid fields highlight. |
| **8 — Optional ground & guard copper** | New `geometry/zones.py` + footprint `zone` emission. Two opt-in, configurable features: **hatched ground fill** (opposite layer; configurable fill %, line width, pitch) and **guard / ESD ring** (configurable width, gap, mask-off, tied to a ground pin). Both **default off**. | Default-off output is byte-identical to current golden files; each feature, when enabled on slider/wheel/trackpad, is DRC-clean in KiCad 9 **and** 10; GUI toggles + CLI flags work and preview them. |
| **9 — Sensitivity & filtering advisories** | `overlay_thickness` + `overlay_er` params; advisory checks for electrode-vs-overlay sizing (Microchip: electrode ≥ finger + 2× overlay), Cp budget (≈30 pF self / 16 pF mutual), and recommended series-R value. Reuse the fab warn/`--strict` channel; optionally print recommendations on silk/`F.Fab`. | Advisories surface as warnings (amber banner / CLI) and as `--strict` blocks; a known under-sized electrode triggers the sizing warning (tested); recommended Rseries appears in output. No copper pads added to the electrode footprint. |
| **10 — Mutual-cap slider** | New `mutual-slider` widget reusing the trackpad diamond/bridge logic in a 1-D arrangement. CLI subcommand + GUI panel + preset(s) + tests. | Generates a DRC-clean two-layer mutual-cap slider; previewed live; pins ↔ pads correct; golden-file + DRC tests pass. |
| **11 — Button / keypad grid** | New `keypad` widget: parametric M×N array of discrete touch buttons (rect / circle / diamond shape), auto-spaced per overlay-thickness guidance. CLI subcommand + GUI panel + preset(s) + tests. | Generates a DRC-clean M×N button grid with correct per-button pads/pins; spacing respects the guideline rule; previewed live; tests pass. |
| **12 — DXF export** | `export/dxf.py`: geometry → DXF, wired into CLI (`--dxf`) and the GUI export menu. | DXF opens in a mechanical viewer / CAD tool with correct geometry and units; round-trip sanity test passes. |
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
| Opt-in features silently change default output | Golden-file "feature-off ⇒ byte-identical" assertion is a required test for Phases 8–9 (see §3 verification rule). |
| Hatched-ground / guard-ring geometry breaks DRC (clearance, thermal relief) | Reuse the shipped `fab.py` clearance derivation to space fill from electrodes; negative-control test that an intentionally-too-close ring fails DRC. |
| Cp / sensitivity numbers are estimates, not measurements | Frame strictly as **advisories** (warn, never silently "correct"); cite the guideline source in the message; never block unless `--strict`. |
| IPC API surface changes (kicad-python / `kipy`) | The plugin is a thin placement wrapper; generation stays in the version-resilient text emitter, so an API break only affects placement, not output. |
| Scope creep across four tracks | Phases are independent and individually verifiable; ship per-branch; nothing here blocks the already-shipped v1. |

---

## 6. Open questions (resolve before/within the relevant phase)

- **Series resistor representation** — advisory + silk only (current plan), or also emit a series-R in the **symbol** (multi-unit / hierarchical)? Decide in Phase 9.
- **Ground/guard net wiring** — does the support copper get its own `Ground`/`Shield` symbol pin, or is it left as a named zone for the user to tie on the board? Decide in Phase 8.
- **Keypad addressing** — discrete self-cap buttons (1 pin each) only, or also a matrix-scanned variant (shared row/col pins) for high button counts? Decide in Phase 11.
- **Plugin distribution** — bundle the IPC plugin with the standalone binary, or list it separately in the KiCad Plugin Manager (v1 deferred the Plugin Manager listing)? Decide in Phase 13.

---

## 7. Key references

Inherits v1's reference set ([`plan.md`](./plan.md) §7). New for v2:

- KiCad footprint `zone` token (embedded zones): <https://dev-docs.kicad.org/en/file-formats/sexpr-footprint/index.html>
- KiCad IPC API / kicad-python (`kipy`): <https://gitlab.com/kicad/code/kicad-python>
- ESCPT (DRC-aware touch **zones** precedent): <https://github.com/hanya/ESCPT>
- Overlay / Cp / sensitivity numbers: [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md) §§5.1, 5.5, 5.7, 5.10.
