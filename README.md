# kicad-captouch

A desktop tool that **parametrically generates capacitive-touch interface footprints** —
self- and mutual-cap sliders, wheels, XY diamond trackpads, and button keypads — for KiCad,
with a live visual preview. Each widget is emitted as a ready-to-use **footprint (`.kicad_mod`)**
plus a matching **schematic symbol (`.kicad_sym`)**, written directly as KiCad S-expressions
(no dependency on KiCad's in-flux scripting API), all **DRC-clean** in KiCad 9 and 10.

License: **GPL-3.0-or-later**.

There are three ways to use it:

| | What you get | Needs |
|---|---|---|
| **[KiCad plugin](#use-it-inside-kicad-plugin)** | Design inside KiCad and click *Add to KiCad project* to install the part into the open board's library, ready to place | KiCad 9/10 (10.0.1+ recommended) |
| **[Standalone app](#run-it-standalone)** | The same live-preview GUI + a CLI, generating files you import yourself | Python, **or** a one-file binary |
| **[From source](#build-from-source)** | Hack on it, run the tests, build the binary or the plugin package | A git checkout |

For the full parameter reference — every widget, flag, fab profile, and advisory — see the
**[usage guide](docs/usage.md)**. For architecture and roadmap see [`docs/plan.md`](docs/plan.md).

## What it generates

Five widgets, all derived from one engine (`params` → `geometry` (Shapely) → `export`):

- **Linear sliders** — a row of rectangular / chevron / interdigitated self-cap electrodes.
- **Wheels** — the slider bent into a continuous annulus around a centre keep-out.
- **XY diamond trackpads** — a mutual-cap `R×C` diamond matrix on two copper layers (`F.Cu` rows,
  `B.Cu`-bridged columns through vias); `R + C` pins resolve `R·C` interpolated nodes.
- **Mutual-cap (CSX) sliders** — the trackpad collapsed to one sense row: N nodes on `N + 1` pins.
- **Button keypads** — an `R×C` grid of discrete self-cap buttons (rect / circle / diamond),
  one pin each.

Most widgets can be designed **from their overall size** (a target length, diameter, or panel
W×H) instead of an element count. Every part ships in the **KiCad 9.0** S-expression format that
both KiCad 9 and 10 accept. See [usage.md](docs/usage.md) for parameters, vendor presets, fab-rule
guards, sensitivity advisories, optional ground/guard copper, and DXF export.

---

## Use it inside KiCad (plugin)

Run the generator **from inside KiCad 9/10** as an IPC Action Plugin. It opens the same
live-preview window, and an **Add to KiCad project** button writes the designed widget's
footprint + symbol into the open project's `captouch` library and registers it — ready to place
from KiCad's own *Add Footprint* / *Add Symbol* pickers. The placed part is byte-identical to the
standalone CLI/GUI output; the [IPC API](https://docs.kicad.org/kicad-python-main/)
(`kicad-python`) is used only to find which project is open.

### Install

The easiest path is KiCad's **Plugin and Content Manager (PCM)** — every tagged release publishes a
ready-made package, so you never hunt for the right plugins folder by hand.

- **Add the repository (recommended — auto-updates).** In the PCM open **Manage…**, add the
  repository URL

  ```
  https://unwndevices.github.io/kicad-captouch/repository.json
  ```

  then install *Capacitive-Touch Footprint Generator* from the list. KiCad offers updates when new
  releases ship.

- **Install from File.** Download `kicad-captouch-pcm-<version>.zip` from the
  [Releases page](https://github.com/unwndevices/kicad-captouch/releases), then in the PCM choose
  **Install from File…** and pick that zip.

- **Manual copy.** Copy the [`kicad-plugin/`](kicad-plugin/) directory into KiCad's IPC plugins
  folder (`~/.local/share/kicad/<ver>/plugins/` on Linux, `~/Documents/KiCad/<ver>/plugins/` on
  macOS, `Documents\KiCad\<ver>\plugins\` on Windows).

### Enable it and first run

In every case:

1. **Enable the IPC API** — *Preferences → Plugins → "Enable KiCad API"*. The plugin will **not**
   appear if this is off.
2. **Restart KiCad.** On first run KiCad builds a managed virtualenv and installs the plugin's
   [`requirements.txt`](kicad-plugin/requirements.txt) (`kicad-python` + `kicad-captouch[gui]`,
   pulled as a zip straight from this repo). This takes a minute; the toolbar button appears once
   it finishes.

The action then shows up as **Tools → External Plugins → Capacitive-Touch Generator** and on the
PCB-editor toolbar.

> **No button, nothing under External Plugins?** That almost always means the first-run venv build
> failed. Update to **KiCad 10.0.1+** (10.0.0 had a bug where IPC plugins didn't appear, and 10.0.1
> surfaces plugin errors in the status bar), then see the
> [plugin troubleshooting guide](kicad-plugin/README.md#troubleshooting) for how to read the pip log
> and reset the venv.

### Use it

1. Open your board, then **Tools → External Plugins → Capacitive-Touch Generator** (or the toolbar
   button).
2. Design a slider / wheel / trackpad / mutual-slider / keypad with the live preview.
3. **Add to KiCad project** → confirm the destination (defaults to a project-local `captouch`
   library; footprint and symbol can target different or global libraries).
4. In the PCB editor press <kbd>A</kbd> and pick `captouch:<name>` to place the footprint; add the
   matching symbol from the `captouch` symbol library in the schematic.

Full details and the rationale for the library-install approach are in
[`kicad-plugin/README.md`](kicad-plugin/README.md) and
[usage.md](docs/usage.md#kicad-plugin-design-from-inside-kicad).

---

## Run it standalone

### From a Python install

Shapely is the only runtime dependency; the GUI adds PySide6.

```sh
pip install -e .            # engine + CLI
pip install -e '.[gui]'     # add the PySide6 desktop GUI
```

**Launch the GUI:**

```sh
captouch gui                # or: captouch-gui
```

**Or use the CLI** — each command writes `<name>.kicad_mod` + `<name>.kicad_sym` (default into
`./examples`):

```sh
captouch slider                                  # 4-segment chevron slider
captouch wheel --preset st_rotary                # rotary wheel from a vendor preset
captouch trackpad --num-rows 4 --num-cols 5      # 4×5 mutual-cap diamond pad
captouch mutual-slider --num-segments 6          # 6-node mutual-cap (CSX) slider
captouch keypad --num-rows 4 --num-cols 3        # 4×3 self-cap button grid
captouch slider --length 100                     # size from overall length, not a count
captouch <widget> --help                         # full parameter list for any widget
```

Then import the pair in KiCad (*Manage Footprint/Symbol Libraries*) — see
[usage.md → Using the output in KiCad](docs/usage.md#using-the-output-in-kicad).

### Standalone binary (no Python)

Each release ships a one-file executable on the
[Releases page](https://github.com/unwndevices/kicad-captouch/releases) —
`captouch-linux-x86_64`, `captouch-macos`, `captouch-windows.exe`. Download it, make it executable,
and run it exactly like the CLI; `captouch gui` launches the preview app.

```sh
chmod +x captouch-linux-x86_64
./captouch-linux-x86_64 gui
```

---

## Build from source

Clone the repo, then pick the artifact you want to build.

### Dev install + tests

```sh
pip install -e '.[dev]'                  # engine, GUI, and test/lint toolchain
PYTHONPATH=src python3 -m pytest         # unit + golden-file + kicad-cli gates
```

The `kicad-cli` tests (footprint/symbol render, and **DRC-clean** on a generated board) run
automatically when `kicad-cli` is on `PATH`, and skip otherwise. The GUI tests run headless on Qt's
`offscreen` platform and skip when PySide6 is absent.

### Standalone binary

PyInstaller freezes the CLI + GUI into one file. It can't cross-compile, so each OS builds its own:

```sh
pip install -e '.[packaging]'
packaging/build-binary.sh                # Linux / macOS → dist/captouch (also smoke-tested)
```

The [`build-binaries` CI workflow](.github/workflows/build.yml) builds and smoke-tests on
Linux/macOS/Windows and uploads the artifacts.

### KiCad PCM package

`packaging/build_pcm.py` turns the [`kicad-plugin/`](kicad-plugin/) bundle into an installable PCM
package plus the repository index (`packages.json` / `repository.json` / `resources.zip`). It
pins the plugin's `requirements.txt` to the released tag and validates every emitted JSON against
the vendored PCM v2 schema, building a deterministic (byte-stable) zip:

```sh
pip install jsonschema
python packaging/build_pcm.py --version 0.1.0 --outdir dist
```

On a `v*` tag the [`release` workflow](.github/workflows/release.yml) runs this, publishes the PCM
package and the binaries as Release assets, and deploys the repository index to GitHub Pages so the
[repository URL](#install) resolves and offers updates.

---

## Docs

- **[docs/usage.md](docs/usage.md)** — full usage guide: every widget and flag, vendor presets,
  fab-rule guards, sensitivity advisories, support copper, DXF export, and validating with
  `kicad-cli`.
- **[docs/plan.md](docs/plan.md)** — architecture, stack, and roadmap.
- **[docs/capacitive-touch-design-guidelines.md](docs/capacitive-touch-design-guidelines.md)** —
  the design numbers behind the parameters.
- **[kicad-plugin/README.md](kicad-plugin/README.md)** — the plugin bundle, install options, and
  troubleshooting.
