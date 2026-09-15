"""Single self-capacitance button parameters, validation, presets.

A **button** is one discrete touch key: one sensed electrode (plus an optional
grounded hat that meshes with its legs). It is not a keypad — a keypad is an
``R×C`` grid of *solid* pads; this widget is the patterned single key vendors
draw as a snowflake / comb / hatch so the copper area (Cp) stays down while the
perimeter still fills a finger-sized outline.

Outline is ``square`` or ``circle``. Fill styles:

* ``solid`` — flooded pad (the keypad's 1×1 case, as its own widget).
* ``radial`` — hub + radiating legs, optionally a rim; the classic snowflake.
* ``interdigitated`` — parallel comb fingers.
* ``chevron`` — zigzag / tapered comb fingers.
* ``hatch`` — meshed fill plus a rim (lowest Cp; no ground hat).

``ground_hat`` (radial / comb / chevron) pours the complementary copper as a
``GND`` dummy pad so the legs mesh with a driven-ground hat — common for moisture
immunity. Off by default; the optional guard ring on :mod:`captouch.params.support`
is the coplanar alternative.

Size follows the same overlay rule as the keypad (TI: electrode ≥ ``3×`` overlay,
guidelines §5.7). This module has **no KiCad, geometry, or Qt imports**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ._validate import require_finite
from .sensing import BOARD_THICKNESS, OVERLAY_ER, validate_sensing
from .slider import SliderError
from .support import (
    GROUND_HATCH_PITCH,
    GROUND_HATCH_WIDTH,
    GROUND_MARGIN,
    GUARD_BREAK,
    GUARD_GAP,
    GUARD_WIDTH,
    validate_support,
)

__all__ = [
    "ButtonParams",
    "ButtonError",
    "validate_button",
    "BUTTON_PRESETS",
    "BUTTON_OUTLINES",
    "BUTTON_STYLES",
    "BUTTON_HAT_STYLES",
]

#: Allowed values for :attr:`ButtonParams.outline`.
BUTTON_OUTLINES = ("square", "circle")

#: Allowed values for :attr:`ButtonParams.style`.
BUTTON_STYLES = ("solid", "radial", "interdigitated", "chevron", "hatch")

#: Styles that grow legs, and that may take a grounded hat.
BUTTON_HAT_STYLES = ("radial", "interdigitated", "chevron")

#: Default overall size (mm) — a comfortable finger pad (guidelines §5.7; ST's
#: ~6 mm floor, Microchip's 8–12 mm typical self-cap key).
BUTTON_SIZE_MM = 12.0


class ButtonError(SliderError):
    """Raised when a :class:`ButtonParams` violates a design constraint."""


@dataclass(frozen=True)
class ButtonParams:
    """Parameters for a single self-cap button electrode.

    All lengths are in millimetres.

    Attributes
    ----------
    outline:
        Outer shape: ``"square"`` (side :attr:`size`) or ``"circle"`` (diameter
        :attr:`size`).
    size:
        Overall button dimension (mm).
    style:
        Copper fill: ``solid``, ``radial``, ``interdigitated``, ``chevron``,
        ``hatch``.
    num_legs:
        Radial spokes, or comb / chevron fingers. Ignored for ``solid`` / ``hatch``.
    air_gap:
        Clearance (mm) between legs, or between a leg and the ground hat, or the
        hatch line gap. Ignored for ``solid``.
    leg_width:
        Copper width (mm) of each leg / hatch line. ``None`` derives a width that
        fits ``num_legs`` and :attr:`air_gap` inside the outline.
    hub_diameter:
        Centre pad diameter (mm) for ``radial``. ``None`` derives ``0.28 · size``.
        Ignored for other styles.
    rim_width:
        Outer frame width (mm) that keeps patterned copper connected (and, with a
        hat, is the hat's ring). ``None`` derives ``min(0.8, 0.08 · size)`` for
        patterned styles and ``0`` for ``solid``. ``0`` disables the rim.
    ground_hat:
        Pour the complementary copper as a grounded dummy pad (``GND``). Only
        valid for radial / comb / chevron.
    corner_radius:
        ESD rounding (mm) on a square outline; ignored for a circle. ``0`` leaves
        sharp corners. Must not exceed ``size / 2``.
    name:
        Base name for the emitted footprint / symbol.
    """

    outline: str = "circle"
    size: float = BUTTON_SIZE_MM
    style: str = "radial"
    num_legs: int = 8
    air_gap: float = 0.5
    leg_width: float | None = None
    hub_diameter: float | None = None
    rim_width: float | None = None
    ground_hat: bool = False
    corner_radius: float = 0.0
    name: str = "CT_Button"

    # -- optional board-level support copper (default off) ----------------- #
    ground_hatch: bool = False
    ground_margin: float = GROUND_MARGIN
    ground_hatch_width: float = GROUND_HATCH_WIDTH
    ground_hatch_pitch: float = GROUND_HATCH_PITCH
    guard_ring: bool = False
    guard_width: float = GUARD_WIDTH
    guard_gap: float = GUARD_GAP
    guard_break: float = GUARD_BREAK
    guard_mask_open: bool = True

    # -- overlay / board context for advisories (default: no overlay) ------- #
    overlay_thickness: float = 0.0
    overlay_er: float = OVERLAY_ER
    board_thickness: float = BOARD_THICKNESS

    # -- resolved (derived) quantities ------------------------------------- #
    @property
    def effective_rim_width(self) -> float:
        """Rim width actually used, with the style-dependent default applied."""
        if self.rim_width is not None:
            return self.rim_width
        if self.style == "solid":
            return 0.0
        return min(0.8, 0.08 * self.size)

    @property
    def effective_hub_diameter(self) -> float:
        """Hub diameter actually used (radial only)."""
        if self.hub_diameter is not None:
            return self.hub_diameter
        if self.style != "radial":
            return 0.0
        return 0.28 * self.size

    @property
    def effective_leg_width(self) -> float:
        """Leg / hatch-line width actually used, with the auto default applied."""
        if self.leg_width is not None:
            return self.leg_width
        return _auto_leg_width(self)

    @property
    def num_pins(self) -> int:
        """``1`` (sense) or ``2`` (sense + grounded hat)."""
        return 2 if self.ground_hat else 1

    @property
    def outline_area(self) -> float:
        """Filled outline area (mm²) — conservative Cp stand-in for patterned fills."""
        if self.outline == "circle":
            return math.pi * (self.size / 2.0) ** 2
        return self.size**2

    def resolved(self) -> "ButtonParams":
        """Return a copy with auto ``None`` fields filled in (preview/export)."""
        return replace(
            self,
            leg_width=self.effective_leg_width,
            hub_diameter=self.effective_hub_diameter,
            rim_width=self.effective_rim_width,
        )


def _auto_leg_width(p: ButtonParams) -> float:
    """A copper width that fits ``num_legs`` plus :attr:`air_gap` inside the outline."""
    if p.style == "solid":
        return 0.0
    if p.style == "hatch":
        # Infineon-ish 7 mil hatch line; still above the default fab floor.
        return 0.18
    rim = p.effective_rim_width
    inner = max(p.size - 2.0 * rim, p.size * 0.4)
    n = max(p.num_legs, 1)
    if p.style == "radial":
        r_hub = p.effective_hub_diameter / 2.0
        r_mid = 0.5 * (r_hub + inner / 2.0)
        sector = 2.0 * r_mid * math.sin(math.pi / n)
        if p.ground_hat:
            return max((sector - 2.0 * p.air_gap) / 2.0, 0.15)
        return max(sector - p.air_gap, 0.15)
    # Parallel comb / chevron: divide the inner span into n copper + n gap strips.
    # With a hat the gaps become hat fingers, so copper and gap share the pitch.
    pitch = inner / n
    if p.ground_hat:
        return max((pitch - 2.0 * p.air_gap) / 2.0, 0.15)
    return max(pitch - p.air_gap, 0.15)


def validate_button(p: ButtonParams) -> ButtonParams:
    """Validate *p*, raising :class:`ButtonError` on any constraint violation."""
    require_finite(p, ButtonError)
    validate_support(p, ButtonError)
    validate_sensing(p, ButtonError)
    if p.outline not in BUTTON_OUTLINES:
        raise ButtonError(f"outline must be one of {BUTTON_OUTLINES}, got {p.outline!r}")
    if p.style not in BUTTON_STYLES:
        raise ButtonError(f"style must be one of {BUTTON_STYLES}, got {p.style!r}")
    if p.size <= 0:
        raise ButtonError(f"size must be > 0, got {p.size}")
    if p.corner_radius < 0:
        raise ButtonError(f"corner_radius must be >= 0, got {p.corner_radius}")
    if p.corner_radius > p.size / 2.0:
        raise ButtonError(
            f"corner_radius {p.corner_radius} mm must be <= size/2 = {p.size / 2.0:.3f} mm"
        )
    if p.ground_hat and p.style not in BUTTON_HAT_STYLES:
        raise ButtonError(
            f"ground_hat is only valid for {BUTTON_HAT_STYLES}, not style={p.style!r}"
        )
    if p.style == "solid":
        return p
    if p.air_gap <= 0:
        raise ButtonError(f"air_gap must be > 0, got {p.air_gap}")
    if p.style != "hatch" and p.num_legs < 3:
        raise ButtonError(f"num_legs must be >= 3, got {p.num_legs}")
    rim = p.effective_rim_width
    if rim < 0:
        raise ButtonError(f"rim_width must be >= 0, got {rim}")
    if rim >= p.size / 2.0:
        raise ButtonError(f"rim_width {rim:.3f} mm must be < size/2 = {p.size / 2.0:.3f} mm")
    if p.style == "radial":
        hub = p.effective_hub_diameter
        if hub <= 0:
            raise ButtonError(f"hub_diameter must be > 0, got {hub}")
        if hub >= p.size - 2.0 * rim:
            raise ButtonError(
                f"hub_diameter {hub:.3f} mm must sit inside the outline "
                f"(size {p.size:.3f} minus 2·rim {2.0 * rim:.3f})"
            )
    width = p.effective_leg_width
    if width <= 0:
        raise ButtonError(
            f"leg_width must be > 0, got {width:.3f} mm — "
            f"reduce num_legs or air_gap, or enlarge the button"
        )
    return p


#: Named starting points. Each clears the conservative default fab profile.
BUTTON_PRESETS: dict[str, ButtonParams] = {
    # Finger-sized round snowflake — the default look.
    "snowflake": ButtonParams(
        name="CT_Button_Snowflake",
        outline="circle",
        size=12.0,
        style="radial",
        num_legs=8,
        air_gap=0.5,
    ),
    # Flooded round key, same size as a keypad circle.
    "solid": ButtonParams(
        name="CT_Button_Solid",
        outline="circle",
        size=12.0,
        style="solid",
    ),
    # Square snowflake, slightly rounded corners for ESD.
    "square": ButtonParams(
        name="CT_Button_Square",
        outline="square",
        size=12.0,
        style="radial",
        num_legs=8,
        air_gap=0.5,
        corner_radius=1.0,
    ),
    # Parallel comb meshed with a grounded hat.
    "comb": ButtonParams(
        name="CT_Button_Comb",
        outline="square",
        size=12.0,
        style="interdigitated",
        num_legs=6,
        air_gap=0.4,
        ground_hat=True,
        corner_radius=0.5,
    ),
    # Low-Cp hatched circle (no hat — the mesh leftover is too fragmented).
    "hatch": ButtonParams(
        name="CT_Button_Hatch",
        outline="circle",
        size=12.0,
        style="hatch",
        air_gap=0.7,
        leg_width=0.18,
    ),
}
