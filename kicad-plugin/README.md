# KiCad Action Plugin — Capacitive-Touch Footprint Generator

This directory is the installable **KiCad IPC Action Plugin** bundle. From inside
KiCad 9/10 it opens the live-preview generator, and — when you click **Add to KiCad
project** — writes the chosen widget's footprint + symbol into the open project's
`captouch` library and registers it, so KiCad's **Add Footprint** / **Add Symbol**
pickers can place it onto the board.

It is a thin wrapper: generation stays in the standalone `kicad-captouch` engine
(the version-resilient S-expression emitter), and the [IPC API](https://docs.kicad.org/kicad-python-main/)
(`kicad-python`) is used only to learn which project is open. The placed footprint
is byte-identical to the standalone CLI/GUI output.

## Why a library, not a direct drop-in

The KiCad IPC API builds footprints item-by-item as protobuf; it cannot ingest an
existing `.kicad_mod`. Re-authoring the emitter against the API would fork the
single source of truth (and has uncertain support for the embedded zones and
custom-polygon pads this tool emits). Installing the real generated files into a
project library — and letting you place them with KiCad's own picker — keeps the
emitter authoritative and the output identical to every other frontend.

## Install

Two things are needed in every case: **enable the IPC API** in *Preferences →
Plugins* (tick *"Enable KiCad API"*) — the plugin will not appear if this is off —
and **restart KiCad**. On first run KiCad builds a managed virtualenv and installs
[`requirements.txt`](./requirements.txt) into it (this takes a minute; the toolbar
button appears once it finishes). The action then shows up as **Tools → External
Plugins → Capacitive-Touch Generator** and on the PCB-editor toolbar.

### Recommended: Plugin & Content Manager

Each tagged release publishes a ready-made PCM package, so you never have to find
the right plugins folder by hand:

- **Install from File** — download `kicad-captouch-pcm-<version>.zip` from the
  project's [Releases page](https://github.com/unwndevices/kicad-captouch/releases),
  then in KiCad's **Plugin and Content Manager** choose **Install from File…** and
  pick that zip.
- **Add the repository (auto-updates)** — in the Plugin and Content Manager open
  **Manage…**, add the repository URL
  `https://unwndevices.github.io/kicad-captouch/repository.json`, then install
  *Capacitive-Touch Footprint Generator* from the list. KiCad will offer updates
  when new releases ship.

### Manual: copy the bundle

Alternatively, copy this `kicad-plugin/` directory into KiCad's IPC plugins folder,
renaming it as you like:

- **Linux:** `~/.local/share/kicad/<version>/plugins/` *(or `${KICAD_DOCUMENTS_HOME}/<version>/plugins`)*
- **macOS:** `~/Documents/KiCad/<version>/plugins/`
- **Windows:** `Documents\KiCad\<version>\plugins\`

> Prefer not to pull from GitHub at build time? Run from a source checkout: the
> [`entry.py`](./entry.py) shim adds the repo's `src/` to `sys.path` if
> `kicad-captouch` isn't installed, so the plugin runs straight from the tree
> (you still need `kicad-python` and `PySide6` available in the venv).

## Troubleshooting

**No toolbar button, and nothing under Tools → External Plugins.** This almost
always means KiCad's first-run venv build failed — most often because a dependency
in [`requirements.txt`](./requirements.txt) could not be installed. KiCad reports
this poorly by default, so make it talk:

- **Update to KiCad 10.0.1 or later.** 10.0.0 had a bug where IPC plugins did not
  appear in the toolbar; 10.0.1 also surfaces plugin `stdout`/`stderr` in the
  status-bar warnings (bottom-right).
- **See the build error.** Launch KiCad from a terminal with tracing on:
  - Windows: `set KICAD_ALLOC_CONSOLE=1 & set KICAD_ENABLE_WXTRACE=1 & set WXTRACE=KICAD_API & "C:\Program Files\KiCad\10.0\bin\kicad.exe"`
  - Linux / macOS: `KICAD_ENABLE_WXTRACE=1 WXTRACE=KICAD_API kicad`
- **Inspect or reset the venv.** The plugin's managed environment lives at
  `<KiCad cache>/python-environments/org.kicad-captouch.generator` — Windows
  `%LOCALAPPDATA%\KiCad\<version>\python-environments\…`, Linux
  `~/.cache/KiCad/<version>/…`, macOS `~/Library/Caches/KiCad/<version>/…`. Its pip
  log shows what failed. **Delete this folder and restart KiCad** to force a clean
  rebuild after editing `requirements.txt`.

See the [KiCad add-on developer docs](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/index.html)
for the full debugging reference.

## Files

| File | Purpose |
|---|---|
| `plugin.json` | Action manifest (validated against KiCad's `api/schemas/v1`). |
| `entry.py` | Entrypoint shim → `captouch.kicad_plugin.main`. |
| `requirements.txt` | Deps KiCad installs into the plugin venv. |
| `icon-{light,dark}-{24,48}.png` | Toolbar icons (regenerate with `make_icons.py`). |

## Use

1. Open your board in the KiCad PCB editor.
2. **Tools → External Plugins → Capacitive-Touch Generator** (or the toolbar button).
3. Design a slider / wheel / trackpad / mutual-slider / keypad with live preview.
4. **Add to KiCad project** → confirm the destination (defaults to a project-local
   `captouch` library; the footprint `.pretty` and symbol `.kicad_sym` can target
   different libraries, and a *global* toggle installs to a personal library shared
   across projects).
5. Back in the PCB editor, press **A** and pick `captouch:<name>` to place it; add
   the matching symbol from the `captouch` symbol library in the schematic.
