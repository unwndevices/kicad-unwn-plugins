"""Discrete self-capacitance button / keypad-grid parameters, validation, presets.

A keypad is the simplest touch widget: an ``R×C`` array of **independent self-cap
buttons**, each its own sensed electrode routed to its own pin (no interpolation,
no shared rows/columns — that is the mutual-cap trackpad's job). Position is *which*
button is pressed, not a continuous coordinate, so the only geometry rules are
button *size* and button-to-button *separation* (see
``docs/capacitive-touch-design-guidelines.md`` §§5.3 / 5.7):

* **Separation** — the dominant rule. Self-cap buttons must sit far enough apart
  that a finger on one does not couple into its neighbour: **≥ 4 mm + overlay
  thickness** edge-to-edge (Microchip AN2934 §1.2.2). The default :attr:`gap`
  (4 mm) meets this for a bare board; when a front-panel overlay is specified the
  advisory channel flags a gap that no longer clears ``4 mm + overlay`` (the gap is
  first-class geometry, so — like every other widget — it is *not* silently changed
  by the advisory-only overlay fields; see :mod:`captouch.params.sensing`).
* **Size** — the electrode should be at least the finger contact, extended for the
  overlay: button dimension **≥ 3× overlay thickness** (TI rule of thumb; §5.7),
  with a ~6 mm practical floor (ST). Also surfaced as an advisory.

Three button shapes are offered (all ESD-corner-rounded): ``"rect"`` (square pad),
``"circle"`` (round pad), and ``"diamond"`` (square rotated 45°). All buttons in a
grid share one shape and size.

This module has **no KiCad, geometry, or Qt imports** — it is pure data.
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
    "KeypadParams",
    "KeypadError",
    "validate_keypad",
    "KEYPAD_PRESETS",
    "BUTTON_SHAPES",
    "BUTTON_GAP_MM",
]

#: Allowed values for :attr:`KeypadParams.button_shape`.
BUTTON_SHAPES = ("rect", "circle", "diamond")

#: Default button-to-button separation (mm) — the Microchip AN2934 §1.2.2 self-cap
#: rule "4 mm + touch-cover thickness", evaluated for a bare board (0 cover). The
#: overlay-aware part of the rule is enforced as an advisory, not baked into the
#: default, so the emitted geometry never depends on the advisory-only overlay.
BUTTON_GAP_MM = 4.0


class KeypadError(SliderError):
    """Raised when a :class:`KeypadParams` violates a design constraint.

    Subclasses :class:`SliderError` (as the other widget errors do) so the GUI/CLI
    ``except SliderError`` paths catch it with one handler.
    """


@dataclass(frozen=True)
class KeypadParams:
    """Parameters for a discrete self-cap button / keypad grid.

    All lengths are in millimetres. Defaults follow the guidelines (§§5.3 / 5.7).

    Attributes
    ----------
    num_rows:
        Buttons down the grid (Y), ``>= 1``. ``1`` is a single row of buttons.
    num_cols:
        Buttons across the grid (X), ``>= 1``. ``1`` is a single column; a ``1×1``
        grid is one button.
    button_shape:
        Per-button electrode outline: ``"rect"`` (square pad), ``"circle"`` (round
        pad of diameter :attr:`button_size`), or ``"diamond"`` (a square rotated 45°,
        full diagonal :attr:`button_size`).
    button_size:
        Button dimension (mm): the side for ``rect``, the diameter for ``circle``,
        the full diagonal for ``diamond``. Buttons are uniform across the grid.
    gap:
        Button-to-button **edge-to-edge** separation (mm); the centre pitch is
        ``button_size + gap``. Default :data:`BUTTON_GAP_MM` (the Microchip 4 mm
        self-cap rule for a bare board). The overlay-aware ``4 mm + overlay`` form of
        the rule is checked in the advisory channel.
    corner_radius:
        ESD convex-corner rounding (mm) applied to ``rect`` / ``diamond`` corners;
        ``0`` (default) leaves them sharp. Ignored for ``circle`` (already round).
        Must not exceed ``button_size / 2``.
    name:
        Base name for the emitted footprint / symbol.
    ground_hatch, ground_margin, ground_hatch_width, ground_hatch_pitch,
    guard_ring, guard_width, guard_gap, guard_break, guard_mask_open:
        Optional, **default-off** board-level support copper (a hatched ground pour
        behind the grid and/or a guard / ESD ring around it). See
        :mod:`captouch.params.support`.
    overlay_thickness, overlay_er, board_thickness:
        Front-panel / board-stack context for the **advisory** checks only (never
        drawn). ``overlay_thickness`` 0 (default) means "no overlay specified" and
        switches the overlay-dependent advisories off. See
        :mod:`captouch.params.sensing` and :mod:`captouch.params.advisory`.
    """

    num_rows: int = 3
    num_cols: int = 4
    button_shape: str = "rect"
    button_size: float = 10.0
    gap: float = BUTTON_GAP_MM
    corner_radius: float = 0.0
    name: str = "CT_Keypad"

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
    def pitch(self) -> float:
        """Centre-to-centre spacing of adjacent buttons, ``button_size + gap``."""
        return self.button_size + self.gap

    @property
    def num_buttons(self) -> int:
        """Total buttons in the grid, ``num_rows · num_cols``."""
        return self.num_rows * self.num_cols

    @property
    def num_pins(self) -> int:
        """Total pins / pads, one per button (self-cap: no shared lines)."""
        return self.num_buttons

    @property
    def width(self) -> float:
        """Overall grid width (left edge to right edge), ``num_cols · pitch − gap``."""
        return self.num_cols * self.pitch - self.gap

    @property
    def height(self) -> float:
        """Overall grid height (top to bottom), ``num_rows · pitch − gap``."""
        return self.num_rows * self.pitch - self.gap

    @property
    def button_area(self) -> float:
        """One button's copper area (mm²) — square / disk / rhombus per shape.

        Used by the parasitic-Cp advisory and the fab check. ``circle`` uses the
        analytic disk area (the emitted polygon approximates it).
        """
        if self.button_shape == "circle":
            return math.pi * (self.button_size / 2.0) ** 2
        if self.button_shape == "diamond":  # rhombus, equal diagonals = button_size
            return self.button_size**2 / 2.0
        return self.button_size**2  # rect (square)

    def resolved(self) -> "KeypadParams":
        """Return a copy (parity with the other widgets; nothing to resolve here)."""
        return replace(self)


def validate_keypad(p: KeypadParams) -> KeypadParams:
    """Validate *p*, raising :class:`KeypadError` on any constraint violation.

    Returns *p* unchanged on success so it can be used inline.
    """
    require_finite(p, KeypadError)
    validate_support(p, KeypadError)
    validate_sensing(p, KeypadError)
    if p.button_shape not in BUTTON_SHAPES:
        raise KeypadError(f"button_shape must be one of {BUTTON_SHAPES}, got {p.button_shape!r}")
    for field, val in (("num_rows", p.num_rows), ("num_cols", p.num_cols)):
        if val < 1:
            raise KeypadError(f"{field} must be >= 1, got {val}")
    if p.button_size <= 0:
        raise KeypadError(f"button_size must be > 0, got {p.button_size}")
    if p.gap <= 0:
        raise KeypadError(f"gap must be > 0, got {p.gap}")
    if p.corner_radius < 0:
        raise KeypadError(f"corner_radius must be >= 0, got {p.corner_radius}")
    if p.corner_radius > p.button_size / 2.0:
        raise KeypadError(
            f"corner_radius {p.corner_radius} mm must be <= button_size/2 = "
            f"{p.button_size / 2.0:.3f} mm"
        )
    return p


#: Named starting points drawn from the guidelines doc (§§5.3 / 5.7). Each clears
#: the conservative default fab profile and meets the 4 mm self-cap separation.
KEYPAD_PRESETS: dict[str, KeypadParams] = {
    # Telephone / calculator layout: a 4×3 grid of 10 mm square keys, 4 mm apart
    # (Microchip AN2934 §1.2.2 self-cap separation).
    "numeric": KeypadParams(
        name="CT_Keypad_Numeric",
        num_rows=4,
        num_cols=3,
        button_shape="rect",
        button_size=10.0,
        gap=4.0,
        corner_radius=1.0,
    ),
    # Round macro pad: a 2×3 grid of 12 mm circular keys, 5 mm apart.
    "round": KeypadParams(
        name="CT_Keypad_Round",
        num_rows=2,
        num_cols=3,
        button_shape="circle",
        button_size=12.0,
        gap=5.0,
    ),
    # Compact diamond pad: a 2×2 grid of 8 mm diamond keys, 4 mm apart — the
    # smallest sensible multi-button grid, exercising the diamond shape.
    "compact": KeypadParams(
        name="CT_Keypad_Compact",
        num_rows=2,
        num_cols=2,
        button_shape="diamond",
        button_size=8.0,
        gap=4.0,
        corner_radius=0.5,
    ),
}
