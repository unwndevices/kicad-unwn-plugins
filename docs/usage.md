# Using kicad-captouch

A practical guide to generating capacitive-touch footprints and symbols. For the
architecture and roadmap see [`plan.md`](./plan.md); for the numbers behind the
parameters see [`capacitive-touch-design-guidelines.md`](./capacitive-touch-design-guidelines.md).

- [Install](#install)
- [Quick start](#quick-start)
- [The CLI](#the-cli)
- [Fab-rule guards](#fab-rule-guards)
- [The GUI](#the-gui)
- [DXF export](#dxf-export)
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
captouch mutual-slider --num-segments 6   # 6-node mutual-cap (CSX) diamond slider
captouch wheel  --preset st_rotary    # 5-segment rotary wheel
captouch trackpad --num-rows 4 --num-cols 5   # 4×5 mutual-cap diamond pad
captouch trackpad --panel-width 300 --panel-height 200  # or size from the overall pad
captouch keypad --num-rows 4 --num-cols 3     # 4×3 discrete self-cap button grid
captouch gui                          # live-preview desktop app
```

Each command writes two files into the output directory (default `./examples`):
`<name>.kicad_mod` (footprint) and `<name>.kicad_sym` (matching symbol). Add
`--dxf` for an extra `<name>.dxf` mechanical drawing (see [DXF export](#dxf-export)).

## The CLI

Five generator subcommands — `slider`, `mutual-slider`, `wheel`, `trackpad`,
`keypad` — plus `from-params` (regenerate from a saved parameter set) and `gui`.
Run any with `--help` for the full parameter list.

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
| `--dxf` | Also write `<name>.dxf`, a mechanical / CAD-handoff drawing of the same geometry. |

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
Or size the strip by its overall `--length` instead of `--num-segments` (see
[Design from overall size](#design-from-overall-size)).

### Wheel

```sh
captouch wheel --preset microchip --num-segments 6
captouch wheel --shape spiral --spiral-angle 45
```

Wheel-specific: `--ring-width` (radial width) and `--arc-resolution` (polyline
segments per 90° of arc). The mean radius — and therefore the outer and
centre-hole diameters — is **derived from the pitch** and printed on generation.
Wheels are continuous, so there are no end dummies. Or size the ring by its target
`--outer-diameter` instead of `--num-segments` (see
[Design from overall size](#design-from-overall-size)).

The boundary `--shape` is `{rectangular,chevron,interdigitated,spiral}`. The
wheel-only `spiral` is an iPod-style swirl: each toothless electrode boundary
twists by `--spiral-angle` degrees (default 30) from the centre hole outward, so
adjacent electrodes interleave by angle. `0` degenerates to straight radial bars;
`num-fingers`/`tooth-depth` are ignored for it. `--spiral-angle` is capped at 90°
(a quarter-turn); a steep twist that pinches the electrode into acute outer-edge
copper slivers raises a geometry-aware advisory (warned by default, refused under
`--strict`) — ease it by reducing `--spiral-angle`, widening `--ring-width`, or
adding segments.

### Trackpad

```sh
captouch trackpad --preset infineon --num-rows 6 --num-cols 6
captouch trackpad --num-rows 6 --num-cols 6 --mask-shape circle
captouch trackpad --num-rows 7 --num-cols 7 --mask-shape circle --clip-mode conform
captouch trackpad --mask-shape rrect --corner-radius 4
```

Trackpad-specific: `--num-rows` (Rx) × `--num-cols` (Tx), each ≥ 2 with no upper
cap by default (3–16 / ≤100 nodes is AT11849's *recommendation* for a touch
surface, not a hard limit, so large pads are allowed — but see
[Device profiles](#device-profiles-iqs550) to enforce a specific chip's limit);
`--diamond-pitch`, `--diamond-gap`; `--bridge-width` (F.Cu neck / B.Cu strap) and
`--via-drill` / `--via-diameter` for the cross-layer bridge vias. Tx columns are
bridged on **B.Cu**, so the design needs two copper layers. The connecting necks
pinch tighter than the bulk diamond gap (~`gap/√2`) — that pinch is what the fab
guard and the DRC gate watch. To size from the panel instead of a count, use
`--panel-width`/`--panel-height` (see
[Design from overall size](#design-from-overall-size)).

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

#### Device profiles (IQS550)

By default the trackpad is device-agnostic and only checks the AZD068 *layout*
rules. `--device iqs550` layers the **Azoteq IQS550** (IQS5xx-B000) controller's
hard channel caps on top: **≤ 10 Rx rows, ≤ 15 Tx columns, ≤ 150 nodes** (the
widths of the chip's Rx/Tx mapping registers — datasheet §5.1.3; Rx and Tx are
not interchangeable, which is exactly the tool's fixed `Rx = rows` / `Tx = cols`
topology). A matrix that exceeds the envelope is rejected before anything is
written. The `iqs550` **preset** is the ADR-style circular sensor: a 10 × 10
diamond grid inscribed into a disk with `conform` clipping (rim diamonds cut to
the curve), i.e. the "inscribed grid, not a masked rectangle" pad.

```sh
captouch trackpad --preset iqs550                      # 10×10 conform circle, caps applied
captouch trackpad --device iqs550 --num-rows 8 --num-cols 12 --mask-shape circle --clip-mode conform
```

**Sensor-config export.** `--iqs550-config FILE` also writes a firmware-ready C
header carrying the chip's `Total Rx` / `Total Tx` and the **per-node
Active-channels disable map** — the individual Rx×Tx crossings the circular
boundary cut below 50 % of their electrode area (datasheet §5.1.2 *Individual
Channel Disabling*; AZD068 §6). This is finer-grained than the per-line partial
report above: it disables individual *nodes*, not whole rows/columns.

```sh
$ captouch trackpad --preset iqs550 --iqs550-config pad_iqs550.h
wrote pad_iqs550.h
  IQS550 config: Total Rx=10 Tx=10, 20 of 100 node(s) disabled in the Active-channels map
  …
```

The header packs the 30-byte Active-channels block (15 Tx words, high byte first;
bit *r* = Rx *r*, `1` = enabled — datasheet §8.10.5) as a `uint8_t[30]` array,
draws the enabled/disabled grid in a comment, and carries two caveats worth
heeding: **verify the byte/bit order against AZD070** (the Programming &
Data-Streaming Guide) before flashing, and the bitmap assumes the **identity
Rx/Tx mapping** — if you route the footprint pads to different chip pins, set the
mapping registers (`0x063F` / `0x0649`) and permute the bits to match. Per-channel
ATI then normalises the smaller rim electrodes that remain enabled.

### Mutual slider

```sh
captouch mutual-slider --num-segments 6
captouch mutual-slider --preset microchip
captouch mutual-slider --preset dual          # dual-row, stronger mutual signal
captouch mutual-slider --length 60            # size from an overall length
```

A **mutual-capacitance (CSX)** slider senses position from the mutual coupling at
each drive×sense crossing instead of a per-segment self-capacitance. Geometrically
it is a diamond [trackpad](#trackpad) collapsed to a single sense row: one
continuous F.Cu **Rx** sense line spanning N B.Cu-bridged **Tx** drive electrodes,
so an N-node slider needs only **N + 1 pins** (Microchip AN2934 §2.4, "a single Y
line spans multiple X lines"). It therefore shares the trackpad's diamond, neck,
and via-bridge mechanics — and, like the trackpad, needs **two copper layers**.

Mutual-slider-specific: `--num-segments` (Tx drive electrodes = position nodes,
≥ 3), `--sense-rows {1,2}` (1 = a single sense line; 2 = a dual-row layout for a
stronger mutual signal, Infineon "Dual Solid Diamond"), `--diamond-pitch`,
`--diamond-gap`, `--bridge-width`, `--via-drill`/`--via-diameter`. Or size the
strip by its overall `--length` instead of `--num-segments` (see
[Design from overall size](#design-from-overall-size)). The symbol records the
**2 kΩ** mutual-cap series-R recommendation; the pins are `Rx1` (sense, left) and
`Tx1…TxN` (drive, right).

### Keypad

```sh
captouch keypad --num-rows 4 --num-cols 3                 # a 4×3 button grid
captouch keypad --preset numeric                          # telephone/calculator layout
captouch keypad --preset round                            # round macro pad
captouch keypad --num-rows 2 --num-cols 4 --button-shape diamond --button-size 9
```

A **keypad** is an `R×C` array of **discrete self-capacitance buttons** — each
button is its own sensed electrode on its own pin (no interpolation, no shared
rows/columns; that is the [trackpad](#trackpad)'s job), so the footprint is one
custom pad per button and the symbol one `K1…KN` pin per button, numbered
row-major (top row first, left to right). It is single-layer and needs no vias.

Keypad-specific: `--num-rows`/`--num-cols` (buttons per axis, ≥ 1), `--button-shape`
`{rect,circle,diamond}` (square / round / square-rotated-45°), `--button-size` (the
square side / circle diameter / diamond diagonal), `--gap` (button-to-button
edge-to-edge separation), and `--corner-radius` (ESD rounding for rect/diamond).
The default `--gap` is **4 mm** — the Microchip AN2934 §1.2.2 self-cap separation
rule "4 mm + cover" for a bare board; when an `--overlay-thickness` is given, the
advisory channel flags a gap below `4 mm + overlay` or a button below `3× overlay`
(TI rule). The symbol records the **560 Ω** self-cap series-R recommendation.

### Design from overall size

When you know the **overall size** the interface has to fit (an enclosure cutout,
say) rather than an element count, size it directly and let the generator derive
the count from the pitch — the pitch is never stretched, so the elements stay the
right size for the finger:

```sh
captouch slider        --length 100                    # a 100 mm strip
captouch mutual-slider --length 80                     # an 80 mm mutual-cap strip
captouch wheel         --outer-diameter 50             # a 50 mm wheel
captouch trackpad --panel-width 300 --panel-height 200 # a 300×200 mm XY pad
```

- **Slider** / **mutual-slider** (`--length`) and **wheel** (`--outer-diameter`):
  the element count is rounded to best match the target; the achieved length /
  diameter lands within about half a pitch (sliders) / one pitch (wheel) of the
  target and is printed on generation. Each is mutually exclusive with
  `--num-segments`.
- **Trackpad** (`--panel-width` / `--panel-height`, given together, mutually
  exclusive with `--num-rows`/`--num-cols`): the row/column counts are
  `round(dimension / pitch)`, and the **outline is pinned to exactly the requested
  size**. Where the diamond lattice overflows the outline its rim is trimmed (clean
  box cuts → partial edge channels); where it underflows, the rim terminates in
  clean half-diamonds and the surplus is left as an empty margin out to the outline.

In the GUI each panel has a matching **"Design from overall size"** checkbox that
reveals the target field(s) and shows the derived element count live.

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

### Sensitivity & filtering advisories (optional)

Every generator also runs a set of **electrical** design advisories (guidelines
§§5.5/5.7/5.10) — the counterpart to the [fab-rule guards](#fab-rule-guards), but
about sensitivity rather than manufacturability. They print as guidance after
generation and **never change the emitted geometry**.

| Flag | Meaning |
|---|---|
| `--overlay-thickness MM` | Front-panel overlay thickness. `0`/unset = *no overlay specified* → the overlay-dependent advisories stay off. |
| `--overlay-er ER` | Overlay relative permittivity εr (acrylic ~3, glass ~8). |
| `--board-thickness MM` | FR-4 substrate thickness used for the parasitic-Cp estimate (default 1.6). |

The checks:

- **Series resistor** (always): the recommended value — **560 Ω** self-cap
  (slider/wheel) or **2 kΩ** mutual-cap (trackpad) — placed within ~10 mm of the
  *MCU* pin (Infineon AN85951). It is also embedded in the symbol as a hidden
  **`Series_R`** property, so the guidance rides along with the part. No resistor
  is added to the electrode footprint — a series R belongs at the controller.
- **Electrode vs overlay sizing** (when `--overlay-thickness` is set): a self-cap
  electrode's transverse dimension should be ≥ `finger + 2·overlay`; a mutual-cap
  trackpad's overlay should sit in the ~0.5–3 mm window (§5.7).
- **Parasitic Cp budget**: a per-channel parallel-plate *estimate* vs ~30 pF
  self / ~16 pF mutual (Microchip AT09363, §5.10). An order-of-magnitude figure.

Like the fab guards these are warnings by default; `--strict` promotes the
**actionable** ones (sizing, Cp over budget) to a hard block (exit 3). The series-R
recommendation and the sensitivity note are informational and never block.

```
$ captouch slider --segment-height 8 --overlay-thickness 2
…
advisory: 3 design advisory(ies) (guidelines §§5.5/5.7/5.10):
  - recommend a 560 Ω series resistor on each sense line, placed within ~10 mm of the MCU pin …
  - segment height 8.00 mm is below the finger + 2·overlay minimum 12.00 mm … Widen it or thin the overlay
  - overlay: 2.00 mm, εr 3.0 (εr/thickness ≈ 1.5 mm⁻¹; signal ∝ εr/thickness) …
```

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

- A **Widget** selector swaps the slider / wheel / trackpad / mutual-slider /
  keypad parameter panel.
- A **Preset** menu loads vendor starting points into the form.
- Each sizing-capable panel has a **"Design from overall size"** checkbox (length /
  outer diameter / panel width×height) that derives the element count from the pitch
  and shows it live — the same sizing as the CLI `--length` / `--outer-diameter` /
  `--panel-*`.
- The mutual-slider panel combines that length sizing with the diamond / bridge /
  via knobs and a **sense rows** (1 single / 2 dual) control.
- The keypad panel has a grid size, a button **shape** (rect / circle / diamond),
  size, separation, and corner-radius (disabled for a circle).
- The trackpad panel has a **Controller** selector (generic / `iqs550`) that
  enforces the chosen chip's channel caps (an over-cap matrix outlines the row/col
  field), and a **Mask** group — shape (rect / rrect / circle), a **clip mode**
  (inscribe / conform, active only for a curved mask), and a corner-radius (rrect)
  or radius (circle; *Auto* = inscribed) control — that reshapes the live preview.
  The status bar flags any channels a mask shrinks below 50 % area so you can
  disable them in firmware, and echoes the active device's caps.
- Every panel has a **Support copper (optional)** group — a *Hatched ground pour
  (B.Cu)* checkbox with margin / hatch-width / pitch spins, and a *Guard / ESD ring
  (F.Cu)* checkbox with width / gap / break spins plus a mask-open toggle. Each
  feature's spins enable only when its checkbox is ticked; toggling either redraws
  the preview and adds the zone to the export. Both are off by default.
- Every panel also has an **Overlay / sensitivity (advisory)** group (overlay
  thickness / εr / board thickness) feeding the design advisories — these change no
  geometry. The amber banner additionally lists any blocking advisory (electrode
  sizing / Cp), with the full guidance on its tooltip; a quieter blue line below it
  shows the informational advisories (the series-R recommendation, always; the
  overlay sensitivity note when an overlay is set).
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
- **Export DXF…** writes a `.dxf` mechanical drawing of the same geometry (see
  [DXF export](#dxf-export)).
- **Export IQS550 config…** (enabled only when the trackpad's Controller is
  `iqs550`) writes the sensor-config C header — Total Rx/Tx plus the per-node
  Active-channels disable map — the same artifact as the CLI `--iqs550-config`
  (see [Device profiles](#device-profiles-iqs550)).

`captouch gui --check` constructs the app and exits immediately — a headless smoke
test (used to verify the packaged binary).

## DXF export

`--dxf` (CLI) and **Export DXF…** (GUI) write a `<name>.dxf` drawing of the same
copper the footprint carries — for mechanical / CAD handoff (enclosure cut-outs,
overlay artwork, documentation). It is an *additional* output; the `.kicad_mod` /
`.kicad_sym` pair is unchanged.

```sh
captouch slider --name CT_Slider --dxf -o build/
# wrote build/CT_Slider.kicad_mod
# wrote build/CT_Slider.kicad_sym
# wrote build/CT_Slider.dxf
```

The file is plain ASCII DXF (R12 — the most broadly readable flavour; opens in
LibreCAD, FreeCAD, QCAD, Inkscape, AutoCAD…) in **millimetres**, with the geometry
split onto familiar layers: `F.Cu` / `B.Cu` copper, `F.Fab` outline, `F.CrtYd`
courtyard, and `Vias`. Coordinates are the same as the footprint but with **Y
negated**, so the part reads upright in a conventional y-up CAD coordinate system
(the same convention KiCad's own board → DXF export uses).

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

The trackpad's and mutual slider's Tx bridges live on `B.Cu`, so their boards must
have ≥2 copper layers; so does the hatched ground pour.

## KiCad plugin (design from inside KiCad)

Instead of exporting files and registering libraries by hand, you can run the
generator **from inside KiCad** as an [IPC Action Plugin](https://docs.kicad.org/kicad-python-main/).
It opens the same live-preview window, and the **Add to KiCad project** button
writes the chosen widget's footprint + symbol straight into the open project's
library and registers it — ready to place with KiCad's own *Add Footprint* /
*Add Symbol* pickers.

**Install.** Easiest is KiCad's **Plugin and Content Manager**: every release
publishes a PCM package, so either grab `kicad-captouch-pcm-<version>.zip` from the
[Releases page](https://github.com/unwndevices/kicad-unwn-plugins/releases) and use
*Install from File…*, or add the repository URL
`https://unwndevices.github.io/kicad-unwn-plugins/repository.json` for one-click install
and automatic updates. (You can still copy the [`plugins/captouch/`](../plugins/captouch/)
directory into KiCad's IPC plugins folder by hand instead.) Either way, enable the
API in *Preferences → Plugins* (*"Enable KiCad API"* — the plugin won't appear if
it's off) and restart; on first run KiCad builds a virtualenv from the plugin's
`requirements.txt` and the toolbar button appears once that finishes. See
[`plugins/captouch/README.md`](../plugins/captouch/README.md) for details and
troubleshooting.

**Use.**

1. Open your board, then **Tools → External Plugins → Capacitive-Touch Generator**
   (or the toolbar button).
2. Design a widget with the live preview, exactly as in the standalone GUI.
3. **Add to KiCad project**. A dialog picks the destination — by default a
   project-local `captouch` library (footprints in `captouch.pretty/`, symbols in
   `captouch.kicad_sym`, referenced via `${KIPRJMOD}`). You can point the footprint
   and symbol at **different** libraries, rename the library, or tick **global
   library table** to install into a personal library shared across every project.
4. In the PCB editor press <kbd>A</kbd> and pick `captouch:<name>` to place the
   footprint; add the matching symbol from the `captouch` symbol library in the
   schematic. (Several widgets accumulate in the one library; re-adding a same-named
   part replaces it in place.)

Why a library rather than dropping the footprint directly onto the board: KiCad's
IPC API builds footprints item-by-item as protobuf and **cannot** ingest an
existing `.kicad_mod`, so a direct auto-place would mean re-implementing the whole
emitter against the API — forking the single source of truth, with uncertain
support for the embedded zones and custom-polygon pads this tool emits. Installing
the *real* generated files keeps the placed part byte-identical to every other
frontend, and KiCad's picker does the placement.

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
