# Using kicad-captouch

A practical guide to generating capacitive-touch footprints and symbols. For the
architecture and roadmap see [`plan.md`](./plan.md); for the numbers behind the
parameters see [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md).

- [Install](#install)
- [Quick start](#quick-start)
- [The CLI](#the-cli)
- [Fab-rule guards](#fab-rule-guards)
- [The GUI](#the-gui)
- [Using the output in KiCad](#using-the-output-in-kicad)
- [Standalone binary](#standalone-binary)
- [Validating with kicad-cli](#validating-with-kicad-cli)

---

## Install

The engine + CLI need only **Shapely**; the GUI adds **PySide6**.

```sh
pip install -e .            # engine + CLI
pip install -e '.[gui]'     # add the desktop GUI
```

Non-Python users can instead grab a **[standalone binary](#standalone-binary)** —
one file, no Python install required.

Supported KiCad: **9.0 and 10.0** (the emitted footprint/symbol S-expression
format is accepted by both).

## Quick start

```sh
captouch slider                       # 4-segment chevron slider → ./examples
captouch wheel  --preset st_rotary    # 5-segment rotary wheel
captouch trackpad --num-rows 4 --num-cols 5   # 4×5 mutual-cap diamond pad
captouch gui                          # live-preview desktop app
```

Each command writes two files into the output directory (default `./examples`):
`<name>.kicad_mod` (footprint) and `<name>.kicad_sym` (matching symbol).

## The CLI

Three generator subcommands — `slider`, `wheel`, `trackpad` — plus `gui`. Run any
with `--help` for the full parameter list.

### Options shared by every generator

| Option | Meaning |
|---|---|
| `-o, --out DIR` | Output directory (default `./examples`). |
| `--name NAME` | Base name for the `.kicad_mod` / `.kicad_sym` pair. |
| `--preset KEY` | Start from a vendor preset, then apply any other flags on top. |
| `--list-presets` | List the presets for that widget and exit. |
| `--fab-profile {default,jlcpcb,oshpark}` | Fab capability to check against (default `default`). |
| `--strict` | Treat fab-rule violations as a hard error (refuse to generate). |
| `--list-fab-profiles` | Print the fab profiles and their limits, and exit. |

`--version` prints the version; flags left unset fall back to the preset (or the
built-in defaults).

### Slider

```sh
captouch slider --shape interdigitated --num-segments 6 --air-gap 0.5
captouch slider --preset infineon
```

Key flags: `--shape {rectangular,chevron,interdigitated}`, `--num-segments`,
`--segment-width`/`--segment-height`, `--air-gap`, `--finger-diameter`,
`--num-fingers`, `--tooth-depth`, `--end-dummies`, `--corner-radius`,
`--tip-radius`. Segment width `W` is derived from the finger
(`W = finger − 2·gap`) so Infineon's `W + 2A = finger` rule holds; pass
`--relax-finger-constraint` to waive that check. Chevron tips are rounded by
`--tip-radius` (default 0.15 mm) for ESD/etch relief — set `0` for sharp tips.

### Wheel

```sh
captouch wheel --preset microchip --num-segments 6
```

Wheel-specific: `--ring-width` (radial width) and `--arc-resolution` (polyline
segments per 90° of arc). The mean radius — and therefore the outer and
centre-hole diameters — is **derived from the pitch** and printed on generation.
Wheels are continuous, so there are no end dummies.

### Trackpad

```sh
captouch trackpad --preset infineon --num-rows 6 --num-cols 6
```

Trackpad-specific: `--num-rows` (Rx) × `--num-cols` (Tx), each 3–16 (≤100 nodes);
`--diamond-pitch`, `--diamond-gap`; `--bridge-width` (F.Cu neck / B.Cu strap) and
`--via-drill` / `--via-diameter` for the cross-layer bridge vias. Tx columns are
bridged on **B.Cu**, so the design needs two copper layers. The connecting necks
pinch tighter than the bulk diamond gap (~`gap/√2`) — that pinch is what the fab
guard and the DRC gate watch.

## Fab-rule guards

The design constraints keep an electrode *electrically* sensible; the fab guards
add a *manufacturability* check. After building the geometry, the generator
derives the tightest copper width, copper clearance, drill, and annular ring it
will produce and compares them to a **fab profile**:

```
$ captouch trackpad --list-fab-profiles
default   conservative generic 2-layer (~6 mil; safe with any fab)
          track 0.15 clearance 0.15 drill 0.3 annular 0.15 mm
jlcpcb    JLCPCB 2-layer standard (~5 mil track/space, 0.2 mm drill)
          track 0.127 clearance 0.127 drill 0.2 annular 0.13 mm
oshpark   OSH Park 2-layer (6 mil track/space, 10 mil drill)
          track 0.1524 clearance 0.1524 drill 0.254 annular 0.1524 mm
```

By default a violation is a **warning** — the files are still written:

```
$ captouch trackpad --fab-profile oshpark
wrote examples/CT_Trackpad.kicad_mod
wrote examples/CT_Trackpad.kicad_sym
  mutual-cap trackpad: 4x5 diamonds …
warning: 1 fab-rule issue(s) vs the 'oshpark' profile (…):
  - bridge via annular ring = 0.150 mm is below the annular ring minimum 0.152 mm
```

Add `--strict` to fail instead (exit code 3, nothing written) — useful in CI:

```
$ captouch trackpad --fab-profile oshpark --strict ; echo $?
error: 1 fab-rule issue(s) vs the 'oshpark' profile (…):
  - bridge via annular ring = 0.150 mm is below the annular ring minimum 0.152 mm
  refusing to generate under --strict — relax the geometry, pick a finer --fab-profile, or drop --strict
3
```

The bundled profiles are **representative** of common 2-layer capabilities, not a
contract — always confirm against the board house you order from. (There is also
an absolute physical floor — e.g. a via must always carry a minimum annular ring —
enforced as a hard error regardless of profile.)

## The GUI

```sh
captouch gui            # or: captouch-gui
```

- A **Widget** selector swaps the slider / wheel / trackpad parameter panel.
- A **Preset** menu loads vendor starting points into the form.
- The **preview** renders the *same* geometry the exporters serialise (WYSIWYG),
  with zoom/pan, **Fit**, and per-layer toggles (incl. `F.Cu`, `B.Cu`, and vias
  for the trackpad).
- A **Fab profile** selector re-checks the design live; any violation appears in a
  non-blocking amber banner under the preview.
- **Export footprint + symbol…** writes the pair for the geometry on screen.

`captouch gui --check` constructs the app and exits immediately — a headless smoke
test (used to verify the packaged binary).

## Using the output in KiCad

Each run produces a footprint and a matching symbol whose pins map 1:1 to the
pads.

1. **Footprint** — put `<name>.kicad_mod` in a `.pretty` directory and add that
   directory in *Preferences → Manage Footprint Libraries* (or drop it into an
   existing library folder).
2. **Symbol** — add `<name>.kicad_sym` in *Preferences → Manage Symbol
   Libraries*.
3. Place the symbol in the schematic, assign the footprint, and route each
   Rx/Tx (or segment) pin to your touch controller. The generator emits the
   **electrode only** — add board-level support (hatched ground, ESD ring,
   series resistors, escape routing) per your design.

The trackpad's Tx bridges live on `B.Cu`, so its board must have ≥2 copper layers.

## Standalone binary

For users without Python, build a single self-contained executable with
PyInstaller:

```sh
pip install -e '.[packaging]'
packaging/build-binary.sh            # Linux / macOS → dist/captouch
```

PyInstaller cannot cross-compile, so each OS builds its own binary. The
`.github/workflows/build.yml` matrix builds and smoke-tests on Linux, macOS, and
Windows and uploads the artifacts (triggered on `v*` tags or on demand). The
bundled binary runs the whole CLI, and `captouch gui` launches the preview app.

## Validating with kicad-cli

If `kicad-cli` is on `PATH`, the test suite renders every generated footprint and
symbol and runs **DRC** on a generated board:

```sh
PYTHONPATH=src python3 -m pytest        # unit + golden-file + kicad-cli gates
```

The `kicad-cli` and GUI tests skip automatically when their tools are absent.
