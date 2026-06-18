# Capacitive Touch PCB Design Guidelines

**Scope.** This document consolidates concrete, numeric, vendor-sourced PCB design rules for **self-capacitance and mutual-capacitance touch electrodes**, focused on the three interface types we intend to parametrically generate as KiCad footprints: **linear sliders**, **wheels / rotary sliders**, and **XY pads / trackpads (diamond matrices)**. It also captures the **shared layout rules** (ground, traces, vias, overlay, ESD, parasitic-capacitance budget) that apply to all of them.

The emphasis is on numbers a generator can consume: dimensions (mm), ratios, fill percentages, resistor values, and capacitance budgets. Every nontrivial number is attributed to a primary vendor application note. Where vendors disagree, the range is reported and attributed. Numbers that are *our own* reasonable defaults (not vendor-sourced) are explicitly labelled **[OUR DEFAULT]**.

**Date compiled:** 2026-06-17.

**Primary vendors surveyed:** Microchip / Atmel (QTouch / PTC), Infineon / Cypress (CapSense), Texas Instruments (CapTIvate), Azoteq (ProxSense / IQS), STMicroelectronics (TSC / STMTouch).

---

## 1. Capacitive sensing primer (self-cap vs mutual-cap)

Two sensing topologies dominate, and they drive different electrode geometries.

| | **Self-capacitance** | **Mutual-capacitance** |
|---|---|---|
| Vendor names | QTouch (Microchip), CSD (Infineon), self-cap (TI/Azoteq/ST) | PTC mutual / QMatrix (Microchip), CSX (Infineon), projected/mutual (TI/Azoteq/ST), Rx/Tx (ST) |
| Pins per node | 1 electrode = 1 pin | 1 drive (Tx/X) + 1 sense (Rx/Y) pair; an N×M grid uses N+M pins |
| What a finger does | Adds capacitance from electrode → earth ground (Cx increases) | *Reduces* the coupling capacitance between the Tx and Rx electrodes |
| Multi-touch | No (single point; "ghost" touches on grids) | Yes (each row×column intersection is an independent node) |
| Moisture / noise | More susceptible | Better moisture rejection, less EM crosstalk (Azoteq AZD125 §6.2) |
| Typical use here | Buttons, sliders, wheels | XY pads / trackpads, optionally sliders/wheels |

Key consequences for the generator:

- **Self-cap sliders/wheels** are a row/ring of individually-sensed electrodes; position comes from interpolating the signal across adjacent electrodes (centroid).
- **Mutual-cap trackpads** are a diamond grid where each row and column cross; crossovers must be bridged (vias to a 2nd layer, or jumpers).
- Self-cap sensitivity *degrades* as the electrode's parasitic capacitance (Cp) rises; mutual-cap sensitivity is largely independent of Cp (Infineon AN85951 §7.4.1).

The standard **finger contact model** across all vendors is a disc of **~8 mm diameter** (range 5–10 mm) — Microchip AN2934 §1.1; Infineon AN85951 (~9 mm); Azoteq AZD125 §6.1.1.

---

## 2. Sliders (linear)

### 2.1 Construction & why interpolation needs multiple electrodes

A slider is a 1-D array of electrodes; firmware computes a **centroid** by interpolating the touch signal across the electrode under the finger and its neighbours. For the interpolation to be continuous, **the finger must always overlap ≥2 electrodes** — which is why the electrode pitch is sized to roughly **half a finger width (~4–5 mm)** so that 2–3 electrodes sit under the contact at all times (Microchip AN2934 §1.2.3; Azoteq AZD125 §6.1.1).

- Infineon: the 3-point centroid uses the max segment and both neighbours, so meaningful interpolation needs the touched segment **plus both neighbours**; a 5-segment slider can resolve ≥100 physical positions (AN85951 §2.4.2, §7.4.4).
- Microchip self-cap sliders use **3 active channels** ("two-plus-two-half"), with the centre channel split (QTAN0079 §5.3.1).
- ST: a "normal patterned" (RC) slider uses **5–8 electrodes**; an interlaced charge-transfer slider uses **3** (AN2869 §4.3).
- TI/Azoteq: **3–4 elements** is standard, **8 max** (TI CapTIvate Design Guide; Azoteq AZD125 Tables 6.1/6.2).

**Consensus: ≥3 electrodes** for a usable interpolated slider.

### 2.2 Why straight bars are bad → interleaved/chevron/interdigitated shapes

Plain rectangular bars interpolate only briefly at the crossover; most of the time the finger sits on a single electrode, giving a staircase (non-linear) position output (Microchip AN2934 §1.2.3; Azoteq AZD125 §6.1.1: "a pitch bigger than ~8 mm with no interdigitation will lead to poor coordinates").

The fix is to **stretch the crossover** so two electrodes are always partially covered. Two geometries are used:

- **Chevron / sawtooth / tapered overlap** (Microchip "extended interpolation", AN2934 Fig 1-12): triangular/zig-zag interleaved edges. ST calls this the **interlaced crisscross / zig-zag** pattern (AN2869 §4.3.2).
- **Interdigitated teeth** (Azoteq AZD125 §6.1; Microchip QTAN0079 §5.3.3; TI: "each electrode is inter-digitated"). For 2-layer mutual sliders the slant alternates "to give a zig-zag effect" (Microchip QTAN0079 §6.3.5.2).
- Caution: interdigitated electrodes have long parallel edges → higher load capacitance to neighbours, so they need **larger inter-electrode gaps** (Azoteq AZD125 §6.1.3).
- **ESD:** round all corners; **truncate triangle/tooth tips to a rounded end ~2 mm diameter** (Microchip AN2934 §1.2.3; Azoteq AZD125 §6.1.3).

