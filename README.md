# kicad-captouch

A standalone, vendor-agnostic desktop tool that **parametrically generates capacitive-touch
interface footprints** — sliders, wheels, and XY diamond pads — for KiCad, with a live visual
preview. Each widget is emitted as a ready-to-use **footprint (`.kicad_mod`)** plus a matching
**schematic symbol (`.kicad_sym`)**, written directly as KiCad S-expressions (no dependency on
KiCad's in-flux scripting API).

License: **GPL-3.0-or-later**. See [`docs/plan.md`](docs/plan.md) for the architecture, stack, and
roadmap, and the companion research in [`docs/`](docs).

## Status — Phase 5 (polish & distribution)

Sliders, wheels, **and XY diamond trackpads** are done, with a desktop GUI, **vendor-pinned presets**,
**fab-rule guards**, and a **standalone binary**. The engine — `params` → `geometry` (Shapely) →
`export` — generates three widgets:

- **Linear sliders** — a row of rectangular / chevron / interdigitated electrodes with grounded
  end-dummy segments.
- **Wheels (rotary sliders)** — the slider construction bent into a continuous annulus around a
  centre keep-out hole; the mean radius is derived from the pitch
  (`circumference = num_segments × (W + gap)`), arcs are tessellated to polylines (KiCad custom-pad
  polygons can't hold arcs), and there are no end dummies.
- **XY diamond trackpads** — a **mutual-capacitance** `R×C` diamond matrix on **two copper layers**:
  Rx rows run continuous on `F.Cu` while Tx columns are **bridged on `B.Cu` through thru-hole vias**
  at every crossing, with **half-diamond edge termination**. `R + C` pins resolve `R·C` interpolated
  nodes. The diamond half-diagonal is derived from the pitch and gap so every facing edge keeps the
  nominal clearance.

Sliders and wheels enforce the Infineon `W + 2A = finger_diameter` constraint; every widget emits a
footprint plus a matching symbol whose pins map 1:1 to the pads, in the **KiCad 9.0** format
(footprint `version 20241229`, symbol lib `version 20241209`) that both KiCad 9 and 10 accept — all
**DRC-clean** in KiCad 10 (the trackpad's via bridges verified connected via DRC, not just assumed).

The **PySide6 GUI** wraps the same engine: a slider/wheel/trackpad selector swaps a parameter panel
(with vendor presets) that drives a live `QGraphicsView` preview (zoom/pan, layer toggles — including
distinct `F.Cu`, `B.Cu`, and via layers for the trackpad) rendering the *same* geometry the exporters
serialise — so the preview is byte-faithful to the exported copper — plus one-click export of the
footprint + symbol.

A full **[usage guide](docs/usage.md)** covers install, the CLI, fab profiles, the GUI, importing into
KiCad, and building the binary.

Install (Shapely is the only runtime dependency; the GUI adds PySide6):

```sh
pip install -e .          # engine + CLI (or: pip install shapely)
pip install -e '.[gui]'   # add the PySide6 desktop GUI
```

Non-Python users can build a single self-contained executable instead — see
[Standalone binary](#standalone-binary).

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
`--tooth-depth`, `--end-dummies`, `--corner-radius`, `--tip-radius`. Segment width is derived from
the finger diameter unless given; `--relax-finger-constraint` waives the `W + 2A` check.

Chevron tooth-tips are acute and would otherwise etch to fab-resolution copper points, so they are
rounded for ESD relief by `--tip-radius` (default 0.15 mm, chevron-only); `--corner-radius` adds
extra rounding to every shape. Set `--tip-radius 0` to keep sharp tips.

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
segments per 90°); it also takes `--corner-radius` / `--tip-radius` like the slider. The outer
diameter and centre-hole diameter are **derived** from the pitch and ring width and printed on
generation. Wheels are continuous, so there are no end dummies.

### Generate a trackpad

```sh
# defaults: 4x5 mutual-cap diamond matrix, 5 mm pitch
captouch trackpad --out examples --name CT_Trackpad

# from a vendor preset, overriding the matrix size
captouch trackpad --preset infineon --num-rows 6 --num-cols 6

captouch trackpad --list-presets      # infineon / microchip / compact
captouch trackpad --help              # full parameter list
```

Trackpad parameters: `--num-rows` (Rx sense lines) `×` `--num-cols` (Tx drive lines), each 3–16;
`--diamond-pitch` (row/column centre spacing) and `--diamond-gap` (copper-to-copper gap);
`--bridge-width` (the F.Cu neck / B.Cu strap width) and `--via-drill` / `--via-diameter` for the
cross-layer bridge vias. The Tx columns are bridged on `B.Cu` so the design needs **two copper
layers**. Note the connecting necks pinch tighter than the bulk diamond gap (~`gap/√2`), as in any
diamond pattern — that pinch is what the DRC gate checks.

### Fab-rule guards

After building the geometry, every generator checks the tightest copper width, clearance, drill, and
annular ring it will produce against a **fab profile** (`--fab-profile {default,jlcpcb,oshpark}`,
default `default`; `--list-fab-profiles` prints them). A violation is a non-blocking **warning** by
default — the files are still written; `--strict` promotes it to a hard error (exit 3, nothing
written) for CI. The GUI shows the same check live, in an amber banner under the preview. The bundled
profiles are representative of common 2-layer capabilities — confirm against your own board house.

```sh
captouch trackpad --fab-profile oshpark            # warns: via annular ring below the floor
captouch trackpad --fab-profile oshpark --strict   # refuses to generate (exit 3)
```

### Standalone binary

For users without Python, PyInstaller freezes the CLI + GUI into one file:

```sh
pip install -e '.[packaging]'
packaging/build-binary.sh        # Linux / macOS → dist/captouch (captouch gui launches the app)
```

PyInstaller can't cross-compile, so each OS builds its own binary; the
[`build-binaries` CI workflow](.github/workflows/build.yml) builds and smoke-tests on
Linux/macOS/Windows and uploads the artifacts.

### Tests

```sh
PYTHONPATH=src python3 -m pytest        # unit + golden-file + kicad-cli gates
```

The `kicad-cli` tests (footprint/symbol render, and **DRC-clean** on a generated test board) run
automatically when `kicad-cli` is on `PATH`, and are skipped otherwise. The GUI tests run headless
on Qt's `offscreen` platform (no display needed) and are skipped when PySide6 is absent. The Phase-0
format spike is still emitted by `captouch spike`.
