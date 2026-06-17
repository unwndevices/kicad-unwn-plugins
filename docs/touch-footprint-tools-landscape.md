# Capacitive-Touch Footprint Generation: Tool Landscape

**Scope.** This document surveys the *existing* tool landscape for generating
capacitive-touch interface footprints — sliders, wheels / rotary sensors, and
XY pads / trackpads (including diamond grids) — on PCBs. The focus is KiCad but
is explicitly **not** limited to KiCad: it also covers commercial EDA tools,
touch-silicon vendor design software, and generic / open-source parametric
geometry generators. The goal is to inform planning of a new KiCad-focused
parametric tool (plugin / external / CLI) that generates these footprints.

**Date of research.** 2026-06-17. Maturity signals (stars, last commit,
archived/maintained status) are as observed on that date. Where a capability
could not be confirmed from a primary source, this is stated explicitly rather
than guessed.

---

## Summary table

| Tool / project | Vendor / source | Type | Generates real PCB geometry? | Export formats | Open source? | Maturity / notes |
|---|---|---|---|---|---|---|
| **KiCad footprint wizards** (`touch_slider_wizard.py`, `mutualcap_button_wizard.py`) | KiCad (official) | KiCad Python footprint wizard (bundled) | **Yes** — KiCad footprints | `.kicad_mod` | Yes (GPL-3.0+) | **Most official touch generator.** GitHub repo **archived 2023**; GitLab repo also dormant (~11 commits). Slider + mutual-cap button only; no wheel/XY. ~22 GitHub stars. |
| **kicad-footprint-generator** | community (pointhi → KiCad GitLab) | Python library / framework | Yes (general) | `.kicad_mod` | Yes (GPL-3.0+) | Foundational framework for KiCad's official libs. GitHub mirror archived 2020 → moved to GitLab. **No touch footprints.** ~199 stars. |
| **ESCPT** (Electrostatic Capacitive Pad Tool) | hanya (GitHub) | KiCad pcbnew Python macro | **Yes** — copper as KiCad **zones** (DRC-clean) | KiCad zones | Yes (GPLv3) | Mutual-cap pads (3 types). ~15 stars, ~4 commits, **unmaintained**. |
| **idc_kicad** | lionnus (GitHub) | Python CLI | **Yes** — interdigitated capacitor | `.kicad_mod` | Yes (GPL-3.0) | Closest "IDE → real KiCad copper". ~2 stars, 7 commits, **early/dormant**. |
| **svg2shenzhen** | badgeek (GitHub) | Inkscape extension | Yes (arbitrary SVG → copper) | `.kicad_pcb`, `.kicad_mod` | Yes (GPL-3.0) | De-facto SVG→KiCad bridge. **Discontinued** (last v0.2.18.7, Mar 2025); author points to Gingerbread. ~862 stars. Not touch-specific. |
| **Altium "Designing with Touch Controls"** | Altium (built-in) | Commercial EDA built-in | **Yes** — copper electrodes | Altium native | No | Only mainstream commercial EDA w/ native parametric electrode gen. Buttons/sliders/wheels. **Legacy vendor branding** (Atmel/Cypress/Microchip). No native XY trackpad. |
| **Microchip Touch Sensor Plugin for Altium** | Microchip (Altium extension) | Vendor EDA plugin | Yes (footprints incl. diamond buttons) | Altium native | No | Generates ButtonSelf + Surface Diamond patterns. Vendor-locked. |
| **TI SLAA891 OpenSCAD scripts** | Texas Instruments | OpenSCAD scripts (tool-agnostic) | **Yes** — electrode outlines | **DXF** | Yes (BSD; OpenSCAD GPLv2) | Parametric slider/wheel/curved-slider/touchpad. Import DXF → copper manually. Canonical method; **not revised since 2020**. |
| **timonsku/Touchpad-Generator** | timonsku (GitHub) | OpenSCAD + Python pipeline | **Yes** — diamond XY pad **+ routing** | **Eagle XML** `.brd` (imports into KiCad) | Yes | Most complete XY-trackpad generator. Used on MNT Reform Next. ~67 stars, **2 commits, dormant**. |
| **Tangara touchwheel electrode tool** | cooltech.zone (Tangara) | Web app | Partial — outlines (needs cleanup) | **SVG** | Source viewable (OSL-3.0 site) | 3-electrode interpolated **wheel** only. Recent (2024), single-purpose. |
| **appfruits/RotarySensor** | community (GitHub) | Eagle ULP | **Yes** — wheel copper | Eagle native | Yes | QTouch click-wheel. ~8 stars, **not actively developed**. |
| **PatternAgents Touch Widgets** | PatternAgents (GitHub) | Eagle **static library** (not generator) | Yes (fixed parts) | Eagle native | Yes (CC BY-SA 4.0) | Buttons/sliders/radial/XY as fixed sizes. From 2013, **stale**. |
| **gdsfactory** | gdsfactory (GitHub) | Python geometry library | Yes (IDE/comb primitives) | GDS, OASIS, STL, **Gerber** | Yes (MIT) | Strong parametric base w/ `interdigital_capacitor()`; **not touch-specific**, no KiCad-mod. Very active. |
| **gdstk / gdspy** | heitzmann (GitHub) | Python GDSII library | Capable, but IC/MEMS-oriented | GDSII / OASIS | Yes | Not used for PCB touch in practice; no PCB workflow. |
| **kicad-coil-generators / NFC coil gens** | community (various) | KiCad wizard / Python | **Yes** — spiral copper | `.kicad_mod` (+ DXF/SVG) | Yes (mostly GPL) | **Analogous prior art** — parametric copper on PCB, the *healthy* category. e.g. v1.2.0 (May 2024), KiCad 8. |
| **CapTIvate Design Center** | Texas Instruments | Vendor GUI | **No** — firmware/tuning only | C code, CCS/IAR | Free (closed) | Silicon-locked (MSP430). v1.83 (2020), stable but aging. Design *guidelines* only for geometry. |
| **Infineon CapSense Configurator (ModusToolbox)** | Infineon/Cypress | Vendor GUI | **No** — firmware/widget config only | C init code | Free (closed) | Silicon-locked (PSoC). Active. Geometry only in design-guide PDFs. |
| **QTouch tools (START / MPLAB / Composer)** | Microchip/Atmel | Vendor GUI | **No** — firmware/tuning only | C code | Free (closed) | Silicon-locked. Diamond/slider/wheel geometry only in app-note PDFs (QTAN0079, AN2934). |
| **Azoteq per-device IQS GUIs** | Azoteq | Vendor GUI | **No** — register/tuning only | C header (`.h`) | Free (closed) | Silicon-locked. Geometry only in AZD125 / AZD068 guides. |
| **STM32CubeMX TouchSensing** | STMicroelectronics | Vendor GUI | **No** — firmware/tuning only | `.ioc` + C | Free (closed) | Silicon-locked (STM32). Geometry only in AN4312 / AN5105. |
| **NXP Touch / TSS + Config Tools** | NXP | Vendor GUI/library | **No** — firmware/tuning only | C source | Free (closed) | Silicon-locked. Geometry only in AN3863 / AN3747 / AN12082. |
| **Renesas QE for Capacitive Touch** | Renesas | Vendor e² studio plugin | **No** — firmware/tuning only | C code, param `.h` | Free (closed) | Silicon-locked (RA/RX/RL78). Active (v4.3.0, Mar 2026). Requires board *already* laid out. |
| **Semtech EVK GUI (SX9xxx / PerSe)** | Semtech | Vendor GUI | **No** — register/tuning only | Register config | Bundled w/ EVK | Silicon-locked. SAR proximity sensors. Active. |