### 2.3 Numeric slider dimensions (by vendor)

Self-cap, **non-interpolated** (discrete keys / rectangular):

| Parameter | Microchip AN2934 (Table 1-2) | Azoteq AZD125 (Table 6.1) | ST AN2869 (RC, Fig 13) |
|---|---|---|---|
| Slider/segment height | 8 / 12 / 20 mm | 3.6 / 8 / 16 mm | 1–15 mm |
| Electrode width (length) | 4 / 6 / 8 mm | 3.35 / 4.5 / 7 mm | ≤ 8 mm |
| Electrode pitch | 4 / 6 / 8 mm | 3.6 / 5 / 8 mm | — |
| Inter-electrode gap | 0.25 / 0.5 / 1 mm | 0.25 / 0.5 / 1 mm | ≤ 0.5 mm |
| Element count | — | 3 / 3–4 / 8 | 5 (up to 8) |

*(values shown as min / typ / max where the source gives them)*

Self-cap, **interpolated** (chevron / interdigitated):

| Parameter | Microchip AN2934 (Table 1-3) | Azoteq AZD125 (Table 6.2) | Infineon AN85951 (Table 31) |
|---|---|---|---|
| Slider/segment height | 8 / 12 / 20 mm | 8 / 12 / 20 mm | 7 / 12 / 15 mm |
| Segment width | 8 / 16 / 30 mm (pitch) | (pitch 8 / 16 / 28 mm) | 1.5–8 mm; **rec 8 mm** |
| Inter-electrode gap | 0.5 / 1 / 1.5 mm | 0.5 / 1 / 1.5 mm | 0.5 / — / 2 mm; **rec 0.5 mm** |
| End padding / dummy | — | 1 / 2 / 3.5 mm | +1 dummy segment each end |
| Tooth/tip width | ~2 mm rounded | 0.25 / 0.5 / 1 mm | — |
| Fingers per element | — | 3 / 5 / 7 | — |

**Infineon's governing equation (AN85951 §7.4.4.1, Eq. 73):** `W + 2A = finger diameter`, where W = segment width, A = air gap. With a ~9 mm finger this yields the **W = 8 mm, A = 0.5 mm** recommendation (8 + 2×0.5 = 9). If `W+2A < finger` the finger couples to >2 segments (non-linear); if `>finger` there are dead/flat spots at segment centres.

**Inter-electrode gap consensus:** typical **0.5 mm**, range **0.25–1.5 mm**. A gap **< 0.25 mm** causes excessive load capacitance to the adjacent electrode (Azoteq AZD125 §6.1.2); large parallel-edged electrodes push the gap up toward **1.5 mm** to limit load capacitance (Microchip AN2934 §1.2.3).

**Dummy / end segments (Infineon AN85951 §7.4.4.2).** For uniform sensitivity, lay out an **n-segment slider as n+2 physical segments**, the two end ones grounded or driven-shield. ST equivalently terminates each slider end with a **half-electrode**, both ends tied together (AN2869 §4.3).

**Number of segments / PCB length (Infineon AN85951 §7.4.4.3):**
- `num_segments = sliderLength / (segmentWidth + airGap) + 1`
- `min PCB length = sliderLength + 3·segmentWidth + 2·airGap` (with dummies).

### 2.4 Mutual-cap sliders

Microchip and ST also support mutual sliders (interdigitated X/Y or "flooded-X"):

- Microchip interleaved (AN2934 Table 2-3): height 8/12/20 mm, segment width 8/12/30 mm, X width 0.25/0.5/2 mm, Y width 0.25/0.5/1 mm, X–Y gap 0.25/0.5/1.5 mm; typically a single Y line spans multiple X lines.
- Microchip flooded-X (AN2934 Table 2-4): X overlap 1/2/3 mm, max Y-stripe gap 3/4/5 mm; only valid when the touch cover is no thicker than the X–Y layer separation (so with 1.6 mm FR4, no cover > 1.6 mm).
- Infineon: CapSense Components support **CSD (self-cap) sliders only** in firmware; design sliders as self-cap (AN85951 §2.4.2).

### 2.5 Resistive interpolation (reduce pin count on long sliders)

To cover a long slider with few pins, intermediate electrodes are joined by a resistor ladder and only the ends are routed to GPIO:

- Microchip mutual: **total series R between each pair of directly-connected X lines = 10–20 kΩ** (AN2934 §2.2.3).
- Microchip self-cap (QTAN0079 §5.4.2): per-section `Rtotal ≈ 100 kΩ`; end resistors ≈ **5% of Rtotal** to create a 5% dead-band that stops position wrap-around.
- Microchip mutual (QTAN0079 Fig 6-8): `Rtotal ≈ 2–10 kΩ`.

### 2.6 Trace routing & ground (sliders)

- Route each segment to its own pin; **keep trace length and width equal across all segments**, and keep the gap to ground identical for all segments, so every segment has matched sensitivity (Infineon AN85951 §7.4.4.4).
- Infineon: **max segment-to-segment Cp variation = 44%** of the max segment Cp (at 85% IDAC calibration) before the response goes non-linear.
- Inactive/unused elements are driven to ground (or driven-shield) during the scan (Azoteq AZD125 §3.2.2).
- For mutual sliders, route **ground between Tx and Rx tracks** for shielding (Azoteq AZD125 §6.2).
- A thin grounded guard trace alongside escaping slider traces de-sensitises them to touch (Microchip QTAN0079 §5.2.2).

---

## 3. Wheels / rotary sliders

