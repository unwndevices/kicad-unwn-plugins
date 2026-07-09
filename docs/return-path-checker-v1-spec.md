# Return-Path Checker — v1 Specification

> **Status:** hand-off-ready. This is the destination of wayfinder map
> [Map: return-path checker v1 spec + multi-plugin repo remodel](https://github.com/unwndevices/kicad-captouch/issues/2).
> Every decision below traces to a resolved map ticket (linked inline). Execution —
> implementing the checker and performing the repo remodel — begins after this spec.

A geometric **current-return-path checker** for KiCad PCBs. It parses a `.kicad_pcb`,
identifies the reference plane under each routed signal trace, and reports where the
return path is broken (a plane void the trace crosses), degraded (a layer/reference
change with no nearby return via), or unreferenced (a trace running past the plane
edge). It ships as a standalone Python CLI (headless, CI-friendly) with a thin
in-KiCad IPC plugin layered on top.

---

## 1. Scope

**In v1:**

- Three geometric checks: **split-crossing** (plane void a trace crosses),
  **plane-edge clearance**, and **return-via-at-layer-change**, plus false-positive
  suppression (sliver ignore-area, terminus/antipad exclusion).
- Automatic reference-plane identification (hybrid stackup + geometric).
- A layered, project-checked-in TOML configuration model.
- A flat per-class severity model with a checked-in waiver sidecar.
- Four report formats (text, JSON, SVG, HTML) and three in-KiCad surfaces.

**Explicitly out of v1** ([#11](https://github.com/unwndevices/kicad-captouch/issues/11),
[#12](https://github.com/unwndevices/kicad-captouch/issues/12), map *Out of scope*):

- **Loop-area / copper-starvation** checks — lean toward field-solving, beyond a
  geometric v1.
- **Rise-time-derived threshold budgets** (per-net edge-rate mode) — the `.kicad_pcb`
  carries no rise-time data. A possible post-v1 opt-in.
- **Auto-remediation** — v1 reports; it does not place vias or reroute.
- **Bulk/pattern waivers** — per-finding waiver is the only waiver granularity.

---

## 2. Architecture

Decided while charting the map, refined by
[#4](https://github.com/unwndevices/kicad-captouch/issues/4) and
[#5](https://github.com/unwndevices/kicad-captouch/issues/5):

```
                 ┌─────────────────────────────┐
   .kicad_pcb ──▶│  core: sexpr parser         │
   (file or      │        → Shapely geometry    │──▶ findings ──▶ reports
    live board)  │        → detectors           │                (text/json/svg/html)
                 └─────────────────────────────┘
                        ▲                 ▲
             CLI (headless, CI) ──┘       └── in-KiCad IPC plugin (GUI only)
```

- **Standalone Python core + CLI** is the primary artifact and the *only* path that
  runs in CI. It parses `.kicad_pcb` text directly with the repo's **own**
  S-expression parser (`captouch.sexpr` today, `kicad-core.sexpr` after the remodel) —
  not kiutils — so one parser serves both footprint emission and board reading
  ([#6](https://github.com/unwndevices/kicad-captouch/issues/6)).
- **The in-KiCad layer** is a thin IPC plugin over the same core (§7).

Geometry engine: **Shapely**. Reference plane = `unary_union` of a qualifying pour's
`filled_polygon` islands; an uncovered span = `trace.difference(plane)`. Validated
end-to-end and at real scale ([#6](https://github.com/unwndevices/kicad-captouch/issues/6),
[#13](https://github.com/unwndevices/kicad-captouch/issues/13)): ~258 ms total on a
2 MB / 54k-vertex 4-layer board, ~41 ms for the crossing check over 123 traces.
Performance is a non-issue. (Optimization notes: buffer the plane **once** and use
`shapely.prepared` `covers()` to reject; `plane.simplify(0.01 mm)` halves vertex count
if more headroom is needed.)

---

## 3. Parser contract

The single most concrete outcome of the real-board retest
([#13](https://github.com/unwndevices/kicad-captouch/issues/13)): the parser **must**
target the KiCad-10 schema, or it silently passes a broken board.

- **Nets are name-based everywhere** — `(net "GND")`, `(net "Net-(Q5-G)")`. No net
  numbers; no zone `(net_name ...)` child.
- **A single zone can span multiple layers** — `(layers "F.Cu" "B.Cu" "In2.Cu")`.
  The reference plane is selected **per `filled_polygon` layer** within a zone.
- **Antipads/thermal reliefs are baked into the island geometry** — no separate hole
  geometry; a plane resolves to one high-vertex island (e.g. 10,447 verts) with the
  clearances already carved in.

> A parser using net *numbers*, a zone `net_name` child, or one-layer-per-zone (the
> pre-#13 spike code) would produce an empty plane and zero traces — a false
> "clean board" pass. The v1 parser contract pins the three points above.

**Target file baseline:** KiCad file version `20260206` (KiCad 10), the retest board.

---

## 4. Reference-plane identification

The domain core, from
[#7](https://github.com/unwndevices/kicad-captouch/issues/7). The **reference plane**
for a trace segment is the solid copper region on an adjacent stackup layer that
carries its return current. Pinned along four axes.

### 4.1 Reference source — hybrid (stackup + geometric)

KiCad 10's **Track Propagation table** (declared Bottom/Top Reference per signal layer)
is the default source; geometric nearest-solid-pour inference fills in where the table
is silent. Geometric coverage is **always** re-checked — copper must actually exist
*under* the trace — so voids and slots carved in a *declared* plane are still caught.
(No surveyed tool auto-identifies reference planes; this is novel ground —
[#3](https://github.com/unwndevices/kicad-captouch/issues/3).)

### 4.2 Qualifying reference net — any plane; default GND + power

Any sufficiently large pour is a valid AC reference (power planes are decoupled to GND).
Default qualifying set = **GND + power nets**, configurable (`reference_nets`, §6). A
pour counts as a plane only above `min_pour_area_mm2` (§5).

### 4.3 Adjacency — immediate stackup neighbour(s)

The bottom-reference neighbour is primary; the top-reference neighbour is included as
well when the trace is **stripline** (buried between two planes). Mirrors the stackup's
microstrip/stripline model.

### 4.4 Segment classification — four buckets

| Class | Definition | Default severity (§5) |
|---|---|---|
| **solid** | one continuous qualifying reference under the whole segment | — (clean) |
| **split-crossing** | uncovered span with reference copper on **both** sides — an internal void/slot/gap. *The primary defect.* | `error` |
| **reference-change** | the reference net or layer changes along the segment (GND→power, bottom-ref layer swap) | `info` |
| **edge-overhang / no-reference** | the uncovered span touches or extends past the pour boundary, or no qualifying plane exists | `warning` |

**The split-crossing vs edge-overhang predicate** (validated on real geometry,
[#13](https://github.com/unwndevices/kicad-captouch/issues/13)) — for each uncovered
sub-span of a trace, test both endpoints against qualifying reference copper (within
`sampling_tolerance_mm`):

- **both endpoints on reference copper of the same plane → split-crossing** (the trace
  re-enters copper on the far side; the gap is internal). *The defect.*
- **an endpoint at the pour's outer boundary, or the span extends beyond the plane →
  edge-overhang / no-reference** (the trace simply leaves the pour).

This "**both ends on the plane**" interior test is a **required** filter, not optional:
on the retest board it dropped 89 of 91 raw uncovered spans as benign pad/antipad
terminus over-runs (a trace's last segment reaching its pad, where the plane is held
back by clearance). A free-ended span is never a split.

---

## 5. Checks, algorithms & default thresholds

From [#11](https://github.com/unwndevices/kicad-captouch/issues/11), validated by
[#13](https://github.com/unwndevices/kicad-captouch/issues/13). All thresholds are
**fixed geometric defaults, overridable per net/netclass** through the §6 config
surface.

### 5.1 The three v1 checks

1. **Split-crossing** — the core detector (§4.4). `trace.difference(plane)` → uncovered
   spans → drop spans shorter than `min_crossing_span_mm` and smaller-bridging than
   `sliver_ignore_area_mm2` → apply the both-ends-on-plane predicate → survivors are
   `split-crossing`; free-ended survivors are `edge-overhang`.
2. **Plane-edge clearance** — flag a trace running closer than the clearance threshold
   to the reference-plane edge.
3. **Return-via-at-layer-change** — at a signal via that changes layers, flag the
   absence of a return/stitch via within `return_via_distance_mm`.

### 5.2 Default threshold table

| Knob (config key) | v1 default | Source |
|---|---|---|
| `edge_clearance_mm` | **`max(3H, 90 mil, 1× trace width)`** — H = dielectric height to the reference plane, from the stackup; computed per-trace. A scalar override sets a flat floor. | TI / Intel (#3) |
| `return_via_distance_mm` | **2.0 mm** (refines #3's borrowed 1.5 mm; in-KiCad prior-art consensus) | EMC Auditor / breakneck |
| `sliver_ignore_area_mm2` | **0.0065 mm²** (≈ 10 mil²) — copper below this doesn't bridge a plane | Altium `ReturnPathIgnoreArea` |
| `min_pour_area_mm2` | **1.0 mm²** — a fill counts as a reference plane | pragmatic; confirmed #13 |
| `min_crossing_span_mm` | **0.1 mm** — report floor (exact Shapely geometry, no sampling grid) | pragmatic; confirmed #13 |
| `sampling_tolerance_mm` | tolerance for "endpoint on reference copper" in the §4.4 predicate | — |

The two pragmatic defaults (`min_pour_area_mm2`, `min_crossing_span_mm`) held on the
real board — the 0.1 mm floor cleanly drops sub-antipad slivers; no change needed.

---

## 6. Configuration model

From [#8](https://github.com/unwndevices/kicad-captouch/issues/8). Values from #11/#12;
this section fixes the concrete schema, file names, and discovery — the decisions #8/#12
deferred to this spec.

### 6.1 Net selection

Every routed signal net is checked by default, minus the reference nets:

```
victims  = all_signal_nets − reference_nets
victims −= exclude(netclass | net)
victims += include(net)                # force-in
```

### 6.2 Config source, precedence, discovery

- **File:** `return-path.toml`, checked in with the project (headless-friendly,
  diffable).
- **Discovery order:** `--config PATH` (explicit) wins; else the nearest
  `return-path.toml` searching from the board file's directory upward to the
  filesystem/repo root; else built-in defaults (no file required).
- **Precedence — most-specific wins:**

  ```
  tool defaults → [defaults] → [netclass.<NAME>] → [net."<NAME>"]
  ```

  CLI flags override the file for one-off runs (§7). KiCad-native netclass rules were
  rejected — the rules language can't express these checks (#3) and it's clumsy
  headless.

### 6.3 Schema (concrete keys)

```toml
# return-path.toml
version = 1

[defaults]
reference_nets = ["GND", "+3V3", "+5V"]   # §4.2; default GND + power
include = []                               # net names to force-check
exclude = []                               # net names or netclass names to skip

# thresholds — §5.2
min_pour_area_mm2      = 1.0
min_crossing_span_mm   = 0.1
sliver_ignore_area_mm2 = 0.0065            # 10 mil²
return_via_distance_mm = 2.0
sampling_tolerance_mm  = 0.05
# edge_clearance_mm omitted → the max(3H, 90mil, 1×W) formula; set a number to override

[defaults.severity]                        # §7 — one of error|warning|info|ignore
split_crossing     = "error"
missing_return_via = "error"
edge_clearance     = "warning"
edge_overhang      = "warning"
reference_change   = "info"

# override layers — same keys, most-specific wins
[netclass.HighSpeed]
edge_clearance_mm = 0.30

[net."DDR_CLK"]
severity.reference_change = "warning"
```

---

## 7. Severity & waivers

From [#12](https://github.com/unwndevices/kicad-captouch/issues/12), within #4's IPC
constraints.

### 7.1 Severity model

- **Flat per check class** (not magnitude-scaled), overridable per net/netclass.
- **Vocabulary: `error` / `warning` / `info` / `ignore`.** `ignore` is a class-level
  off-switch (emits nothing anywhere) — distinct from per-finding waivers.
- **Defaults** — see the §4.4 table and the `[defaults.severity]` block above.
- **Cross-surface rule:** the **DRC panel shows exactly the two `InjectDrcError` levels**
  (`error`, `warning`); `info` shows on every *other* surface (overlay, findings panel,
  all reports) but never as a DRC marker.

### 7.2 Waiver persistence

- **System of record: a checker-owned sidecar** `return-path.waivers.toml`, checked in
  alongside `return-path.toml` (discovered the same way; `--waivers PATH` overrides).
  KiCad-native DRC exclusions were **rejected** as source of truth — they can't run
  headless, key to KiCad's marker serialization rather than our finding identity, and
  give `info` findings no home. (They may later be honored as an optional read-only
  secondary input.)
- **Keying: content hash** of `hash(check, class, net, layer, reference_layer,
  quantized-location)`, location quantized to a **0.5 mm grid**. A material change
  (defect moves/reshapes, net renamed, reference plane changes) alters the hash → the
  waiver **lapses → re-review**. This conservative lapse-on-change is the point;
  KIID-anchoring was rejected.
  - **Stored but not hashed (descriptive):** `severity` (config-derived), `span_mm`,
    `message`.
  - **Matching:** pure hash equality on the grid — O(1); the grid-boundary seam fails
    *safe* (lapse), and 0.5 mm keeps distinct same-net findings from colliding.
- **Entry shape:** hash `id` + descriptive echo (check/class/net/message/raw location) +
  provenance — `reason` (expected, not hard-enforced), auto-stamped `author`
  (git `user.name` / KiCad session) + `date`, optional `expires` (temporary accept;
  off by default).
- **Stale waivers** (key matches no current finding): **reported as `info`, never
  auto-deleted** (non-destructive to the checked-in sidecar); explicit
  `--prune-waivers` for cleanup.

```toml
# return-path.waivers.toml
version = 1

[[waiver]]
id = "a1b2c3d4"                            # content hash (§7.2)
check = "split-crossing"
net = "DDR_CLK"
location = { x = 128.40, y = 96.10 }       # raw, descriptive
reason = "reviewed — crosses documented moat by design"
author = "Ciro Caputo Viglione"
date = "2026-07-09"
# expires = "2026-12-31"                   # optional
```

### 7.3 Suppression model — three tiers (broadest → narrowest)

1. **Net exclusion** (§6.1) — don't check the net at all.
2. **Class `ignore`** (§7.1) — never care about a defect class board-wide.
3. **Per-finding waiver** (§7.2) — reviewed and accepted one specific instance.

Per-finding is the **sole** waiver granularity — no pattern/bulk tier in v1.

---

## 8. Reporting & the finding record

From [#9](https://github.com/unwndevices/kicad-captouch/issues/9). Asset:
`prototypes/return-path-geometry-spike/report.py` + `overlay.svg`/`overlay.png`.

### 8.1 The canonical finding record

The shared unit both reports and the overlay consume:

```
check · net · class · severity · layer · reference_layer · location{x,y} · span_mm · message
```

In JSON a waived finding additionally carries `waived: true` + `reason` (§7.2); it is
**never silently dropped**.

### 8.2 Report formats (v1)

- **Text** (default) — human console output; grouped, severity-iconed, one line +
  message per finding, with an error/warning tally and a `Waived (N)` section.
- **JSON** (CI) — the machine format; a list of finding records.
- **SVG overlay** — findings in board space (copper islands, traces, numbered
  severity-colored crosshairs); rasterizable.
- **HTML** — a self-contained report embedding the overlay + finding list, for sharing.

### 8.3 In-KiCad surfaces (all three together)

Per the #4 mechanism (§9):

- **`User.*`-layer overlay** — durable crosshair + numbered-label graphics; the
  persistent record (survives a native DRC run). Waived findings drawn **muted**
  (hollow/greyed).
- **`InjectDrcError` markers** — populate the native DRC panel (`error`/`warning` only;
  **unwaived** only), accepting they're wiped by the next native DRC run.
- **`add_to_selection()`** — flash the offending trace (selection is the only
  interaction primitive).
- **Custom findings-list panel** — click-to-select navigation; **all** findings, waived
  **sectioned** (and where you un-waive).

> **Open implementation risk (signpost, not a blocker):** the IPC plugin is a separate
> process (§9), so whether the findings-list panel can be a **dockable in-app panel** or
> must be a **standalone plugin window** is unconfirmed — resolve at execution or via a
> small research pass. (Map *Not yet specified*.)

---

## 9. In-KiCad integration mechanism

From [#4](https://github.com/unwndevices/kicad-captouch/issues/4). Asset:
`docs/kicad-ipc-plugin-api.md`. Verified against kicad-python **0.7.1** and KiCad 10
source.

- **Mechanism:** an **IPC plugin** (`plugin.json`, `runtime.type: "python"`) distributed
  via PCM (`metadata.json` schema v2, `"runtime": "ipc"`, `"kicad_version": "10.0"`).
  KiCad auto-creates a per-plugin venv and pip-installs the plugin's `requirements.txt`,
  so the checker core is just a PyPI dependency.
- **Bridge:** `Board.get_as_string()` — the live board as `.kicad_pcb` text, *unsaved
  edits included* — keeping the single parser path (§2).
- **KiCad floor: KiCad 10+** for the in-KiCad layer (IPC plugin API era). SWIG is
  **removed in KiCad 11**, so IPC is the only forward path.

**Constraints that shape the spec:**

1. **GUI-only in KiCad 9/10** — headless `kicad-cli api-server` lands only in KiCad 11.
   The core's own `.kicad_pcb` parser stays **mandatory for CI**.
2. **DRC integration is generic markers only** — `InjectDrcError` yields
   `DRCE_GENERIC_WARNING/ERROR` (no custom violation type); running native DRC **wipes**
   them. The durable fallback is graphics on a `User.*` layer.
3. **No docked UI, no events** — out-of-process (NNG over UNIX socket); the only
   in-KiCad surface is a toolbar button; the API is synchronous (needs retry when KiCad
   is busy); no zoom-to/highlight-net — selection is the interaction primitive.

**Gotcha:** the kicad-python 0.7.1 wheel ships broken `kipy.board_rules` /
`kipy.schematic_types` — pin the version, avoid those imports.

---

## 10. CLI contract

The concrete surface #8/#12 deferred to this spec.

```
return-path check BOARD.kicad_pcb [options]

  Config / waivers
    --config PATH          explicit return-path.toml (else discovered, §6.2)
    --waivers PATH         explicit return-path.waivers.toml (else alongside config)
    --no-waivers           ignore the sidecar for this run
    --reference-nets NET…  override reference_nets
    --include NET          force-check a net (repeatable)
    --exclude NET…         skip a net or netclass (repeatable)
    --set KEY=VALUE        ad-hoc threshold/severity override (repeatable)

  Output
    --format text|json|svg|html   repeatable / comma-separated (default: text)
    --output PATH          write a single-format report to a file (else stdout)
    --out-dir DIR          write all requested formats into a directory

  Waiver management
    --waive HASH --reason "…"    append a waiver entry to the sidecar
    --prune-waivers              remove stale (unmatched) waiver entries

  Gate
    --fail-on error|warning|info|none   exit-code threshold (default: error)
```

**Exit codes** — computed from **unwaived** findings only (§7.2):

| Code | Meaning |
|---|---|
| `0` | no unwaived finding at or above `--fail-on` |
| `1` | one or more unwaived findings at or above `--fail-on` |
| `2` | usage / parse error (bad args, unreadable board) |

Default `--fail-on error` means: **unwaived `error` fails the build**; `warning`/`info`
exit 0. Waiving the last active `error` greens the build.

---

## 11. Repo layout & packaging plan

From [#5](https://github.com/unwndevices/kicad-captouch/issues/5) — decided on paper;
execution follows this map.

- **Repo rename:** `kicad-captouch` → **`kicad-plugins`** (GitHub 301-redirects the old
  URL; existing clones and the `main.zip` `requirements.txt` URL keep resolving). Per-tool
  package names stay descriptive: `kicad-captouch`, `kicad-returnpath`.
- **Topology:** a **uv workspace** of packages with a **lean shared `kicad-core`**
  (S-expression read/emit `sexpr.py` + the IPC bridge) and one package per tool depending
  on it — keeps the CLI-first checker free of captouch's heavy PySide6 GUI dependency.
- **Tooling:** uv workspace (one `uv.lock`, path deps core←tools, editable) + **hatchling**
  as each package's build backend (per-package `python -m build` / PCM flow unchanged). CI
  migrates `pip install -e ".[dev]"` → `uv sync`.
- **PCM:** **one PCM package per tool, one shared repository index** on GitHub Pages
  (`https://unwndevices.github.io/kicad-plugins/repository.json`). Reverse-DNS identifiers
  per tool: `com.github.unwndevices.kicad-captouch` (unchanged — installs not orphaned) +
  new `com.github.unwndevices.kicad-returnpath`.
- **Versioning:** **independent per-tool semver tags** — `core-vX.Y.Z`,
  `captouch-vX.Y.Z`, `returnpath-vX.Y.Z`; `release.yml` reads the tag prefix and builds
  only that tool. **Core + tools published to PyPI** (retires the install-from-GitHub-archive
  stopgap).
- **Migration posture: remodel now, extract `kicad-core` later** — do the rename + uv
  workspace + moves now; **defer carving out `kicad-core`** until the return-path checker
  actually imports it (a shared boundary designed against one consumer is a guess). Reserve
  the `packages/kicad-core/` slot on paper.

**Target tree:**

```
kicad-plugins/
  pyproject.toml            # [tool.uv.workspace] members = ["packages/*"]
  uv.lock
  packages/
    kicad-captouch/         # current src/captouch (incl. sexpr + bridge, for now)
      src/captouch/  pyproject.toml (hatchling)
    kicad-returnpath/       # the checker (new)
    kicad-core/             # RESERVED — carved out when returnpath imports it
  plugins/
    captouch/               # entry.py, plugin.json, icons, requirements.txt
    returnpath/             # thin PCM bundle (new)
  packaging/                # shared PCM build tooling, generalized to per-tool
```

**Migration order (execution):** rename repo → scaffold uv workspace at root →
`git mv src/captouch packages/kicad-captouch/…` → `git mv kicad-plugin plugins/captouch`
→ generalize `build_pcm.py` + `release.yml` to per-tool tags → switch CI to `uv sync`.

---

## 12. Deferred / open (hand-off signposts)

Not blockers for execution; flagged so they aren't lost.

- **Findings-list panel hosting** — dockable in-app vs standalone window is unconfirmed
  (§8.3); resolve at execution or via a small research pass.
- **CI story** — headless runs, exit codes (§10), report artifacts, a possible GitHub
  Action wrapping `return-path check`. (Map *Not yet specified*.)
- **Other mono-repo plugins** beyond captouch + return-path — unspecified; each is its
  own future effort.
- **KiCad-native DRC exclusions as a read-only secondary waiver input** — possible
  post-v1 (§7.2).
- **Tolerance-matching for waivers** and **rise-time edge-rate mode** — post-v1 opt-ins.

---

## Appendix — traceability

| Spec section | Map ticket |
|---|---|
| §2 Architecture, §3 Parser, §5.1 detector | [#6 geometry spike](https://github.com/unwndevices/kicad-captouch/issues/6), [#13 real-board retest](https://github.com/unwndevices/kicad-captouch/issues/13) |
| §4 Reference-plane identification | [#7](https://github.com/unwndevices/kicad-captouch/issues/7) |
| §5 Checks & thresholds | [#11](https://github.com/unwndevices/kicad-captouch/issues/11) |
| §6 Configuration model | [#8](https://github.com/unwndevices/kicad-captouch/issues/8) |
| §7 Severity & waivers | [#12](https://github.com/unwndevices/kicad-captouch/issues/12) |
| §8 Reporting UX | [#9](https://github.com/unwndevices/kicad-captouch/issues/9) |
| §9 In-KiCad integration | [#4](https://github.com/unwndevices/kicad-captouch/issues/4) |
| §11 Repo layout & packaging | [#5](https://github.com/unwndevices/kicad-captouch/issues/5) |
| §1 Landscape / vocabulary | [#3](https://github.com/unwndevices/kicad-captouch/issues/3) |