> **Headline finding:** No touch-silicon vendor tool generates copper electrode
> geometry; they configure firmware and emit C / register files only, and ship
> geometry as **written design guidelines** (PDF app notes). In open source the
> touch-specific generators that *do* produce real geometry are all **tiny,
> single-purpose, and mostly dormant or archived**. The well-maintained,
> general, GUI/CLI parametric touch-electrode generator emitting native KiCad
> copper **does not exist**.

---

## 1. KiCad-native capabilities & plugins

### 1.1 Footprint wizards (official, bundled) — the canonical touch generators

KiCad ships a collection of Python "footprint wizards" accessible from the
Footprint Editor; they "allow you to see the footprint rendered with parameters
you can edit." Two are directly on-target:

- **`touch_slider_wizard.py`** — parametric capacitive touch slider. Lets you
  choose between a button ("digital") and a slider ("analog").
- **`mutualcap_button_wizard.py`** — "a Wizard for Mutual Capacitance Touch
  Buttons," with parameters for pad width/height, outer/inner electrode width,
  and an option to draw a line around the button. It was added to generate
  capacitive-touch button footprints with measurements based on Microchip's
  **QTAN0079** documentation.

Sources:
[touch_slider_wizard.py](https://github.com/KiCad/kicad-footprint-wizards/blob/master/touch_slider_wizard.py),
[mutualcap_button_wizard.py](https://github.com/KiCad/kicad-footprint-wizards/blob/master/mutualcap_button_wizard.py),
[PR #6 (mutual-cap button wizard)](https://github.com/KiCad/kicad-footprint-wizards/pull/6),
[bundled plugins dir](https://github.com/KiCad/kicad-source-mirror/tree/master/pcbnew/python/plugins).

**Maturity / caveats (important for a tool evaluator):**

- The GitHub repo `KiCad/kicad-footprint-wizards` is **archived (read-only since
  May 9, 2023)**, ~22 stars, ~15 commits, GPL-3.0+. The wizard files are present
  (incl. both touch wizards). ([repo](https://github.com/KiCad/kicad-footprint-wizards))
- The GitLab home `gitlab.com/kicad/code/kicad-footprint-wizards` is likewise
  **dormant** (~11 commits, created Dec 2019, GPL-3.0+, no recent activity).
  ([GitLab](https://gitlab.com/kicad/code/kicad-footprint-wizards))
- These wizards are bundled with KiCad, but coverage is limited: **slider and
  mutual-cap button only — no wheel/rotary, no XY pad/diamond grid** — and there
  is no active development. (A merge request `!5` proposed an improved slider
  wizard adding self-cap "normal mode" vs. split mutual-cap electrodes.)

### 1.2 kicad-footprint-generator (community framework)

`pointhi/kicad-footprint-generator` is a Python framework that produces
`.kicad_mod` files; many footprints in the official KiCad library were created
with it. It is **not** official KiCad software per se but feeds the official
libraries.

- GitHub mirror **archived Oct 7, 2020** (read-only), ~199 stars, GPL-3.0+,
  redirected to GitLab (`gitlab.com/kicad/libraries/kicad-footprint-generator`).
- **No touch/capacitive footprints** — it targets connectors, packages,
  inductors, etc. Useful as an architecture reference, not a touch tool.

Source: [pointhi/kicad-footprint-generator](https://github.com/pointhi/kicad-footprint-generator).

### 1.3 Custom-shaped pads & the `.kicad_mod` S-expression format

KiCad footprints (`.kicad_mod`) are plain-text S-expression files that can be
generated/edited programmatically or by hand. Copper electrode shapes are
expressed as **custom pads with polygon primitives**: in the pad properties
"Custom Shape Primitives" tab you "Add Primitive" → "Polygon"; you can also draw
graphics and "Create pad from selected shapes." Custom shapes can be entered
point-by-point or by editing the `.kicad_mod` file directly in a text editor.

A documented limitation: KiCad custom-pad primitives support arcs, **but not arcs
as part of a polygon**, which matters for smooth curved electrodes (wheels,
curved sliders). 

Sources:
[SMD custom-shape primitives (forum)](https://forum.kicad.info/t/smd-pad-custom-shape-primitives/26393),
[PAD class reference](https://docs.kicad.org/doxygen/classPAD.html),
[footprints from drawings](https://flaviutamas.com/2019/footprint-from-drawing).

This is the key enabler for a parametric generator: emit `.kicad_mod` with
polygon custom-pad primitives (or zones, for DRC-clean copper).

### 1.4 Scripting / API surface

- **Legacy SWIG `pcbnew` Python bindings** — long-standing API; can build
  footprints and pads programmatically (the footprint wizards use this path).
  **Deprecated as of KiCad 9.0**, with the current plan to **remove SWIG in
  KiCad 11.0**. ([dev-docs: APIs and bindings](https://dev-docs.kicad.org/en/apis-and-binding/index.html))
- **New IPC API (KiCad 9.0+)** — language-agnostic, stable interface built on
  Protocol Buffers + NNG over UNIX sockets; the recommended path forward. In
  **KiCad 9.0 it is only implemented in the PCB editor** and is "equivalent to
  the Action Plugins system" — i.e. it interacts with a *running PCB editor
  session*. The docs do **not** confirm footprint-library creation via the IPC
  API, and note that even file plotting/export was not available until KiCad 11.
  This means, as of mid-2026, the **mature path for programmatic footprint
  generation is still the (deprecated) SWIG bindings or direct `.kicad_mod`
  emission**, not the IPC API. ([IPC API for add-on developers](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/),
  [kicad-python (PyPI)](https://pypi.org/project/kicad-python/),
  [kicad-python docs](https://docs.kicad.org/kicad-python-main/kicad.html))
- **kicad-python** — Pythonic wrapper over the IPC API; first release is
  PCB-editor-focused, intended as a transition path from SWIG plugins.
- **Action Plugins** — Python plugins (`pcbnew.ActionPlugin`) shown under
  *Tools → External Plugins*, optionally as toolbar buttons; the standard way to
  ship a GUI plugin today.

**Implication for the new tool:** a CLI that emits `.kicad_mod` directly is the
most robust, version-stable approach (no dependency on the in-flux API);
an Action Plugin can wrap it for a GUI. Avoid betting solely on the IPC API for
footprint creation until it gains library/footprint authoring.

### 1.5 Existing KiCad touch-specific plugins / scripts

- **ESCPT — Electrostatic Capacitive Pad Tool** (`hanya/ESCPT`): a Python macro
  run from the Pcbnew scripting console that generates **mutual-capacitance pads
  as KiCad zones** (so DRC works): Type A (through-hole + GND centerline), Type B
  (SMD), Type C (B + back-side separator). Parameters include outer radius, inner
  pad radius, gap widths, corner resolution. GPLv3. ~15 stars, ~4 commits,
  **unmaintained**. ([ESCPT](https://github.com/hanya/ESCPT)) — *the most
  KiCad-native "real copper" touch generator found, but tiny and dormant.*
- **idc_kicad** (`lionnus/idc_kicad`): Python tool that generates an
  interdigitated capacitor and outputs `.kicad_mod`. Params: track width, gap,
  width/finger length, finger count, optional connecting track. GPL-3.0. ~2
  stars, 7 commits, **early/dormant**. ([idc_kicad](https://github.com/lionnus/idc_kicad))
- **PCM (Plugin and Content Manager) registry**: the PCM lets users discover and
  install Python plugins, libraries, and themes from repositories. A targeted
  search surfaced **no capacitive-touch slider/wheel/pad plugin in the PCM
  registry**. ([PCM browser](https://www.kicad.org/pcm/),
  [PCM docs](https://docs.kicad.org/9.0/en/kicad/kicad.html))
- **Hackaday.io "Capacitive Touch in KiCAD"**: documents the *manual* workflow
  (fill tool, graphic polygon tool, polygonal pad tool, then move to copper) and
  explicitly notes **no dedicated generator or plugin** — confirming the gap.
  References a fixed example footprint (`jspark311/SX8634-Breakout`) and an old
  forum thread. ([Hackaday.io page](https://hackaday.io/page/6779-capacitive-touch-in-kicad))

### 1.6 SVG-to-PCB workflows

- **svg2shenzhen** (`badgeek/svg2shenzhen`): Inkscape extension converting
  arbitrary SVG layers (named `F.Cu`, `B.Cu`, `Edge.Cuts`, etc.) into
  `.kicad_pcb` / `.kicad_mod`. The de-facto way to get arbitrary parametric SVG
  copper into KiCad. ~862 stars, GPL-3.0, but **discontinued** (last release
  v0.2.18.7, Mar 2025; author recommends *Gingerbread* instead). Limitations:
  needs Inkscape 1.0+; edge cuts must be outline-only; drill layers can't use
  grouped objects; complex inner cut-outs must be separate paths. Not
  touch-specific. ([svg2shenzhen](https://github.com/badgeek/svg2shenzhen))
- **svg2mod**: SVG → KiCad footprint module ([svg2mod on PyPI](https://pypi.org/project/svg2mod/)).
- **Limitation pattern:** SVG bridges work but require an external editor +
  manual layer discipline, and curved/filled-shape fidelity is fiddly. Direct
  `.kicad_mod` emission avoids this.

---

## 2. Vendor design tools (touch-silicon vendors — the most important prior art)

**Confirmed across every vendor examined:** these tools do **firmware
configuration and sensitivity tuning only**. None generates real PCB copper
geometry (electrode shapes), and none exports to CAD / Gerber / DXF / footprint
libraries. PCB electrode geometry is universally delivered as **written design
guidelines** (application-note PDFs with recommended dimensions, spacing, and
reference patterns) that an engineer applies by hand in their own ECAD tool. The
only "export" these tools produce is C source / headers / register-config files.

### 2.1 Microchip / Atmel — QTouch

- **Tools:** QTouch via Atmel START / MPLAB Harmony / QTouch Configurator,
  QTouch Modular Library (PTC). These configure firmware and tune sensitivity.
- **Geometry?** **No.** Microchip's own "Surface Sensor Design Guide" provides
  only **design guidelines** — e.g. rhombus (diamond) size 3–5 mm, 0.5 mm
  edge-to-edge gap, conceptual "5×6 surface" layouts — and **no tool to generate
  the diamond-pattern copper automatically**; users implement specs manually.
  ([Surface Sensor Design Guide](https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/start-qtouch-capacitive-sensing-library/design-guides/surface-sensor-design-guide/))
- **Key design guides (geometry knowledge):** **QTAN0079** "Buttons, Sliders and
  Wheels Sensor Design"
  ([PDF](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ApplicationNotes/ApplicationNotes/doc10752.pdf)),
  "Secrets of a Successful QTouch Design"
  ([PDF](https://ww1.microchip.com/downloads/en/Appnotes/an-kd02_103-touch_secrets.pdf)),
  AT11805 long slider, AT02259 layout checklist, AN2934 (canonical ~5 mm-pitch
  diamond). Note: QTAN0079 is the same doc the KiCad mutual-cap wizard is based on.
- **Export / free / lock-in:** C code; free; Atmel/Microchip silicon only.
- **CAD generation exists only *outside* their tools** — via Altium's QTouch
  IntLib (see §3.1), not in QTouch itself.

### 2.2 Infineon / Cypress — CapSense

- **Tools:** CapSense Configurator in **ModusToolbox** (and the CapSense
  component in legacy PSoC Creator); CapSense Tuner for live tuning.
- **Geometry?** **No.** The Configurator produces **middleware init code, device
  init code, and tuning parameters** — it contains **no PCB copper geometry,
  footprints, layout files, or CAD exports**. Physical design is handled
  separately per the CapSense Design Guide. Supported *widgets* (buttons, matrix
  buttons, sliders, touchpads, proximity) are firmware constructs.
  ([CapSense middleware ref](https://infineon.github.io/capsense/capsense_api_reference_manual/html/index.html),
  [CapSense controllers](https://www.infineon.com/products/microcontroller/sensing-controller/capsense-controllers))
- **Key design guide:** **AN85951** "PSoC 4 and PSoC 6 CapSense Design Guide"
  (recommended electrode shapes/sizes, diamond patterns)
  ([Infineon doc page](https://documentation.infineon.com/html/psoc6/epf1667481159393.html)),
  AN65973.
- **Export / free / lock-in:** C init code; free; PSoC silicon only; actively
  maintained.

### 2.3 Texas Instruments — CapTIvate

- **Tool:** CapTIvate Design Center (CDC). Drag-and-drop GUI to place sensing
  elements (buttons, sliders, wheels, proximity, TrackPad/XY), pick self/mutual
  mode, map sensors to MSP430 **pins** ("Auto Assign" assigns MCU pins, not
  copper), generate code, then tune live.
- **Geometry?** **No** — workflow is place → configure → map-to-pins → generate
  source → tune; no PCB electrode geometry / footprints / CAD output. Export: C
  source + CCS/IAR projects. Free; MSP430-locked; **v1.83 (May 2020)** — stable
  but unchanged ~6 years.
  ([MSPCAPTDSNCTR](https://www.ti.com/tool/MSPCAPTDSNCTR),
  [CapTIvate Design Center guide](https://software-dl.ti.com/msp430/msp430_public_sw/mcu/msp430/CapTIvate_Design_Center/1_83_00_08/exports/docs/users_guide/html/CapTIvate_Technology_Guide_html/markdown/ch_designcenter.html))
- **Geometry knowledge** lives in the **CapTIvate Technology Guide "Design Guide"
  chapter** (self-cap buttons 4–15 mm, mutual RX/TX ~0.5 mm spacing, sliders/
  wheels 3–12 elements at 3–7 mm pitch, touchpad spacing, 25% hatched ground)
  ([Design Guide](https://software-dl.ti.com/msp430/msp430_public_sw/mcu/msp430/CapTIvate_Design_Center/latest/exports/docs/users_guide/html/CapTIvate_Technology_Guide_html/markdown/ch_design_guide.html)).
- **Notable exception:** TI separately ships the **SLAA891 OpenSCAD scripts**
  that *do* generate geometry — but those are tool-agnostic OpenSCAD, not part of
  the Design Center (see §4.2 below).

### 2.4 Azoteq — ProxFusion / IQS

- **Tools:** per-device debug/config GUIs (IQS7222A, IQS323, IQS7229A, …) for
  real-time register config, tuning, data logging; plus programming utilities.
- **Geometry?** **No.** Export is a **C header (`.h`) register config**; no CAD.
  Free; each GUI is locked to one Azoteq IC (often needs matching eval hardware);
  active product line.
  ([Azoteq software & tools](https://www.azoteq.com/design/software-and-tools/))
- **Geometry knowledge:** **AZD125** Capacitive Sensing Design Guide (overlay,
  trace width, electrode pitch / gaps for sliders/wheels)
  ([AZD125 PDF](https://www.azoteq.com/images/stories/pdf/azd125_capacitive_sensing_design_guide_v1.0.pdf)),
  **AZD068** Trackpad Design Guidelines (diamond Rx/Tx XY), AZD076 (curved/3D),
  IQS5xx-B000 trackpad datasheet
  ([PDF](https://www.azoteq.com/images/stories/pdf/iqs5xx-b000_trackpad_datasheet.pdf)).
  *(Azoteq's IQS9150 + timonsku's generator powered the MNT Reform Next trackpad
  — see §5.)*

### 2.5 STMicroelectronics — STM32 TSC / TouchSensing

- **Tools:** **STM32CubeMX TouchSensing** (configures the on-chip TSC peripheral,
  picks sensor type proximity/button/linear/rotary, enables middleware) +
  STMTouch/TouchSensing middleware.
- **Geometry?** **No.** CubeMX outputs `.ioc` + C; middleware is firmware. No
  CAD/Gerber/DXF. Free; STM32-locked; CubeMX active, middleware in maintenance.
  ([stm32-mw-touchsensing](https://github.com/STMicroelectronics/stm32-mw-touchsensing),
  [STM32CubeMX](https://www.st.com/en/development-tools/stm32cubemx.html))
- **Geometry knowledge:** **AN4312** surface-sensor design (electrode sizes,
  grounded mesh fill, slider/rotary patterns)
  ([AN4312 PDF](https://www.st.com/resource/en/application_note/an4312-how-to-design-surface-sensors-for-touch-sensing-applications-on-stm32-mcus-stmicroelectronics.pdf)),
  **AN5105** getting started (Rev 5, Nov 2024)
  ([AN5105 PDF](https://www.st.com/resource/en/application_note/an5105-getting-started-with-touch-sensing-control-on-stm32-microcontrollers-stmicroelectronics.pdf)).

### 2.6 NXP — TSI / Touch Sensing Software

- **Tools:** NXP Touch (MCUXpresso middleware + GUI config tool, rotary/slider/
  keypad decoders, auto-tuning); legacy Xtrinsic TSS; MCUXpresso Config Tools;
  FreeMASTER (live tuning).
- **Geometry?** **No.** GUIs emit C source/config; FreeMASTER tunes; no CAD.
  Free; NXP-MCU-locked; NXP Touch active, TSS legacy.
  ([NXP Touch for KE15Z](https://www.nxp.com/design/design-center/software/development-software/mcuxpresso-software-and-tools-/nxp-touch-solution-for-kinetis-ke15z-mcu-family:TOUCH-SOFTWARE),
  [TSS](https://www.nxp.com/products/TSSMCU))
- **Geometry knowledge:** **AN3863** electrode design
  ([PDF](https://www.nxp.com/docs/en/application-note/AN3863.pdf)),
  AN3747 pad layout, **AN12082** slider zigzag/chevron segments
  ([PDF](https://www.nxp.com/docs/en/application-note/AN12082.pdf)),
  AN12190/AN12933 (2D/trackpad diamonds).

### 2.7 Renesas — CTSU / QE for Capacitive Touch

- **Tool:** **QE for Capacitive Touch** (free e² studio plugin) — initial touch-UI
  config + automatic/manual sensitivity tuning of an **already-built** board.
- **Geometry?** **No — explicitly.** QE "does not generate PCB layouts… firmware
  configuration only" and "requires that PCB electrodes are already designed and
  laid out before engaging the QE tool." Export: `qe_touch_sample.c` +
  `qe_touch_define.h`. Free; RA/RX/RL78-locked; **actively maintained (v4.3.0,
  Mar 24 2026)**.
  ([QE for Capacitive Touch](https://www.renesas.com/en/software-tool/qe-capacitive-touch-development-assistance-tool-capacitive-touch-sensors))
- **Geometry knowledge:** **R30AN0389** CTSU Electrode Design Guide (Rev 2.10,
  Apr 2025, 93 pp.; reference patterns for self/mutual buttons, sliders, wheels,
  matrix)
  ([doc page](https://www.renesas.com/en/document/apn/capacitive-sensor-microcontrollers-ctsu-capacitive-touch-electrode-design-guide?language=en)).

### 2.8 Semtech — SAR / capacitive proximity (SX9xxx / PerSe)

- **Tool:** Evaluation Kit GUI (register config, cap-sensing settings, proximity
  thresholds, real-time cap graphing).
- **Geometry?** **No — explicit.** Register config + monitoring only; no
  footprints/CAD. Export: register/config values + logged data. Bundled free with
  EVK; SX9xxx-locked; active (PerSe shown at CES 2026). Datasheets describe the
  sensor as "a simple copper area on a PCB or FPC" — textual rules, not generated
  geometry.
  ([Semtech SAR sensors](https://www.semtech.com/products/smart-sensing/sar-sensors),
  [PerSe Connect](https://www.semtech.com/products/smart-sensing/perse-connect))

> **Source-quality caveats (vendor area):** TI, Azoteq, Microchip, and Infineon
> primary pages were fetched cleanly. Several ST / NXP / Renesas / Semtech PDFs
> were inaccessible to the fetcher (timeouts, size limits, an Akamai geo-block on
> nxp.com, and login gating on Semtech). Tool *capability / lock-in / maturity*
> claims were confirmed from directly fetched pages or strongly corroborated
> search excerpts; exact dimensional figures in some guideline PDFs come from
> search snippets and would need manual transcription if precise numbers become
> load-bearing.

---

## 3. Non-KiCad EDA ecosystem

### 3.1 Altium Designer — the only commercial EDA with a native generator

- **"Designing with Touch Controls"** (built-in): you place/configure a vendor
  sensor component on the schematic, set parameters, and on Update-to-PCB (ECO)
  Altium **auto-generates the actual copper electrode pattern** (regions/
  polygons). Covers buttons/keys (0-D), linear sliders (1-D), and wheels
  (rotational), with size variants. **Real PCB geometry: yes.** Closed-source.
  ([Altium Touch Controls](https://www.altium.com/documentation/altium-designer/designing-with-touch-controls))
  - **Caveats:** built around **legacy vendor modules** (Atmel QTouch/QMatrix,
    Cypress CapSense/PSoC, Microchip mTouch) — branding from now-acquired
    companies — and there's **no native general XY diamond-grid trackpad**
    generation (buttons/sliders/wheels only). The landing page was updated as
    recently as Dec 2025, so the feature still ships.
    ([Atmel touch controls (v18)](https://www.altium.com/documentation/18.0/display/ADES/((Atmel+Touch+Controls))_AD),
    [Cypress touch controls (v21)](https://www.altium.com/documentation/altium-designer/designing-with-cypress-touch-controls?version=21))
- **Microchip Touch Sensor Plugin for Altium** (vendor extension): configure
  sensor in the symbol, generate layout on ECO. Docs demonstrate **"ButtonSelf"**
  and **"Surface Diamond"** patterns (so diamonds, at least for buttons). Vendor
  library `Microchip Touch Sensors.IntLib`. Closed-source.
  ([install guide](https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/touch-sensor-altium-designer-plugin/guide-to-install-touch-sensor-plugin-in-altium/),
  [use guide](https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/touch-sensor-altium-designer-plugin/guide-to-use-touch-sensor-plugin-in-altium/),
  [Altium touch-sensor resource](https://resources.altium.com/p/implementing-touch-sensors))
- **Altium scripting API + community scripts:** Altium's Delphi/VBScript PCB API
  can draw polygons programmatically (sides, radius, track width, rotation).
  General script collections exist
  ([AltiumScriptCentral](https://github.com/gbmhunter/AltiumScriptCentral),
  [altium-scripts-libraries](https://github.com/dcconn/altium-scripts-libraries)),
  but **no community/marketplace script dedicated to capacitive-touch electrode
  generation was found** — users rely on the built-in Touch Controls, the
  Microchip plugin, or importing TI's DXF.

### 3.2 Autodesk Eagle / Fusion 360 Electronics

- **appfruits/RotarySensor** (Eagle ULP): `qslice.ulp` generates the **real
  copper pattern** for a rotary click-wheel; `touch_pcb.ulp` generates the
  outline (QTouch-compatible). ~8 stars, 4 forks, **not actively developed**.
  ([RotarySensor](https://github.com/appfruits/RotarySensor))
- **PatternAgents Touch Widgets Library** (Eagle): a pre-made **static library**
  of buttons (incl. backside-LED), linear/radial sliders, and X/Y touchpads in
  fixed sizes — **not a generator** (you pick a size, not parametric). CC BY-SA
  4.0. From Nov 2013, some footprints "experimental", **effectively
  unmaintained**.
  ([PatternAgents announcement](https://patternagents.github.io/news/2013/11/24/eagle-touch-widgets-library.html),
  [Adafruit writeup](https://blog.adafruit.com/2013/12/20/cap-touch-library-for-eagle/))
- **Fusion 360 / library.io parametric footprints:** Autodesk's parametric
  footprint generation targets **standard IC packages** (QFP, DFN, SOT, …), not
  touch electrodes. **No touch-specific generator found** beyond the Eagle ULP
  above.
  ([Fusion ULP blog](https://www.autodesk.com/products/fusion-360/blog/fusion-360-electronics-user-language-programming-ulp-scripts/),
  [Hackaday: parametric part generation](https://hackaday.com/2018/03/08/autodesk-introduces-parametric-part-generation/))

### 3.3 Other commercial EDA — manual only

- **Cadence OrCAD / Allegro:** **no** built-in/automated touch generator. The
  recommended approach is manual: import a custom shape via the Padstack Editor
  or draw shapes by hand.
  ([Cadence community thread](https://community.cadence.com/cadence_technology_forums/pcb-design/f/pcb-design/42607/capacitive-touch-button))
- **DipTrace:** **no** dedicated touch generator. Users build pads manually
  (copper pours, filled polygons converted to pads), one component per button
  size.
  ([DipTrace forum thread](https://diptrace.com/forum/viewtopic.php?t=9536))

**Bottom line (non-KiCad EDA):** Only Altium ships a native parametric electrode
generator, and it's legacy-branded and limited to buttons/sliders/wheels (no
general XY diamond). OrCAD/Allegro and DipTrace have nothing. Fusion/Eagle's
parametric tooling is for IC packages. The practical cross-tool answer is to
**leave the EDA** and generate geometry in OpenSCAD (TI SLAA891 / timonsku) then
import DXF / Eagle-XML.

---

## 4. Generic / parametric / programmatic geometry generators

### 4.1 GDSII-family libraries — capable but not PCB-oriented

- **gdstk** ([repo](https://github.com/heitzmann/gdstk)) / **gdspy**
  ([repo](https://github.com/heitzmann/gdspy)): C++/Python GDSII/OASIS libraries
  with Boolean polygon ops and offsetting. Technically capable of comb/IDE
  geometry, but **IC/MEMS/photonics-oriented**; **no evidence of use for PCB
  touch electrodes**, and GDSII doesn't map cleanly to PCB fab (you'd need a
  GDS→Gerber/DXF bridge). gdspy is bug-fix-only; author points to gdstk.
- **gdsfactory** ([repo](https://github.com/gdsfactory/gdsfactory),
  [docs](https://gdsfactory.github.io/gdsfactory/)): MIT, very active Python
  layout library targeting "chips, **PCBs**, and 3D-printable objects." Ships the
  exact primitives — confirmed `interdigital_capacitor()` and
  `interdigitated_electrodes()` (finger count/width/length/gap, bus dims, layer)
  ([components](https://gdsfactory.github.io/gdsfactory/components.html)) — and
  exports **GDS, OASIS, STL, and Gerber**. **The strongest open-source geometry
  foundation found**, though it's not a touch-sensor tool and has no
  slider/wheel/diamond components or `.kicad_mod` export out of the box.

### 4.2 OpenSCAD-style / OpenSCAD-to-PCB

- **TI SLAA891 OpenSCAD scripts** — BSD-licensed OpenSCAD scripts that
  parametrically generate self-cap **sliders, wheels, curved sliders, and
  touchpads** from a handful of primitives; workflow is edit params → render →
  **export DXF** → import into the EDA and convert to copper regions (the report
  walks through Altium 19 import). The canonical cross-EDA parametric method, but
  **not revised since 2020** and OpenSCAD-centric (no GUI; manual DXF→copper).
  ([SLAA891B PDF](https://www.ti.com/lit/an/slaa891b/slaa891b.pdf),
  scripts: http://www.ti.com/lit/zip/slaa891)
- **Bryan Duxbury — touch wheel in OpenSCAD + EAGLE (2013)**: parametric 3-ring
  interleaved electrodes via OpenSCAD chain-hull, plus a Ruby script to stitch
  DXF segments into ordered polygons. The genealogical root of the Tangara tool.
  ([writeup](https://bryanduxbury.com/2013/12/05/designing-a-capacitive-touch-wheel-in-openscad-and-eagle/))
- **OpenSCAD→PCB reality:** OpenSCAD is a 3D modeller; the practical PCB bridge is
  **DXF import**, and DXF out of OpenSCAD is "just collections of segments" that
  must be stitched into polygons. There is **no clean OpenSCAD→KiCad-copper
  tool** — it's always DXF + manual cleanup, or the SVG bridges in §1.6.

### 4.3 Interdigitated-electrode (IDE) generators

- **lionnus/idc_kicad** — IDE → `.kicad_mod` (see §1.5). Most on-target for KiCad,
  but tiny/dormant.
- **gdsfactory IDE components** — see §4.1 (parametric, Gerber/GDS, MIT, active;
  chip-oriented).
- **trygvrad/Interdigitated-Electrodes**
  ([repo](https://github.com/trygvrad/Interdigitated-Electrodes)): MIT, but
  **computation only** (capacitance + E-field); **does not generate fabricable
  geometry**. Dormant (last release Sep 2020).
- IDE work is common in sensors/microfluidics/biosensors, but the public tools
  there are mostly **analysis/calculators**, not geometry exporters.

### 4.4 KiCad coil / antenna / spiral generators — the analogous prior art

This is the **healthiest** category and the strongest engineering precedent: the
same "parametric copper shape on a PCB" problem, solved and maintained.

| Project | Output | License | Maturity |
|---|---|---|---|
| [SK-Electronics-Consulting/kicad-coil-generators](https://github.com/SK-Electronics-Consulting/kicad-coil-generators) | KiCad footprints via Footprint Wizard | GPL-3.0 | ~11 stars; **v1.2.0 May 2024**, tested on KiCad 8 — actively usable |
| [YugnatD/Kicad-NFC-Coil-Generator](https://github.com/YugnatD/Kicad-NFC-Coil-Generator) | **`.kicad_mod` + DXF + SVG** + image | not stated | ~4 stars, light activity |
| [nideri/nfc_antenna_generator](https://github.com/nideri/nfc_antenna_generator) | KiCad NFC antenna module | — | small |
| [in3otd/spiki](https://github.com/in3otd/spiki) | KiCad spiral inductor; simulates L/Q via FastHenry | — | niche |
| [kicad-coil-creator (Hackaday.io)](https://hackaday.io/project/188200-kicad-coil-creator) | edit `main.py` params → `*.kicad_mod` | — | hobby |

**Takeaway:** parametric **Python emitting `.kicad_mod`** (or driving the
footprint-wizard API), optionally also DXF/SVG, is the established, proven route.
It maps directly onto touch electrodes and is the most credible architecture for
a new tool.

---

## 5. Open-source projects that generate touch electrode geometry

The directly-on-target projects (most also referenced above):

- **KiCad official touch wizards** (`touch_slider_wizard.py`,
  `mutualcap_button_wizard.py`) — §1.1. Slider + mutual-cap button; archived.
- **ESCPT** (`hanya/ESCPT`) — §1.5. Mutual-cap pads as KiCad zones; unmaintained.
- **idc_kicad** (`lionnus/idc_kicad`) — §1.5/§4.3. IDE → `.kicad_mod`; dormant.
- **timonsku/Touchpad-Generator**
  ([repo](https://github.com/timonsku/Touchpad-Generator),
  [Hackaday](https://hackaday.com/2025/03/06/custom-touchpad-pcbs-without-the-pain/))
  — generates a **2D XY diamond-pattern touchpad and a fully-routed board**
  (traces, vias, polygon pours with row/col net names) via OpenSCAD → DXF →
  Python → **Eagle XML `.brd`** (author avoided KiCad's "really complex" file
  format; Eagle XML imports into most EDAs including KiCad). Built for the **MNT
  Reform Next** trackpad (Azoteq IQS9150). ~67 stars but **2 commits, dormant** —
  yet validated on a shipping product. *The most complete XY-trackpad generator
  found.*
- **Tangara "Interpolated Electrode SVG Tool"**
  ([tool](https://cooltech.zone/tangara/labs/touchwheel-electrode-tool/),
  [writeup](https://cooltech.zone/tangara/blog/2024-02-07-touchwheel/)) — web
  app generating a 3-electrode interpolated touch **wheel**; exports **SVG**
  ("usually needs manual processing before it can be used in a PCB"). Recent
  (2024), single-purpose, tied to the shipping Tangara product.
- **appfruits/RotarySensor** (Eagle ULP) — §3.2. Wheel copper; inactive.

**Fixed reference designs (NOT generators)** — useful as test fixtures, not
prior-art generators: `todbot/touchwheels`
([repo](https://github.com/todbot/touchwheels), iPod-style wheels + button pads,
references the Tangara generator), `second-string/capacitive-touch-slider-board-prototype`,
`Tinkerforge/multi-touch-bricklet`, and the microfluidics
`uwmisl/pd-electrodeboard-pcb-v4` (notable for auto-generating its electrode
array via Python — an example of programmatic electrode generation, though for
digital microfluidics, not touch UI).

**Analysis-only / adjacent:** **CapExt** ([capext.com](https://capext.com/)) — a
**commercial** capacitance simulator that *imports* Gerber/DXF touch designs (the
analysis counterpart to a generator, not a generator).

---

## 6. Gaps / opportunities

What is **missing** in the current landscape — i.e. what a new KiCad-focused
parametric CLI/plugin could fill:

1. **No maintained, general, open parametric touch-electrode generator.** The
   touch-specific open-source tools that produce real geometry — KiCad's wizards
   (archived 2023), ESCPT (dormant), idc_kicad (dormant), Touchpad-Generator
   (2 commits), Tangara's web wheel tool — are each **single-purpose and
   mostly unmaintained**. None covers **sliders + wheels + XY diamond grids** in
   one maintained package.

2. **Vendor tools are silicon-locked and geometry-blind.** All eight vendor
   tools surveyed (TI, Infineon, Microchip, Azoteq, ST, NXP, Renesas, Semtech)
   do **firmware/tuning only**, export **C/register files**, and are tied to
   their own MCUs. Their valuable geometry know-how exists **only as PDF design
   guidelines** (QTAN0079, AN85951, AN2934, AZD125/AZD068, AN4312, AN3863,
   R30AN0389, etc.). A new tool could **encode those published dimensions as
   parameter defaults/presets** — vendor-agnostic, no silicon lock-in.

3. **The one native EDA generator (Altium) is closed, legacy-branded, and
   limited.** It covers buttons/sliders/wheels but **not a general XY diamond
   trackpad**, is tied to acquired-vendor modules, and is Altium-only/commercial.
   KiCad — by far the largest open EDA community — has **no equivalent**.

4. **No CLI.** Every existing path is either a GUI (Altium, vendor tools), an
   in-app wizard (KiCad), an Inkscape extension (svg2shenzhen), or an OpenSCAD
   render + manual DXF cleanup. There is **no scriptable, reproducible,
   version-controllable CLI** that takes parameters and emits a ready
   `.kicad_mod` / `.kicad_pcb`. This is valuable for automation, regression
   testing, and parametric design sweeps.

5. **DRC-clean copper is rarely handled.** Most outputs are graphic polygons or
   raw DXF needing manual conversion. ESCPT's approach (emit **KiCad zones** so
   DRC works) is the right idea but isn't general. A new tool emitting custom-pad
   polygons and/or zones with correct nets/clearances would be a real
   improvement. (Note the KiCad limitation: custom-pad **polygons can't contain
   arcs**, so curved electrodes need polygonal approximation.)

6. **Smooth/interpolated geometry is under-served.** Interpolated 3-electrode
   wheels and zig-zag/chevron sliders (which give linear position output) require
   non-trivial geometry; today this lives in scattered one-offs (Tangara,
   Duxbury, NXP AN12082). A parametric generator that does this correctly would
   be differentiated.

7. **Architecture is de-risked.** The coil/antenna generators
   (kicad-coil-generators, NFC generators) prove that **parametric Python →
   `.kicad_mod`** is the reliable, version-stable pattern — independent of the
   in-flux KiCad IPC API (which, in KiCad 9, doesn't yet confirm footprint-
   library authoring, and SWIG is deprecated for removal in KiCad 11). A new tool
   should likely **emit `.kicad_mod` / `.kicad_pcb` S-expressions directly** for
   the CLI core, and optionally wrap it as an Action Plugin for a GUI, optionally
   reusing **gdsfactory** for the underlying parametric geometry/Boolean ops and
   adding KiCad/SVG/Gerber export.

**In one line:** the clear opportunity is a **maintained, vendor-agnostic,
parametric CLI + KiCad plugin** that generates sliders, wheels, and XY diamond
grids as **DRC-clean native KiCad copper**, with defaults encoding the published
vendor design guidelines — something that **does not exist today** in any
ecosystem.

---

## 7. Key references

**KiCad (native, plugins, API)**
- KiCad footprint wizards (archived): https://github.com/KiCad/kicad-footprint-wizards — `touch_slider_wizard.py`, `mutualcap_button_wizard.py`
- KiCad footprint wizards (GitLab): https://gitlab.com/kicad/code/kicad-footprint-wizards
- kicad-footprint-generator: https://github.com/pointhi/kicad-footprint-generator
- KiCad APIs & bindings (dev docs): https://dev-docs.kicad.org/en/apis-and-binding/index.html
- IPC API for add-on developers: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
- kicad-python (PyPI): https://pypi.org/project/kicad-python/
- KiCad PCM browser: https://www.kicad.org/pcm/
- ESCPT (capacitive pad tool): https://github.com/hanya/ESCPT
- idc_kicad (interdigitated capacitor): https://github.com/lionnus/idc_kicad
- Custom-pad primitives (forum): https://forum.kicad.info/t/smd-pad-custom-shape-primitives/26393
- Hackaday.io "Capacitive Touch in KiCAD": https://hackaday.io/page/6779-capacitive-touch-in-kicad
- svg2shenzhen: https://github.com/badgeek/svg2shenzhen ; svg2mod: https://pypi.org/project/svg2mod/

**Vendor tools & design guides**
- TI CapTIvate Design Center: https://www.ti.com/tool/MSPCAPTDSNCTR ; Design Guide: https://software-dl.ti.com/msp430/msp430_public_sw/mcu/msp430/CapTIvate_Design_Center/latest/exports/docs/users_guide/html/CapTIvate_Technology_Guide_html/markdown/ch_design_guide.html
- TI SLAA891 (OpenSCAD geometry): https://www.ti.com/lit/an/slaa891b/slaa891b.pdf ; scripts: http://www.ti.com/lit/zip/slaa891
- Microchip Surface Sensor Design Guide: https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/start-qtouch-capacitive-sensing-library/design-guides/surface-sensor-design-guide/
- Microchip QTAN0079 (buttons/sliders/wheels): https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ApplicationNotes/ApplicationNotes/doc10752.pdf
- Microchip Touch Sensor Plugin for Altium: https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/touch-sensor-altium-designer-plugin/guide-to-use-touch-sensor-plugin-in-altium/
- Infineon CapSense middleware ref: https://infineon.github.io/capsense/capsense_api_reference_manual/html/index.html ; AN85951: https://documentation.infineon.com/html/psoc6/epf1667481159393.html
- Azoteq software & tools: https://www.azoteq.com/design/software-and-tools/ ; AZD125: https://www.azoteq.com/images/stories/pdf/azd125_capacitive_sensing_design_guide_v1.0.pdf
- ST stm32-mw-touchsensing: https://github.com/STMicroelectronics/stm32-mw-touchsensing ; AN4312: https://www.st.com/resource/en/application_note/an4312-how-to-design-surface-sensors-for-touch-sensing-applications-on-stm32-mcus-stmicroelectronics.pdf
- NXP Touch (KE15Z): https://www.nxp.com/design/design-center/software/development-software/mcuxpresso-software-and-tools-/nxp-touch-solution-for-kinetis-ke15z-mcu-family:TOUCH-SOFTWARE ; AN3863: https://www.nxp.com/docs/en/application-note/AN3863.pdf
- Renesas QE for Capacitive Touch: https://www.renesas.com/en/software-tool/qe-capacitive-touch-development-assistance-tool-capacitive-touch-sensors
- Semtech SAR / PerSe: https://www.semtech.com/products/smart-sensing/sar-sensors

**Non-KiCad EDA**
- Altium "Designing with Touch Controls": https://www.altium.com/documentation/altium-designer/designing-with-touch-controls
- appfruits/RotarySensor (Eagle ULP): https://github.com/appfruits/RotarySensor
- PatternAgents Eagle Touch Widgets: https://patternagents.github.io/news/2013/11/24/eagle-touch-widgets-library.html
- Cadence Allegro touch thread: https://community.cadence.com/cadence_technology_forums/pcb-design/f/pcb-design/42607/capacitive-touch-button
- DipTrace forum: https://diptrace.com/forum/viewtopic.php?t=9536

**Parametric / programmatic geometry & analogous prior art**
- gdsfactory: https://github.com/gdsfactory/gdsfactory ; components: https://gdsfactory.github.io/gdsfactory/components.html
- gdstk: https://github.com/heitzmann/gdstk ; gdspy: https://github.com/heitzmann/gdspy
- timonsku/Touchpad-Generator: https://github.com/timonsku/Touchpad-Generator (Hackaday: https://hackaday.com/2025/03/06/custom-touchpad-pcbs-without-the-pain/)
- Tangara touchwheel electrode tool: https://cooltech.zone/tangara/labs/touchwheel-electrode-tool/ (writeup: https://cooltech.zone/tangara/blog/2024-02-07-touchwheel/)
- Bryan Duxbury touch wheel (OpenSCAD+EAGLE): https://bryanduxbury.com/2013/12/05/designing-a-capacitive-touch-wheel-in-openscad-and-eagle/
- todbot/touchwheels: https://github.com/todbot/touchwheels
- kicad-coil-generators: https://github.com/SK-Electronics-Consulting/kicad-coil-generators
- YugnatD NFC coil generator: https://github.com/YugnatD/Kicad-NFC-Coil-Generator
- trygvrad/Interdigitated-Electrodes (analysis only): https://github.com/trygvrad/Interdigitated-Electrodes
- CapExt (commercial cap simulator): https://capext.com/