A wheel is a slider bent into a closed ring: the centroid wraps from the last channel back to channel 0, so there are **no end electrodes** (Microchip AN2934 §1.2.4; Infineon AN85951 §2.4.2).

### 3.1 Channel count

- **Minimum 3 electrodes** — "position calculation requires unique crossover regions" (Microchip AN2934 §1.2.4). TI: a self-cap wheel "only needs three elements."
- ST normal rotary: 3, 5, or 8 electrodes (AN2869 Fig 15). ST projected (mutual) rotary: **≥6 keys** (AN2869 §5.3).
- Infineon hardware reference: the CY3280-SRM radial slider module uses **10 sensors** (AN64846).

### 3.2 Numeric wheel dimensions (by vendor)

| Parameter | ST AN2869 (normal, Fig 15) | ST AN2869 (interlaced, Fig 16) | ST AN2869 (projected, §5.3) | Microchip AN2934 (interpolated, Table 1-5) |
|---|---|---|---|---|
| Diameter / electrode width | w = 8–10 mm | band 2.0–4.0 mm, tooth pitch 2.0–4.0 mm | D = 15–21 mm | width 8/12/20 mm |
| Perimeter arc per key | L = 10–12 mm | — | W = 6–8 mm | — |
| Ring (radial) width | — | — | — | 4–6 mm per ring; HS 4/6/8 mm |
| Inter-electrode gap | e ≤ 0.5 mm | 0.2–0.3 mm | Tx gap ≈ T | 0.5 / 1 / 1.5 mm |
| Centre hole diameter | d ≥ 5 mm | — | (inner taper) | deadzone ≤ 4 mm |
| Electrode-to-ground gap | — | 2 mm | — | — |

ST projected-rotary arc width: `W ≈ (π·D / num_keys) − Rx_width`; if W < 6 mm use fewer keys or a larger D, if W > 8 mm use more keys or a smaller D (AN2869 §5.3). Microchip's 3-channel button wheel is 12–20 mm diameter with a 5 mm centre hole and ~90° wedges (AN2934 Fig 1-13/1-15).

**Important gap:** none of Infineon, TI, or Azoteq publish a wheel-specific inner/outer radius table — they derive wheel geometry from the **same slider pitch/width/gap rules bent into an annulus**. Only ST gives explicit radii (d ≥ 5 mm centre, D = 15–21 mm for projected). The generator should treat wheel radius as derived: `circumference = num_segments × (segment_width + gap)`, with a centre keep-out hole.

---

## 4. XY pads / trackpads (diamond matrices)

### 4.1 Topology

The standard XY pad is a **diamond (rhombus) row/column pattern**. Rows of diamonds form one axis, columns the other; the 45°-rotated diamond chains make each node's coupling area vary smoothly along the orthogonal axis, which is what enables sub-pitch interpolation in both directions (Microchip AN2934 §1.2.5; ST AN2869 §5.1.1).

- **Mutual-cap (CSX)** diamond pads support **multi-touch** (each row×column intersection is a node) and are the standard for trackpads. Infineon uses a **Dual Solid Diamond (DSD)** layout (two rows/columns per sense line) for adequate mutual signal (AN234185 §3.1.1).
- **Self-cap (CSD)** diamond pads are single-touch only (ghosting on a grid). Infineon uses **Single Solid Diamond (SSD)** (AN234185 §3.1.1). Microchip supports self-cap diamond surfaces as row+column electrode chains (AN2934 §1.2.5).
- Microchip's older QTouch Surface guide states a surface "can only be designed using the Mutual Capacitance method" (AT11849); the newer AN2934 supports both.

### 4.2 Diamond geometry (the core numbers)

| Parameter | Microchip AN2934 (Tables 1-6 / 2-8) | Infineon AN234185 (§3.1.2.3) | Azoteq AZD068 (Tables 4.2/4.3) | TI CapTIvate Design Guide | ST AN2869 |
|---|---|---|---|---|---|
| Electrode pitch (row/col centres) | 4 / 6 / 10 mm | 3.8–5 mm; **typ 5 mm** | 1.56 / 3–6 / 8 mm | 3–7 mm (10+ for gestures) | (diamond, qualitative) |
| Gap between diamonds | 0.25 / 0.5 / 1 mm | ITO-on-glass 30–100 µm; ITO-on-PET 100–300 µm; copper = etch min | 0.1 / 0.3 / 0.5 mm | 0.1 / 0.3 / 0.5 mm | — |
| Ideal pitch for 8 mm finger | **~5 mm** | (smaller = more accuracy) | min-touch-sep ≈ 2.5× pitch | — | — |

**Pitch-vs-finger consensus:** ideal pitch ≈ **5 mm for an 8 mm finger**, ensuring any contact overlaps ≥2 electrodes per axis (Microchip AN2934 §1.2.5; Infineon AN234185 typ 5 mm; TI 3–7 mm).

**Diamond gap disagreement:** Infineon AN234185 and TI cite **0.1–0.5 mm** (typ 0.3 mm); Microchip AN2934 cites **0.25–1 mm** (typ 0.5 mm); Microchip's older AT11849 gives a 3.5 mm rhombus diagonal with 1 mm column gap. For copper trackpads, use the **fab's minimum etchable gap**; 0.3 mm is a safe typical.

### 4.3 Number of rows/columns & resolution

