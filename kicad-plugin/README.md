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

Copy this `kicad-plugin/` directory into KiCad's IPC plugins folder, renaming it as
you like:

- **Linux:** `~/.local/share/kicad/<version>/plugins/` *(or `${KICAD_DOCUMENTS_HOME}/<version>/plugins`)*
- **macOS:** `~/Documents/KiCad/<version>/plugins/`
- **Windows:** `Documents\KiCad\<version>\plugins\`

Then enable the IPC API in **Preferences → Plugins** (*"Enable KiCad API"*) and
restart KiCad. On first run KiCad creates a virtualenv and installs
[`requirements.txt`](./requirements.txt) (this can take a minute — the toolbar
button appears once it finishes). The action shows up as **Tools → External Plugins
→ Capacitive-Touch Generator** and on the PCB-editor toolbar.

> Prefer not to install the package from PyPI? Run from a source checkout: the
> [`entry.py`](./entry.py) shim adds the repo's `src/` to `sys.path` if
> `kicad-captouch` isn't installed, so the plugin runs straight from the tree
> (you still need `kicad-python` and `PySide6` available).

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
