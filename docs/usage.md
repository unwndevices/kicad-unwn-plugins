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

Three generator subcommands — `slider`, `wheel`, `trackpad` — plus `from-params`
(regenerate from a saved parameter set) and `gui`. Run any with `--help` for the
full parameter list.

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
| `--save-params FILE` | Also write the resolved parameters as JSON (replay with `from-params`). |

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
captouch trackpad --num-rows 6 --num-cols 6 --mask-shape circle
captouch trackpad --num-rows 7 --num-cols 7 --mask-shape circle --clip-mode conform
captouch trackpad --mask-shape rrect --corner-radius 4
```

Trackpad-specific: `--num-rows` (Rx) × `--num-cols` (Tx), each 3–16 (≤100 nodes);
`--diamond-pitch`, `--diamond-gap`; `--bridge-width` (F.Cu neck / B.Cu strap) and
`--via-drill` / `--via-diameter` for the cross-layer bridge vias. Tx columns are
bridged on **B.Cu**, so the design needs two copper layers. The connecting necks
pinch tighter than the bulk diamond gap (~`gap/√2`) — that pinch is what the fab
guard and the DRC gate watch.

**Mask shape.** `--mask-shape {rect,rrect,circle}` sets the pad's outer outline
(default `rect`):

- `rrect` rounds the corners by `--corner-radius` (mm); works at any matrix size.
- `circle` clips the matrix to a disk of `--radius` (mm; default the inscribed
  `0.5·min(width,height)`). A circle needs a roughly **square** matrix
  (`num_rows ≈ num_cols`); an elongated one whose outer column the disk can't reach
  is rejected with an error pointing you at a larger radius or a squarer matrix.

The mask shapes the copper, the `F.Fab` outline, and the courtyard; it never
changes the `Rx`/`Tx` pin count or numbering.

**Clip mode.** `--clip-mode {inscribe,conform}` decides how a *curved* mask
(circle/rrect) treats the diamonds it crosses (no effect on `rect`):

- `inscribe` (default) keeps a diamond only when its **centre** is inside the
  mask, then clips — so rim diamonds are kept whole or dropped whole. The boundary
  is a chunky inscribed lattice, but every survivor stays ≥~half present, carries
  its bridge via, and bridges contiguously.
- `conform` clips **every** diamond/neck/strap to the mask boundary, so the copper
  edge follows the curve exactly (Azoteq AZD068 §6, Fig 6.3). Rim diamonds become
  cut **partial channels**. Bridges are placed only where the via centres still
  clear the cut edge, and any rim diamond a bridge can't reach is dropped, so the
  copper stays fully connected and DRC-clean.

Either way a curved mask shrinks some edge channels' electrode area. The generator
reports the channels left below **50 %** of their full area (Azoteq's rule of thumb
for disabling a channel in firmware):

```
$ captouch trackpad --num-rows 7 --num-cols 7 --mask-shape circle --clip-mode conform
wrote examples/CT_Trackpad.kicad_mod
wrote examples/CT_Trackpad.kicad_sym
  mutual-cap trackpad: 7x7 diamonds (7 Rx + 7 Tx, 49 nodes), …
  4 partial channel(s) under 50% of full electrode area (Azoteq AZD068 §6 — consider disabling these in firmware):
    - Rx1: 49% area remaining
    - Rx7: 49% area remaining
    - Tx1: 49% area remaining
    - Tx7: 49% area remaining
```

### Support copper (ground & guard, optional)

Every generator can add two **opt-in, default-off** board-support features
(guidelines §4.6, §5.1, §5.2). Both are emitted as embedded KiCad `zone`s tied to
a single **`GND`** net via one thru-hole net-tie pad plus a matching `GND` symbol
pin (numbered after the electrodes). With both off the output is **byte-identical**
to the electrode-only part.

| Flag | Meaning |
|---|---|
| `--ground-hatch` | Add a **hatched ground pour** on the opposite layer (`B.Cu`) — shields without the capacitive loading of a solid pour. |
| `--ground-margin MM` | How far the pour extends past the electrodes (default 2.0). |
| `--hatch-width MM` | Hatch copper-line width (default 0.18 = 7 mil). |
| `--hatch-pitch MM` | Hatch centre-to-centre pitch (default 1.14 = 45 mil); must exceed the line width. |
| `--guard-ring` | Add a grounded **guard / ESD ring** on the electrode layer (`F.Cu`), broken so it isn't a closed-loop antenna. |
| `--guard-width MM` | Ring band width (default 0.8). |
| `--guard-gap MM` | Gap from the electrodes to the ring (default 2.0). |
| `--guard-break MM` | Break in the ring (default 0.1). |
| `--guard-no-mask-open` | Keep solder mask over the ring (default: expose it through `F.Mask`, per §4.6). |

```sh
captouch slider   --preset infineon --ground-hatch
captouch trackpad --num-rows 6 --num-cols 6 --guard-ring
captouch wheel    --preset microchip --ground-hatch --guard-ring --hatch-pitch 1.0
```

On generation the added copper and the net-tie are reported:

```
$ captouch slider --ground-hatch --guard-ring
wrote examples/CT_Slider.kicad_mod
wrote examples/CT_Slider.kicad_sym
  …
  support copper: hatched ground on B.Cu (0.18 mm line / 1.14 mm pitch), mask-free guard/ESD ring on F.Cu (0.80 mm, 2.00 mm gap)
    tied to the GND pin (pad 5); assign the zone net to GND on your board