- No fixed count — it's a tradeoff: more diamonds → better centroid accuracy and resolution, but more I/O, slower scan, higher current (Infineon AN234185 §3.1.2.2; Microchip AN2934 §1.2.5). `nx = X_dimension / pitch`, `ny = Y_dimension / pitch`.
- Microchip AT11849 limits: **min 3, max 16 rows/columns; ≤100 total nodes**.
- A 5×5 diamond pattern = 25 nodes but only **10 pins** (5 rows + 5 cols) — Infineon AN234185 §3.1.
- Assign axes so **#Rx ≤ #Tx** (put the sense/Rx lines on the shorter axis — lower Cp, less noise) — Infineon AN234185 §4.1.2; AN85951 §7.4.7.
- Resolution: Azoteq native **256 steps between adjacent channel centres**, so max X = 256×(N_cols−1) (AZD068 §4.3); TI ">10-bit"; Microchip AT11849 Z/I patterns 4–7 bits, 5 mm node ≈ 162 DPI, 7 mm node ≈ 232 DPI.
- Two-touch separation must be **≥ 2× sensor pitch** between contact centres (Microchip AN2934 §2.2.5).
- **Terminate every panel edge with a half-diamond** so all diamonds are uniform (Infineon AN234185 §4.3). Avoid orphan "half channels" at edges (Azoteq AZD068 §2.2.1).

### 4.4 Bridges / jumpers at intersections

Rows and columns must cross, so one axis is continuous and the other is bridged:

