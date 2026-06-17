# kicad-captouch

A standalone, vendor-agnostic desktop tool that **parametrically generates capacitive-touch
interface footprints** — sliders, wheels, and XY diamond pads — for KiCad, with a live visual
preview. Each widget is emitted as a ready-to-use **footprint (`.kicad_mod`)** plus a matching
**schematic symbol (`.kicad_sym`)**, written directly as KiCad S-expressions (no dependency on
KiCad's in-flux scripting API).

License: **GPL-3.0-or-later**. See [`docs/plan.md`](docs/plan.md) for the architecture, stack, and
roadmap, and the companion research in [`docs/`](docs).

## Status — Phase 3 (wheel)

Sliders **and wheels** are done, with a desktop GUI. The engine — `params` → `geometry` (Shapely) →
`export` — generates **rectangular, chevron, and interdigitated** electrodes for two widgets:

- **Linear sliders** — a row of electrodes with grounded end-dummy segments.
- **Wheels (rotary sliders)** — the slider construction bent into a continuous annulus around a
  centre keep-out hole; the mean radius is derived from the pitch
  (`circumference = num_segments × (W + gap)`), arcs are tessellated to polylines (KiCad custom-pad
  polygons can't hold arcs), and there are no end dummies.

Both enforce the Infineon `W + 2A = finger_diameter` constraint and emit a footprint plus a matching
symbol whose pins map 1:1 to the pads, in the **KiCad 9.0** format (footprint `version 20241229`,
symbol lib `version 20241209`) that both KiCad 9 and 10 accept. All three slider and wheel shapes are
**DRC-clean** in KiCad 10.

The **PySide6 GUI** wraps the same engine: a slider/wheel selector swaps a parameter panel (with
vendor presets) that drives a live `QGraphicsView` preview (zoom/pan, layer toggles) rendering the
*same* geometry the exporters serialise — so the preview is byte-faithful to the exported copper —
plus one-click export of the footprint + symbol.

Install (Shapely is the only runtime dependency; the GUI adds PySide6):

```sh
pip install -e .          # engine + CLI (or: pip install shapely)
pip install -e '.[gui]'   # add the PySide6 desktop GUI
```

### Launch the GUI

```sh
captouch gui              # or: captouch-gui
```

### Generate a slider

```sh
# defaults: 4-segment chevron slider, W derived from an 8 mm finger
captouch slider --out examples --name CT_Slider

# from a vendor preset, overriding a couple of parameters
captouch slider --preset infineon --shape interdigitated --num-segments 6

captouch slider --list-presets        # infineon / microchip / azoteq
captouch slider --help                # full parameter list
```

Key parameters: `--shape {rectangular,chevron,interdigitated}`, `--num-segments`,
`--segment-width`/`--segment-height`, `--air-gap`, `--finger-diameter`, `--num-fingers`,
`--tooth-depth`, `--end-dummies`, `--corner-radius`. Segment width is derived from the finger
diameter unless given; `--relax-finger-constraint` waives the `W + 2A` check.

### Generate a wheel

```sh
# defaults: 5-segment chevron wheel, radius derived from the pitch
captouch wheel --out examples --name CT_Wheel

# from a vendor preset, overriding the segment count
captouch wheel --preset st_rotary --num-segments 6

captouch wheel --list-presets         # st_rotary / microchip / infineon
captouch wheel --help                 # full parameter list
```

Wheel-specific parameters: `--ring-width` (radial width), `--arc-resolution` (circle tessellation,
segments per 90°). The outer diameter and centre-hole diameter are **derived** from the pitch and
ring width and printed on generation. Wheels are continuous, so there are no end dummies.

### Tests

```sh
PYTHONPATH=src python3 -m pytest        # unit + golden-file + kicad-cli gates
```

The `kicad-cli` tests (footprint/symbol render, and **DRC-clean** on a generated test board) run
automatically when `kicad-cli` is on `PATH`, and are skipped otherwise. The GUI tests run headless
on Qt's `offscreen` platform (no display needed) and are skipped when PySide6 is absent. The Phase-0
format spike is still emitted by `captouch spike`.
