# KiCad Action Plugin — Return-Path Checker

This directory is the installable **KiCad IPC Action Plugin** bundle. From inside
KiCad 10 it runs the [return-path checker](../../packages/kicad-returnpath) on the
**live** board — split-plane crossings, plane-edge clearance, and missing return
vias — and surfaces the findings without leaving KiCad:

- **DRC markers** for unwaived `error`/`warning` findings, in the native DRC panel
  (these are wiped by the next native DRC run — that's expected);
- a durable **`User.1`-layer overlay** — a numbered, severity-coloured crosshair per
  finding (waived findings drawn muted) that *survives* a native DRC run — the
  persistent record;
- **selection** — clicking a finding flashes/selects the offending trace (selection
  is KiCad's only interaction primitive over IPC);
- a **findings-list panel** — a **standalone window** (IPC gives no docked in-app UI,
  so the panel cannot dock — it is a separate plugin window) listing *every* finding,
  including `info` and waived, waived ones **sectioned**; clicking a row selects its
  trace, and un-waiving a row rewrites `return-path.waivers.toml`.

It is a thin, GUI-only wrapper: the analysis stays in the standalone `kicad-returnpath`
engine, reached over the [IPC API](https://docs.kicad.org/kicad-python-main/)
(`kicad-python`) via `Board.get_as_string()`, so the in-KiCad findings are identical
to a headless `return-path check` run. The **CLI stays the CI path**; this plugin is
the interactive surface.

## Install

Two things are needed in every case: **enable the IPC API** in *Preferences →
Plugins* (tick *"Enable KiCad API"*) — the plugin will not appear if this is off —
and **restart KiCad**. On first run KiCad builds a managed virtualenv and installs
[`requirements.txt`](./requirements.txt) into it (this takes a minute; the toolbar
button appears once it finishes). The action then shows up as **Tools → External
Plugins → Return-Path Checker** and on the PCB-editor toolbar.

> **KiCad 10+ only.** The IPC plugin API lands in KiCad 10, and SWIG is removed in
> KiCad 11 — IPC is the only forward path. `kicad-python` is pinned to **0.7.1**.

### Recommended: Plugin & Content Manager

Each tagged release publishes a ready-made PCM package, so you never have to find
the right plugins folder by hand:

- **Install from File** — download `kicad-returnpath-pcm-<version>.zip` from the
  project's [Releases page](https://github.com/unwndevices/kicad-unwn-plugins/releases),
  then in KiCad's **Plugin and Content Manager** choose **Install from File…** and
  pick that zip.
- **Add the repository (auto-updates)** — in the Plugin and Content Manager open
  **Manage…**, add the repository URL
  `https://unwndevices.github.io/kicad-unwn-plugins/repository.json`, then install
  *Return-Path Checker* from the list. KiCad will offer updates when new releases ship.

### Manual: copy the bundle

Alternatively, copy this `plugins/returnpath/` directory into KiCad's IPC plugins
folder, renaming it as you like:

- **Linux:** `~/.local/share/kicad/<version>/plugins/` *(or `${KICAD_DOCUMENTS_HOME}/<version>/plugins`)*
- **macOS:** `~/Documents/KiCad/<version>/plugins/`
- **Windows:** `Documents\KiCad\<version>\plugins\`

> Prefer not to pull from GitHub at build time? Run from a source checkout: the
> [`entry.py`](./entry.py) shim adds the repo's `src/` to `sys.path` if
> `kicad-returnpath` isn't installed, so the plugin runs straight from the tree (you
> still need `kicad-python` available in the venv).

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
  `<KiCad cache>/python-environments/com.github.unwndevices.kicad-returnpath` — Windows
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
| `entry.py` | Entrypoint shim → `returnpath.kicad_plugin.main`. |
| `requirements.txt` | Deps KiCad installs into the plugin venv (`kicad-python==0.7.1`). |
| `icon-{light,dark}-{24,48}.png` | Toolbar icons (regenerate with `make_icons.py`). |

## Use

1. Open your board in the KiCad PCB editor.
2. **Tools → External Plugins → Return-Path Checker** (or the toolbar button).
3. Findings appear as DRC markers (unwaived errors/warnings) and as a numbered
   `User.1` overlay (every finding; waived ones muted). Run native DRC if you like —
   the overlay persists; the injected markers do not.
4. The **findings-list panel** window opens with the complete list — every severity,
   waived findings sectioned. Click a row to flash its trace; select a waived row and
   **Un-waive** it to drop its entry from `return-path.waivers.toml` (it resurfaces on
   the next run).
5. Configuration and waivers are read from the project's `return-path.toml` /
   `return-path.waivers.toml` (discovered upward from the board), exactly as the CLI.
