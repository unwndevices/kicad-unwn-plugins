"""Sensitivity & filtering advisories — design guidance, never hard errors.

Where :mod:`captouch.params.fab` checks the resolved geometry against what a board
house can *etch*, this module checks it against the *electrical* sensitivity
guidance the vendor app-notes give — the numbers in
``docs/capacitive-touch-design-guidelines.md`` §§5.5/5.7/5.10:

* **Electrode-vs-overlay sizing** (§5.7, Microchip AN2934 §1.3) — a self-cap
  electrode's touch-transverse dimension should be at least ``finger + 2·overlay``
  so the finger does not overhang the copper (which hurts interpolation linearity).
  For the mutual-cap trackpad, which has no finger parameter, the binding overlay
  rule instead is the **max overlay thickness** window (§5.7: ~0.5–3 mm).
* **Parasitic-capacitance (Cp) budget** (§5.10) — a per-channel parallel-plate
  *estimate* of the electrode-to-ground capacitance vs the ~30 pF self / ~16 pF
  mutual budgets (Microchip AT09363). This is an order-of-magnitude estimate to a
  ground plane one ``board_thickness`` below the copper, not a measurement.
* **Series resistor** (§5.5) — the recommended RC/ESD series-R value (560 Ω self /
  2 kΩ mutual, Infineon AN85951), reported so the user places it within ~10 mm of
  the *MCU* pin. No resistor copper is added to the electrode footprint — a series R
  belongs at the controller, not the sensor.

Like the fab guards, these are **advisory by default** (Phase 5/9 decision):
generation still succeeds and the items surface as warnings in the CLI and GUI;
``--strict`` promotes the actionable ones (sizing, Cp) to a hard failure. The
purely informational items (the series-R recommendation, the sensitivity note)
never block. None of this changes the emitted geometry.

This module imports the concrete widget params for its per-widget dispatch and is
**not** imported by them, mirroring the :mod:`~captouch.params.fab` /
:mod:`~captouch.params.support` split. Pure data: no KiCad/geometry/Qt imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .keypad import BUTTON_GAP_MM, KeypadParams
from .mutual_slider import MutualSliderParams
from .sensing import has_overlay
from .slider import SliderParams
from .trackpad import TrackpadParams
from .wheel import WheelParams

__all__ = [
    "Advisory",
    "check_advisories",
    "recommended_series_r",
    "estimate_cp_pf",
    "FR4_ER",
    "CP_BUDGET_SELF_PF",
    "CP_BUDGET_MUTUAL_PF",
    "SERIES_R_SELF",
    "SERIES_R_MUTUAL",
    "TRACKPAD_OVERLAY_MIN_MM",
    "TRACKPAD_OVERLAY_MAX_MM",
    "BUTTON_OVERLAY_SIZE_FACTOR",
    "SPIRAL_MIN_OUTER_CORNER_DEG",
]

# -- physical / guideline constants ------------------------------------------ #
#: ε0 expressed in pF·mm⁻¹ so ``ε0·εr·A[mm²]/d[mm]`` lands directly in pF.
_EPS0_PF_PER_MM = 8.854e-3
#: FR-4 substrate relative permittivity for the Cp estimate (guidelines §5.7
#: table: FR-4 εr 4.2–5.2; 4.5 is a representative mid-value).
FR4_ER = 4.5
#: Per-channel parasitic-Cp budgets (pF) — Microchip AT09363 §2.2.2.1 (§5.10):
#: self-cap channel ≤ 30 pF, mutual electrode ≤ 16 pF.
CP_BUDGET_SELF_PF = 30.0
CP_BUDGET_MUTUAL_PF = 16.0
#: Recommended series-resistor values (Infineon AN85951; guidelines §5.5).
SERIES_R_SELF = "560 Ω"
SERIES_R_MUTUAL = "2 kΩ"
#: Overlay-thickness window (mm) for a mutual-cap trackpad (guidelines §5.7:
#: mutual needs ≥ 0.5 mm; touchpad max ~3 mm at 5th-gen sensitivity).
TRACKPAD_OVERLAY_MIN_MM = 0.5
TRACKPAD_OVERLAY_MAX_MM = 3.0
#: A self-cap button electrode dimension should be at least this multiple of the
#: overlay thickness (TI rule of thumb; guidelines §5.7).
BUTTON_OVERLAY_SIZE_FACTOR = 3.0
#: Smallest sensible outer-edge wedge corner (degrees) for a spiral wheel. A
#: steeper twist tapers the electrode to an acute copper sliver at the outer arc
#: that risks failing KiCad DRC; below this the advisory fires. Calibrated against
#: the empirical DRC boundary (an 8-segment / 6 mm-ring / finger-8 / gap-0.5 wheel
#: is clean at ≤80° → ~22° corner, but slivers at ≥90° → ~20° corner).
SPIRAL_MIN_OUTER_CORNER_DEG = 20.0


@dataclass(frozen=True)
class Advisory:
    """One sensitivity/filtering advisory.

    *blocks* marks the actionable items (sizing, Cp over budget) that a
    ``--strict`` run promotes to a hard failure; informational items (the series-R
    recommendation, the sensitivity note) have ``blocks=False`` and never fail.
    """

    feature: str  # short label, e.g. "electrode vs overlay sizing"
    message: str  # full guidance sentence, with numbers + the cited source
    blocks: bool = False


WidgetParams = SliderParams | WheelParams | TrackpadParams | MutualSliderParams | KeypadParams


# --------------------------------------------------------------------------- #
# building blocks
# --------------------------------------------------------------------------- #
def recommended_series_r(params: WidgetParams) -> tuple[str, str]:
    """Return ``(value, sensing-mode label)`` for the recommended series resistor.

    Self-cap (slider/wheel) → 560 Ω; mutual-cap (trackpad, mutual slider) → 2 kΩ
    (Infineon AN85951; guidelines §5.5).
    """
    if isinstance(params, (TrackpadParams, MutualSliderParams)):
        return SERIES_R_MUTUAL, "mutual-cap (CSX)"
    return SERIES_R_SELF, "self-cap (CSD)"


def estimate_cp_pf(area_mm2: float, board_thickness_mm: float, er: float = FR4_ER) -> float:
    """Parallel-plate estimate (pF) of a channel's electrode-to-ground capacitance.

    ``C = ε0·εr·A/d`` for copper area *area_mm2* a substrate thickness
    *board_thickness_mm* above a reference ground plane. An order-of-magnitude
    advisory figure (it ignores fringing, trace/pin Cp, and assumes a full ground
    plane one board-thickness below), not a measurement — see the module docstring.
    """
    return _EPS0_PF_PER_MM * er * area_mm2 / board_thickness_mm


def _series_r_advisory(params: WidgetParams) -> Advisory:
    value, mode = recommended_series_r(params)
    return Advisory(
        feature="series resistor",
        message=(
            f"recommend a {value} series resistor on each sense line, placed within "
            f"~10 mm of the MCU pin (not the electrode) — {mode}, for RC filtering + ESD "
            f"(Infineon AN85951; guidelines §5.5)"
        ),
        blocks=False,
    )


def _sensitivity_note(params: WidgetParams) -> Advisory:
    ratio = params.overlay_er / params.overlay_thickness
    return Advisory(
        feature="overlay sensitivity",
        message=(
            f"overlay: {params.overlay_thickness:.2f} mm, εr {params.overlay_er:.1f} "
            f"(εr/thickness ≈ {ratio:.1f} mm⁻¹; signal ∝ εr/thickness). Thinner or "
            f"higher-εr panels sense more; bond the panel void-free to avoid an air "
            f"gap (guidelines §5.7)"
        ),
        blocks=False,
    )


def _cp_advisory(
    params: WidgetParams, area_mm2: float, budget_pf: float, mode: str
) -> Advisory | None:
    cp = estimate_cp_pf(area_mm2, params.board_thickness)
    if cp <= budget_pf:
        return None
    return Advisory(
        feature="parasitic Cp",
        message=(
            f"estimated per-channel Cp ≈ {cp:.1f} pF exceeds the {mode} budget "
            f"{budget_pf:.0f} pF (parallel-plate estimate over {params.board_thickness:.2f} mm "
            f"FR-4; Microchip AT09363, guidelines §5.10) — shrink the electrode, thin the "
            f"ground, or shorten traces; mutual-cap sensitivity is Cp-independent"
        ),
        blocks=True,
    )


def _overlay_sizing_advisory(
    params: SliderParams | WheelParams, transverse_mm: float, label: str
) -> Advisory | None:
    """Self-cap electrode transverse dimension vs ``finger + 2·overlay`` (§5.7)."""
    need = params.finger_diameter + 2.0 * params.overlay_thickness
    if transverse_mm >= need:
        return None
    return Advisory(
        feature="electrode vs overlay sizing",
        message=(
            f"{label} {transverse_mm:.2f} mm is below the finger + 2·overlay minimum "
            f"{need:.2f} mm (finger {params.finger_diameter:.1f} mm + 2 × "
            f"{params.overlay_thickness:.2f} mm overlay; Microchip AN2934 §1.3) — the "
            f"finger overhangs the electrode, hurting linearity. Widen it or thin the overlay"
        ),
        blocks=True,
    )


def _wheel_spiral_advisory(params: WheelParams) -> Advisory | None:
    """Steep-spiral copper-sliver guard for a wheel boundary (geometry-aware).

    A spiral boundary twists by ``spiral_angle`` from the inner radius to the
    outer radius, so its tangent leans away from the radial direction by a growing
    angle as the radius grows. At the outer arc — the worst case — the wedge corner
    where the twisting boundary meets the outer edge is the *complement* of that
    lean, so a steeper twist (or a narrower ring, which raises the twist gradient)
    pinches the electrode into an acute copper sliver that can fail KiCad DRC.

    Returns ``None`` unless this is an actually-twisting spiral whose estimated
    outer-edge corner is below :data:`SPIRAL_MIN_OUTER_CORNER_DEG`; otherwise a
    blocking advisory naming the angle, threshold, and the concrete fixes.
    """
    if params.segment_shape != "spiral" or params.spiral_angle == 0:
        return None
    # ``span`` matches the geometry's r_hi - r_lo (the boundaries are extended one
    # air_gap past each ring edge so the gap strips cut cleanly); the twist climbs
    # linearly across it, giving a constant gradient g (rad/mm).
    span = params.ring_width + 2.0 * params.air_gap
    g = math.radians(abs(params.spiral_angle)) / span
    # The boundary tangent makes angle φ = atan(outer_radius·g) with the radial
    # direction; the sharp wedge corner at the outer arc is the complement of φ.
    acute_deg = math.degrees(math.atan2(1.0, params.outer_radius * g))
    if acute_deg >= SPIRAL_MIN_OUTER_CORNER_DEG:
        return None
    return Advisory(
        feature="spiral copper slivers",
        message=(
            f"spiral_angle {params.spiral_angle:.0f}° tapers the electrode to an "
            f"~{acute_deg:.0f}° corner at the outer edge, below the "
            f"{SPIRAL_MIN_OUTER_CORNER_DEG:.0f}° minimum — such an acute copper sliver "
            f"may fail PCB DRC (fab-dependent). Reduce spiral_angle, widen ring_width, "
            f"or add segments to open the corner"
        ),
        blocks=True,
    )


def _keypad_size_advisory(params: KeypadParams) -> Advisory | None:
    """Self-cap button dimension vs ``3 × overlay`` (TI rule; §5.7)."""
    need = BUTTON_OVERLAY_SIZE_FACTOR * params.overlay_thickness
    if params.button_size >= need:
        return None
    return Advisory(
        feature="button vs overlay sizing",
        message=(
            f"button size {params.button_size:.2f} mm is below the "
            f"{BUTTON_OVERLAY_SIZE_FACTOR:.0f} × overlay minimum {need:.2f} mm "
            f"(overlay {params.overlay_thickness:.2f} mm; TI rule of thumb, guidelines §5.7) — "
            f"enlarge the button or thin the overlay so a finger fully couples to it"
        ),
        blocks=True,
    )


def _keypad_separation_advisory(params: KeypadParams) -> Advisory | None:
    """Self-cap button separation vs ``4 mm + overlay`` (Microchip §1.2.2 / §5.3)."""
    need = BUTTON_GAP_MM + params.overlay_thickness
    if params.gap >= need:
        return None
    return Advisory(
        feature="button separation",
        message=(
            f"button gap {params.gap:.2f} mm is below the {BUTTON_GAP_MM:.0f} mm + overlay "
            f"minimum {need:.2f} mm (overlay {params.overlay_thickness:.2f} mm; Microchip "
            f"AN2934 §1.2.2, guidelines §5.3) — widen the gap so a finger on one button "
            f"does not couple into its neighbour"
        ),
        blocks=True,
    )


def _trackpad_overlay_advisory(params: TrackpadParams) -> Advisory | None:
    """Mutual-cap trackpad overlay thickness vs the ~0.5–3 mm window (§5.7)."""
    t = params.overlay_thickness
    if TRACKPAD_OVERLAY_MIN_MM <= t <= TRACKPAD_OVERLAY_MAX_MM:
        return None
    if t < TRACKPAD_OVERLAY_MIN_MM:
        detail = f"below the {TRACKPAD_OVERLAY_MIN_MM:.1f} mm mutual-cap minimum"
    else:
        detail = f"above the ~{TRACKPAD_OVERLAY_MAX_MM:.0f} mm trackpad maximum"
    return Advisory(
        feature="overlay thickness",
        message=(
            f"overlay {t:.2f} mm is {detail} for a mutual-cap trackpad "
            f"({TRACKPAD_OVERLAY_MIN_MM:.1f}–{TRACKPAD_OVERLAY_MAX_MM:.0f} mm; Infineon "
            f"AN85951 Tables 27/30, guidelines §5.7) — trackpads need a thin, void-free panel"
        ),
        blocks=True,
    )


# --------------------------------------------------------------------------- #
# per-widget dispatch
# --------------------------------------------------------------------------- #
def _self_cap_advisories(
    params: SliderParams | WheelParams, transverse_mm: float, label: str, channel_area_mm2: float
) -> list[Advisory]:
    out: list[Advisory | None] = [_series_r_advisory(params)]
    if has_overlay(params):
        out.append(_overlay_sizing_advisory(params, transverse_mm, label))
        out.append(_sensitivity_note(params))
    out.append(_cp_advisory(params, channel_area_mm2, CP_BUDGET_SELF_PF, "self-cap"))
    return [a for a in out if a is not None]


def _keypad_advisories(params: KeypadParams) -> list[Advisory]:
    out: list[Advisory | None] = [_series_r_advisory(params)]
    if has_overlay(params):
        out.append(_keypad_size_advisory(params))
        out.append(_keypad_separation_advisory(params))
        out.append(_sensitivity_note(params))
    out.append(_cp_advisory(params, params.button_area, CP_BUDGET_SELF_PF, "self-cap"))
    return [a for a in out if a is not None]


def _trackpad_advisories(params: TrackpadParams) -> list[Advisory]:
    # Worst-case channel: the longer electrode line (max of an Rx row's num_cols
    # diamonds and a Tx column's num_rows diamonds); diamond area = 2·d².
    line_diamonds = max(params.num_rows, params.num_cols)
    channel_area = line_diamonds * 2.0 * params.half_diag**2
    out: list[Advisory | None] = [_series_r_advisory(params)]
    if has_overlay(params):
        out.append(_trackpad_overlay_advisory(params))
        out.append(_sensitivity_note(params))
    out.append(_cp_advisory(params, channel_area, CP_BUDGET_MUTUAL_PF, "mutual"))
    return [a for a in out if a is not None]


def check_advisories(params: WidgetParams) -> list[Advisory]:
    """Return the sensitivity/filtering advisories for *params*.

    The recommended series resistor is always present; the overlay-dependent items
    (sizing / thickness window, sensitivity note) appear only when an overlay is
    specified; the Cp item appears only when the estimate exceeds the budget. The
    list never includes a manufacturability error — those are :mod:`fab`'s job.
    """
    if isinstance(params, TrackpadParams):
        return _trackpad_advisories(params)
    if isinstance(params, MutualSliderParams):
        # A mutual-cap slider is electrically a 1-row trackpad; reuse the mutual
        # advisory treatment (2 kΩ series-R, mutual Cp budget, mutual overlay window).
        return _trackpad_advisories(params.to_trackpad())
    if isinstance(params, KeypadParams):
        return _keypad_advisories(params)
    if isinstance(params, WheelParams):
        # Shared self-cap items, plus the wheel-only spiral sliver guard (kept out
        # of _self_cap_advisories, which the slider also calls — the slider has no
        # spiral shape and must be unaffected).
        out = _self_cap_advisories(
            params, params.ring_width, "ring width", params.width * params.ring_width
        )
        spiral = _wheel_spiral_advisory(params)
        if spiral is not None:
            out.append(spiral)
        return out
    if isinstance(params, SliderParams):
        return _self_cap_advisories(
            params, params.segment_height, "segment height", params.width * params.segment_height
        )
    raise TypeError(f"unsupported params type for advisories: {type(params).__name__}")