- **Two routing layers** are the general solution: electrodes/one axis on top, the crossover bridges (and the other axis's interconnects) on a 2nd layer, joined by **vias** (Microchip AN2934 §2.2.5; Azoteq AZD068 §2.1: "the two Tx diamonds are connected on a different layer with a via"; ST AN2869 §5.1.1).
- **Single-layer copper trick (Infineon AN234185 §3.1.2.3, Table 3):** implement the whole diamond pattern on one copper layer using **0 Ω resistor jumpers** to hop one axis over the other. In this case the **PCB thickness becomes part of the overlay** (electrodes face away from the finger).
- Crossings, where unavoidable, must be at **90°** and minimised in area; **Tx/Rx must not overlap > 1 mm**, else insert a shield layer between them (Infineon AN234185 §4.3; Azoteq AZD068 §5.2).
- No vendor gives a numeric **bridge width** in mm; it is sized for resistance/Cp (metal bridges preferred over ITO for lower resistance — Infineon AN234185).

### 4.5 Trackpad trace routing

- Azoteq generally-used: trace **width 0.15 mm**, trace-to-ground spacing **0.3 mm** (AZD068 §5.2).
- Infineon: trace pitch 10–300 µm by process; **trace resistance ≤ 5% of sensor resistance**; route Rx shortest, Tx around the outside; put a **grounded trace between rows and columns** (3W spacing) to cut cross-coupling; "double" routing (both ends of each row/col) for large panels cuts RC delay 4× (AN234185 §4.3, §5).
- Do not place the IC directly behind the pad on a PCB total thickness < 0.6 mm or on FPC (Azoteq AZD068 §5.2).

### 4.6 Trackpad ESD ring

- A grounded **ESD guard ring** around the perimeter, tied to **system/chassis ground (not the controller VSS pin)** — Infineon AN234185 §4.2.1; Azoteq AZD068 §5.4.
- Guard-ring **break gap ≈ 0.1 mm** so it doesn't form a loop antenna (Infineon AN234185).
- The ESD ring must **not be covered with solder mask**, and joins circuit ground at only one point (Azoteq AZD068 §5.4).

---

## 5. Shared layout rules

### 5.1 Ground fill — hatched, not solid

Solid copper near a sensor or trace couples directly into Cx/Cp, raises the RC time constant and acquisition time, and lowers sensitivity (the field is pulled into the ground plane). A **hatched/meshed** ground keeps the shielding benefit while greatly reducing capacitive loading (Microchip AN2934 §1.4.1; Infineon AN85951 §7.4.10; ST AN2869 §4.5.6).

| Vendor | Hatch fill % | Hatch line / spacing | Notes |
|---|---|---|---|
| Microchip AN2934 | rear shield 50% or 25% | not specified | coplanar (same-layer) shield should be **solid** (no overlap penalty) |
| Microchip AT09363 / AT11849 | **< 40%** copper | not specified | meshed ground behind electrodes for noise |
| Microchip QTAN0079 | 50% mesh | not specified | legacy |
| Infineon AN85951 | **top 25%, bottom 17%** | top: 7 mil line / 45 mil pitch; bottom: 7 mil line / 70 mil pitch | no solid copper within **1 cm** of any sensor/trace |
| TI CapTIvate | FR-4 **25%**; FPC **10%** | not specified | ↑% = noise immunity, ↓% = sensitivity |
| ST AN2869 | sensor layer **15%**, opposite side **10%**; sliders/wheels **10% mesh** | not specified | full flood mandatory only under MCU → series resistors |
| Azoteq AZD068 | (ground-diamond pattern) | ground-diamond gap **> 5× the sensor diamond gap** | use a ground *pattern*, not solid pour, on PCBs < 0.8 mm |

**Hatch % consensus:** roughly **10–50%**, clustering around **25%** for the touch/top layer. Only Infineon publishes a concrete line width/pitch (**7 mil line; 45 mil top / 70 mil bottom pitch**); all others give only the fill percentage. **[OUR DEFAULT]** for a generator: 25% top-layer hatch using a ~0.18 mm (7 mil) line — matching Infineon.

**Same-layer vs opposite-layer ground:** coplanar (same-layer) ground around the electrode gives the best isolation and should be solid (it doesn't overlap the sensor); rear/overlapping ground must be hatched to limit loading (Microchip AN2934 §1.4.1; ST AN2869 §4.5.6). Floating planes must **never** sit near sensors (ST AN2869 §4.5.6).

### 5.2 Electrode-to-ground clearance

| Vendor | Electrode-to-ground gap | Notes |
|---|---|---|
| Microchip AN2934 | 1 / 2 / 3 mm (min/typ/max); ~2 mm coplanar | 3–5 mm if moisture immunity matters (AT09363) |
| Infineon AN85951 | = overlay thickness, clamped to **0.5–2 mm** | e.g. 1 mm overlay → 1 mm gap |
| TI CapTIvate | ≥ **½ × overlay thickness** | |
| ST AN2869 | ≥ 2 mm; **4–5 mm recommended**; sliders/wheels 2 mm | |
| Azoteq AZD125 | > 5 mm preferred; mutual Rx-to-GND ≥ 0.5 mm and > Tx-Rx gap | |

**Consensus:** ~**2 mm** typical, tied loosely to overlay thickness; widen to 3–5 mm for moisture/noise immunity.

### 5.3 Air gap between adjacent electrodes / sensors

- Self-cap button-to-button separation: **4 mm + touch-cover thickness** (Microchip AN2934 §1.2.2); Infineon: button edge-to-edge **> 8 mm** (AN85951 §7.4.5).
- Slider/wheel inter-electrode gap: typ **0.5 mm**, range 0.25–1.5 mm (see §2.3).
- Diamond gap: 0.1–1 mm (see §4.2).
- ST: electrode-to-electrode gap **≥ 2× panel thickness** to avoid cross-detection (AN2869 §4.5.6).
- Any touch line to metal (chassis, screws): **> 5 mm** (Infineon AN85951 §7.4.5).

### 5.4 Sensor trace width, length, and routing

| Parameter | Value | Source |
|---|---|---|
| Trace width | **0.1–0.5 mm** (Microchip); **≤ 0.18 mm / 7 mil** (Infineon); **0.2 mm, thinner better** (Azoteq); 0.15 mm trackpad (Azoteq) | Microchip AT09363; Infineon AN85951 §7.4.6; Azoteq AZD125 §3.2.1 |
| Max trace length | **< 200 mm** (Microchip); **< 300 mm** FR4 / 50 mm flex (Infineon); **< 100 mm** (ST); **≤ 210 mm**, or 120 mm for large electrodes (TI) | Microchip AT09363; Infineon AN85951 §7.4.6; ST AN2869 §4.5.4; TI CapTIvate |
| Layer | route on the **non-touch (opposite) layer**, drop to electrode via a via | all vendors |
| Trace-to-ground/hatch clearance | 0.25–0.51 mm (10–20 mil) | Infineon AN85951 §7.4.7 |
| Edge-of-board clearance | ≥ **5 mm** | Microchip AT09363 |
| Crossing other signals | only at **90°**, on a different layer | all vendors |
| Don't route under foreign pads / over power-ground planes | de-sensitises the key | Microchip QTAN0079; ST AN2869 §4.5.7 |

**Consensus:** keep traces **thin (≤0.2 mm)**, **short (<~200 mm)**, on the **opposite layer**, never parallel to noisy lines, crossing only at 90°.

### 5.5 Series resistors

A series resistor near each sensor pin forms a low-pass RC with the sensor Cp (suppresses RF emissions/interference) and adds ESD protection.

| Vendor | Value | Placement |
|---|---|---|
| Infineon AN85951 | self-cap (CSD) **560 Ω**; mutual (CSX) **2 kΩ**; EMC range **560 Ω – 4.7 kΩ**; comms lines 330 Ω | within **10 mm** of the device pin |
| Microchip AT09363 | external **1 kΩ – 100 kΩ** (≥1 kΩ minimum); demo used 220 kΩ (CSD) / 100 kΩ internal + 1 kΩ external (mutual) | at the **MCU pin**, never at the button |
| Microchip QTAN0079 | ≥ **1 kΩ**; **10 kΩ** for difficult ESD/emissions | at the chip |
| Azoteq AZD068 | start at **100 Ω**; **470 Ω** and **1 kΩ** also good | as close to IC as possible |
| ST AN2869 | shield resistor `Rs_shield = Rs_key / k` | close to MCU |
| Microchip AN2934 (interpolation) | 10–20 kΩ total between directly-connected X lines | resistor ladder |

**Consensus:** a series resistor on each sensor line **at the MCU pin** (within ~10 mm). Values span **~100 Ω to a few kΩ** for the RC/ESD function (Infineon's 560 Ω self / 2 kΩ mutual are the most specific), rising to tens of kΩ for ESD-hardened designs. Use **SMD, not through-hole** (through-hole adds parasitic capacitance — Microchip AT09363). Resistor placement at the button instead of the chip is a classic mistake (long track becomes an RF antenna — Microchip QTAN0079 §2.2.4).

### 5.6 Vias

- Vias are the **preferred** way to drop a sense trace to the non-touch layer (makes it touch-insensitive) — all vendors.
- Vias/jumpers are **required** at diamond row/column crossovers and to reconnect isolated X regions in single-layer mutual sliders/wheels (Microchip AN2934 §2.2.5, QTAN0079 §6.3.2; Azoteq AZD068 §2.1).
- **Minimise via count** — each adds Cp. Infineon: **max 2 vias per sensor trace**, **10 mil hole**, placed at the **edge of the pad** (AN85951 §7.4.9).
- Stitching vias along board edges reduce side-coupled noise and tie ground floods across layers (Microchip AT09363).

### 5.7 Overlay / dielectric

The overlay (front panel) must be **non-conductive**. Capacitance, and therefore sensitivity, scales as `C = ε0·εr·A / t` — thinner panels and higher εr give larger signal.

**Relative permittivity (εr) of common overlay materials** (composite of Microchip AN2934, Infineon AN85951 Table 26, ST AN2869 Table 2, Azoteq AZD125/068, TI):

| Material | εr |
|---|---|
| Air | 1.0 |
| Acrylic / PMMA / Plexiglas | 2.6–3.4 (typ ~2.8) |
| Polycarbonate / Lexan | 2.9–3.0 |
| ABS | 2.4–4.1 |
| PET / Mylar | 3.0–3.7 |
| FR4 | 4.2–5.2 |
| Glass (standard) | 7.6–8.0 (range 4–10) |
| PSA adhesive | 2.0–4.5 |

**Maximum overlay thickness** (the binding constraint for sensitivity):

| Widget | Infineon 4th-gen | Infineon 5th-gen | Microchip / ST general |
|---|---|---|---|
| Button | 5 mm (acrylic) | 18 mm | up to 10 mm plastic |
| Slider | 5 mm | 18 mm | up to 10 mm |
| Touchpad / trackpad | **0.5 mm** | 3 mm | thin (≤1 mm with hatched shield) |

(Infineon AN85951 Tables 27/30; Microchip QTAN0079; ST AN2869 §3.2.3.) Trackpads tolerate far thinner overlays than buttons/sliders. Glass (εr≈8) can be ~3× thicker than acrylic (εr≈2.5) for the same sensitivity (Infineon AN85951). Mutual-cap (CSX) needs a **minimum overlay ≥ 0.5 mm** (Infineon).

**Electrode sizing vs overlay:** extend the electrode beyond the finger contact by **≥ one overlay-thickness on every side** (Microchip AN2934 §1.3 — 1 mm cover/8 mm finger → 10 mm electrode; 3 mm → 14 mm; 6 mm → 20 mm). TI rule of thumb: button electrode diameter ≥ **3× overlay thickness**. ST: touchkey width ≥ **4× panel thickness**, ≥6 mm practical floor.

**Adhesive / air-gap avoidance:** always **bond** the overlay to the PCB with non-conductive pressure-sensitive adhesive (3M 467 / 468 / 200MP cited by multiple vendors) to eliminate the air gap. An air gap kills sensitivity — Azoteq notes **1 mm of air ≈ 8 mm of glass** (AZD125 §3.1.5). Air bubbles **> 2 mm diameter** cause unacceptable sensitivity loss; even a **100 µm** change in the interface shifts the signal (Microchip QTAN0079 §2.3.4). Mutual-cap *requires* a void-free bond (the panel is the field conduit X→Y). Where an LCD sits behind, a **0.5–1 mm air gap** reduces back-side ground loading (ST AN2869 §3.2.6).

**Sampling capacitor (Cs), ST only:** Cs (Cs_key / Cs_shield) typical range **2.2–100 nF** (ST AN4310). Higher Cs = higher sensitivity.

### 5.8 ESD

- The dielectric overlay provides the primary ESD protection; the main risk is **creepage** across gaps/holes/panel edges (Microchip QTAN0079 §2.5).
- **Round all corners; truncate triangle/tooth tips to ~2 mm rounded ends** to reduce field concentration (Microchip AN2934).
- Minimum overlay thickness to withstand 12 kV (IEC 61000-4-2), Infineon AN85951 Table 40: Glass 1.5 mm, PMMA/borosilicate 0.9 mm, ABS/PC 0.8 mm, FR-4 0.4 mm, PET/Kapton 0.04 mm. (Azoteq AZD068 gives similar minimums at 13 kV.)
- A grounded **ground ring / ESD ring** around the board perimeter (chassis ground) redirects ESD; on trackpads keep it on a separate ESD ground with a ~0.1 mm break (see §4.6).
- ESD protection diodes must be **low-capacitance (< 1 pF)** so they don't load the sensor (Microchip QTAN0079; e.g. Vishay VBUS05L1 = 0.3 pF, NXP NUP1301 = 0.75 pF). TI cites the TPD1E10B06 TVS diode + a series resistor near the MCU.
- Keep series/ESD resistors close to the MCU so an ESD strike isn't conducted down a long track into the chip (ST AN2869 §4.5.5).

### 5.9 Copper, solder mask, surface finish

- Electrodes are normally **filled copper** on FR4; carbon/silver-ink/ITO/PEDOT are alternatives (lower sheet resistance is better — long thin ITO/silver traces build resistance fast) (Microchip QTAN0079 §2.3.2; ST AN2869 §3.2.2).
- Standard 2-layer stack: sensors + hatched ground on top, components/traces on bottom. FR4 thickness **0.5–1.6 mm** (Infineon AN85951 §7.4.2; Azoteq AZD125 §3.2.1). Avoid hygroscopic/paper-based substrates (εr drifts with humidity) (ST AN2869 §3.2.1; Microchip QTAN0079 §2.3.1).
- **Solder mask over electrodes:** *no vendor mandates a value either way* in the surveyed primary docs. The only explicit statement is the opposite — the **ESD ring must be free of solder mask** (Azoteq AZD068 §5.4). **[GAP — not specified by vendors.]**
- **Surface finish (ENIG / HASL):** *not specified* by any surveyed vendor. **[GAP — not specified by vendors.]**

### 5.10 Parasitic capacitance (Cp) budget

The finger signal (ΔC) is roughly **0.1–5 pF** (typ ~1 pF); it must stay large relative to the baseline parasitic Cp. Cp = pad cap + trace cap + pin cap, and rises with electrode area, trace length/width, and a closer ground plane.

| Vendor | Cp budget | Source |
|---|---|---|
| Microchip | self-cap total ≤ **30 pF**; mutual electrode ≤ **16 pF** (PTC compensates trace parasitics ≤ 100 pF); slider/wheel channel ≤ 30 pF | AT09363 §2.2.2.1 |
| Microchip (device max) | most families cap at **32 pF mutual**, **32–63 pF self** | AN2934 Appendix A |
| Infineon | SmartSense auto-tune supports Cp up to **45 pF** (0.2 pF finger) / 35 pF (0.1 pF finger) | AN64846 |
| TI CapTIvate | total parasitic (trace+electrode) should be **10–20 pF** | CapTIvate Design Guide |

If Cp is too **low** (tiny pad + short trace), add a small cap (e.g. 4.7 pF) to reach the supported minimum; if too **high**, shorten/narrow traces, hatch/cut away the rear ground, avoid through-hole parts, or switch to mutual-cap (whose sensitivity is Cp-independent) (Infineon AN85951 §7.4.1; Microchip AT09363 §4.2.1).

---

## 6. Parameterization implications (for the generator tool)

Translating the rules above into parameters a KiCad footprint generator should expose. Defaults below are vendor-consensus where one exists; **[OUR DEFAULT]** marks values we chose in the absence of a single vendor figure.

### 6.1 Global / shared parameters

| Parameter | Default | Range | Driven by |
|---|---|---|---|
| `sensing_mode` | self-cap | self / mutual | §1 |
| `finger_diameter` | 8 mm | 5–10 mm | §1 |
| `overlay_thickness` | 1.5 mm | 0.5–10 mm (≤0.5 mm trackpad) | §5.7 |
| `overlay_er` | 2.8 (acrylic) | 2.0–8.0 | §5.7 |
| `electrode_to_ground_gap` | 2 mm (or = overlay thickness, clamped 0.5–2 mm) | 0.5–5 mm | §5.2 |
| `inter_electrode_gap` | 0.5 mm | 0.25–1.5 mm | §2.3, §4.2 |
| `hatch_enable` | true | — | §5.1 |
| `hatch_fill_pct` | 25% | 10–50% | §5.1 |
| `hatch_line_width` | 0.18 mm (7 mil) **[OUR DEFAULT, per Infineon]** | — | §5.1 |
| `hatch_pitch` | 1.14 mm top / 1.78 mm bottom (Infineon) **[OUR DEFAULT]** | — | §5.1 |
| `ground_layer` | opposite (hatched) + coplanar (solid) | — | §5.1 |
| `trace_width` | 0.18 mm | 0.1–0.5 mm | §5.4 |
| `max_trace_length` | 200 mm | 50–300 mm | §5.4 |
| `series_resistor` | 560 Ω self / 2 kΩ mutual | 100 Ω–100 kΩ | §5.5 |
| `series_resistor_placement` | at MCU pin (≤10 mm) | — | §5.5 |
| `via_hole` | 0.25 mm (10 mil) | — | §5.6 |
| `max_vias_per_trace` | 2 | 1–2 | §5.6 |
| `corner_rounding` / `tip_truncation` | 2 mm rounded tips, all corners rounded | — | §2.2, §5.8 |
| `esd_ring_enable` | true (trackpads) | — | §4.6, §5.8 |
| `esd_ring_break_gap` | 0.1 mm | — | §4.6 |
| `cp_budget_target` | ≤ 30 pF self / ≤ 16 pF mutual | — | §5.10 |
| `solder_mask_over_electrode` | expose **[OUR DEFAULT — vendors silent]** | — | §5.9 |

### 6.2 Slider parameters

| Parameter | Default | Range | Driven by |
|---|---|---|---|
| `num_segments` | 4 | 3–8 | §2.1 |
| `segment_shape` | chevron/interdigitated | rectangular / chevron / interdigitated | §2.2 |
| `segment_width` (W) | 8 mm | 1.5–30 mm | §2.3 |
| `segment_height` (H) | 12 mm | 7–20 mm | §2.3 |
| `air_gap` (A) | 0.5 mm | 0.25–1.5 mm | §2.3 (constraint: `W + 2A ≈ finger_diameter`) |
| `interdigitation_depth` / `num_fingers` | 5 fingers per element | 3–7 | §2.3 |
| `tip_width` | 0.5 mm | 0.25–1 mm | §2.3 |
| `end_padding` / `dummy_segments` | +1 grounded dummy each end | 0–2 | §2.3 |
| `slider_length` | derived: `num_segments × (W + A)` | — | §2.3 |
| `resistive_interpolation` | off | on/off (R_total 10–20 kΩ mutual / ~100 kΩ self) | §2.5 |

Constraint the generator should enforce: `W + 2·A = finger_diameter` (Infineon Eq. 73) — solve for W given A and finger size, then check W against the etch minimum.

### 6.3 Wheel parameters

| Parameter | Default | Range | Driven by |
|---|---|---|---|
| `num_segments` | 3 | 3–10 | §3.1 |
| `outer_diameter` | derived | 15–40 mm | §3.2 |
| `center_hole_diameter` | 5 mm | ≥5 mm | §3.2 |
| `ring_width` (radial) | 5 mm | 4–9 mm | §3.2 |
| `segment_shape` | interdigitated/chevron arcs | — | §3.2 |
| `air_gap` | 0.5 mm | 0.2–1.5 mm | §3.2 |
| `arc_per_segment` | derived: `360° / num_segments` | — | §3.2 |

Derived geometry: `circumference = π × (outer_diameter − ring_width)`; `segment_arc_width = circumference / num_segments − gap`; keep arc width in **6–8 mm** (ST AN2869 §5.3). Wheels are continuous, so no end dummies.

### 6.4 XY pad / trackpad parameters

| Parameter | Default | Range | Driven by |
|---|---|---|---|
| `sensing_mode` | mutual (CSX) | self (SSD) / mutual (DSD) | §4.1 |
| `diamond_pitch` | 5 mm | 3.8–10 mm | §4.2 |
| `diamond_gap` | 0.3 mm | 0.1–1 mm (copper = etch min) | §4.2 |
| `num_rows` × `num_cols` | derived: `panel / pitch` | ≥2 each (3–16 / ≤100 nodes recommended, not enforced) | §4.3 |
| `axis_assignment` | Rx on shorter axis (#Rx ≤ #Tx) | — | §4.3 |
| `edge_termination` | half-diamond on all edges | — | §4.3 |
| `bridge_method` | vias to 2nd layer (default) / 0 Ω jumpers (single-layer copper) | — | §4.4 |
| `bridge_width` | etch-min **[OUR DEFAULT — vendors give no mm]** | — | §4.4 |
| `inter_row_ground_trace` | enabled, 3W spacing | — | §4.5 |
| `routing_style` | single (small) / double (large, aspect > 1.5) | — | §4.5 |
| `esd_ring` | enabled, 0.1 mm break, no solder mask | — | §4.6 |

Constraints: pitch < finger contact patch so ≥2 diamonds/axis are covered; two-touch needs contact separation ≥ 2× pitch.

---

## 7. Key references

- **Microchip AN2934** — *Capacitive Touch Sensor Design Guide* (DS00002934B, 2020): <https://ww1.microchip.com/downloads/aemDocuments/documents/TXFG/ApplicationNotes/ApplicationNotes/Capacitive-Touch-Sensor-Design-Guide-DS00002934-B.pdf> (earlier rev A: <https://ww1.microchip.com/downloads/en/AppNotes/AN2934-Capacitive-Touch-Sensor-Design-Guidelines-00002934A.pdf>)
- **Microchip / Atmel QTAN0079** — *Buttons, Sliders and Wheels Sensor Design Guide* (doc10752): <https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ApplicationNotes/ApplicationNotes/doc10752.pdf>
- **Microchip / Atmel AT09363** — *PTC Robustness Design Guide* (Atmel-42360): <http://ww1.microchip.com/downloads/en/AppNotes/atmel-42360-ptc-robustness-design-guide_applicationnote_at09363.pdf>
- **Microchip / Atmel AT11849** — *QTouch Surface Design Guide* (Atmel-42442): <https://ww1.microchip.com/downloads/en/Appnotes/Atmel-42442-QTouch-Surface-Design-Guide_ApplicationNote_AT11849.pdf>
- **Microchip DeveloperHelp** — *Surface Sensor Design Guide* / *Guide to Design Touch Sensor*: <https://developerhelp.microchip.com/xwiki/bin/view/applications/touch-gesture/guide-to-design-touch-sensor/>
- **Infineon / Cypress AN85951** — *PSoC 4 and PSoC 6 MCU CapSense Design Guide*: <https://www.infineon.com/dgdl/Infineon-AN85951_PSoC_4_and_PSoC_6_MCU_CapSense_Design_Guide-ApplicationNotes-v28_00-EN.pdf> (mirror: <https://www.mouser.com/pdfDocs/001-85951_AN85951_-_PSoC_R_4_and_PSoC_6_MCU_CapSense_R_Design_Guide.pdf>)
- **Infineon AN234185** — *PSoC 4 CapSense Touchpad Design Guide*: <https://www.infineon.com/assets/row/public/documents/30/42/infineon-an234185-psoc-4-capsense-touchpad-design-guide-applicationnotes-en.pdf>
- **Cypress / Infineon AN64846** — *Getting Started with CapSense*: <https://www.mouser.com/pdfDocs/001-64846_AN64846_Getting_Started_with_CapSense.pdf>
- **Texas Instruments — CapTIvate Technology Guide, Design Guide chapter**: <https://software-dl.ti.com/msp430/msp430_public_sw/mcu/msp430/CapTIvate_Design_Center/latest/exports/docs/users_guide/html/CapTIvate_Technology_Guide_html/markdown/ch_design_guide.html>
- **Texas Instruments SLAA842** — *Capacitive Touch Design Flow for MSP430 MCUs*: <https://www.ti.com/lit/pdf/slaa842>
- **Azoteq AZD125** — *Capacitive Sensing Design Guide (Buttons, Sliders and Wheels)*: <https://www.azoteq.com/images/stories/pdf/azd125_capacitive_sensing_design_guide_v1.0.pdf>
- **Azoteq AZD068** — *General Trackpad Design Guidelines*: <https://www.azoteq.com/images/stories/pdf/azd068-general_trackpad_design_guidelines_v4.0.pdf>
- **STMicroelectronics AN2869** — *Guidelines for designing touch sensing applications*: <https://www.st.com/resource/en/application_note/an2869-guidelines-for-designing-touch-sensing-applications-stmicroelectronics.pdf>
- **STMicroelectronics AN4310** — *How to choose the sampling capacitor for touch sensing applications on STM32 MCUs*: <https://www.st.com/resource/en/application_note/an4310-how-to-choose-the-sampling-capacitor-for-touch-sensing-applications-on-stm32-mcus-stmicroelectronics.pdf>
- **STMicroelectronics AN5105** — *Getting started with touch sensing control on STM32 MCUs*: <https://www.st.com/resource/en/application_note/an5105-getting-started-with-touch-sensing-control-on-stm32-microcontrollers-stmicroelectronics.pdf>