```

The zones ship **net-less** (a library footprint carries no net); KiCad assigns
the net when the footprint is placed, and the net-tie pad + `GND` symbol pin make
that **`GND`** the moment you wire the pin. See
[Using the output in KiCad](#using-the-output-in-kicad) for the one wiring step,
and the caveat under
[Validating with kicad-cli](#validating-with-kicad-cli) about refilling these
zones.

### Saving & loading parameters

Any generator can dump the **resolved** parameters it used as JSON with
`--save-params FILE`; `from-params` replays that file — picking the right widget
automatically — to regenerate byte-identical output:

```sh
captouch slider --preset infineon --num-segments 7 --save-params slider.json
captouch from-params slider.json -o build/    # regenerates the same .kicad_mod/.kicad_sym
```

`from-params` also accepts `-o/--out` and the fab-rule flags. The JSON is the same
format the GUI's **Save params…** / **Load params…** buttons read and write, so a
set saved from the CLI loads in the GUI and vice-versa.

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
- The trackpad panel has a **Mask** group — shape (rect / rrect / circle), a
  **clip mode** (inscribe / conform, active only for a curved mask), and a
  corner-radius (rrect) or radius (circle; *Auto* = inscribed) control — that
  reshapes the live preview. The status bar flags any channels a mask shrinks
  below 50 % area so you can disable them in firmware.
- Every panel has a **Support copper (optional)** group — a *Hatched ground pour
  (B.Cu)* checkbox with margin / hatch-width / pitch spins, and a *Guard / ESD ring
  (F.Cu)* checkbox with width / gap / break spins plus a mask-open toggle. Each
  feature's spins enable only when its checkbox is ticked; toggling either redraws
  the preview and adds the zone to the export. Both are off by default.
- The **preview** renders the *same* geometry the exporters serialise (WYSIWYG),
  with zoom/pan, **Fit**, and per-layer toggles (incl. `F.Cu`, `B.Cu`, vias for the
  trackpad, and the **Ground pour** / **Guard ring** support copper).
- A **Fab profile** selector re-checks the design live; any violation appears in a
  non-blocking amber banner under the preview.
- Every field carries a hover **tooltip**; an invalid value outlines the offending
  control (the same message shows in the status bar).
- **Save image…** exports the preview as a PNG (raster) or SVG (vector).
- **Save params… / Load params…** write or read the current parameters as JSON
  (Load switches to the matching widget); interchangeable with the CLI's
  `--save-params` / `from-params`.
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
   Rx/Tx (or segment) pin to your touch controller. By default the generator emits
   the **electrode only** — add board-level support (hatched ground, ESD ring,
   series resistors, escape routing) per your design.
4. **If you enabled support copper** ([above](#support-copper-ground--guard-optional)),
   there is one extra step: wire the part's **`GND`** pin to your ground net. The
   hatched pour, the guard ring, and the net-tie pad are all on that pin, so KiCad
   ties the zones to `GND` automatically — you don't assign the zone net by hand.
   The zones are emitted unfilled (a library footprint has no net to fill against);
   they fill once placed on the board. See the
   [refill caveat](#validating-with-kicad-cli) if you script `kicad-cli`.

The trackpad's Tx bridges live on `B.Cu`, so its board must have ≥2 copper layers;
so does the hatched ground pour.

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

**Caveat — refilling support-copper zones.** `kicad-cli pcb drc --refill-zones`
only refills **board-level** zones, *not* zones embedded inside a footprint, so it
won't fill the ground pour / guard ring while they sit in the `.kicad_mod`. They
fill correctly once the footprint is placed on a board (open the PCB and press
<kbd>B</kbd>, or let DRC refill them there). The test suite verifies the real fill
by **lifting** each footprint zone onto a board on the `GND` net before running
DRC; loading-in-KiCad is covered separately by `kicad-cli fp export svg`. (Relatedly,
the zones are emitted with no baked net name — a `net_name` on a `net 0` zone
crashes `fp export svg` — so never hand-edit one in.)
