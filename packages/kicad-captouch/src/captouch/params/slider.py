"""Linear self-capacitance slider parameters, validation, and presets.

A slider is a 1-D array of ``num_segments`` individually-sensed electrodes; the
controller interpolates a finger's position from the signal on the touched
segment and its neighbours (centroid). For that interpolation to stay linear the
finger must always overlap >=2 electrodes, which drives the core geometry rules
encoded here (see ``docs/capacitive-touch-design-guidelines.md`` section 2).

Key design constraint — **Infineon AN85951 Eq. 73**: ``W + 2A = finger_diameter``
where ``W`` = segment width and ``A`` = inter-electrode air gap. If ``W + 2A`` is
smaller than the finger the contact couples to >2 segments (non-linear); larger
and there are dead/flat spots at segment centres. We solve for ``W`` from the
finger size by default so the relationship holds, and validate it when ``W`` is
given explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ._validate import require_finite
from .sensing import BOARD_THICKNESS, OVERLAY_ER, validate_sensing
from .support import (
    GROUND_HATCH_PITCH,
    GROUND_HATCH_WIDTH,
    GROUND_MARGIN,
    GUARD_BREAK,
    GUARD_GAP,
    GUARD_WIDTH,
    validate_support,
)

__all__ = ["SliderParams", "SliderError", "validate_slider", "SLIDER_PRESETS"]

#: Allowed values for :attr:`SliderParams.segment_shape`.
SEGMENT_SHAPES = ("rectangular", "chevron", "interdigitated")

#: Tolerance (mm) on the ``W + 2A == finger_diameter`` constraint before
#: :func:`validate_slider` rejects the parameters (Infineon AN85951 Eq. 73).
FINGER_CONSTRAINT_TOL = 0.5


class SliderError(ValueError):
    """Raised when a :class:`SliderParams` violates a design constraint."""


@dataclass(frozen=True)
class SliderParams:
    """Parameters for a linear self-capacitance slider.

    All lengths are in millimetres. Dimensions default to the vendor-consensus
    values from the design-guidelines document (section 2.3 / 6.2).

    Attributes
    ----------
    num_segments:
        Number of *active* (sensed, pin-routed) electrodes. >=3 is required for
        usable interpolation (vendor consensus, guidelines section 2.1).
    segment_shape:
        Electrode edge style: ``"rectangular"`` (plain bars; staircase output),
        ``"chevron"`` (triangle-wave shared edge), or ``"interdigitated"``
        (square-wave comb teeth). The latter two stretch the crossover so two
        electrodes are always partially covered (guidelines section 2.2).
    segment_width:
        Segment width ``W``. ``None`` (default) derives it from the finger as
        ``finger_diameter - 2 * air_gap`` so Eq. 73 holds exactly.
    segment_height:
        Electrode height ``H`` (the slider's transverse dimension).
    air_gap:
        Inter-electrode gap ``A`` (uniform copper-to-copper clearance).
    finger_diameter:
        Finger contact-disc diameter used by the Eq. 73 constraint.
    num_fingers:
        Teeth per shared boundary for chevron / interdigitated shapes.
    tooth_depth:
        Half-amplitude (mm) of the boundary waveform — how far teeth reach from
        the nominal segment edge. ``None`` derives ``0.3 * W``. Must stay below
        ``W / 2`` so adjacent boundaries do not collide.
    end_dummies:
        Grounded dummy segments per end (Infineon: lay out an n-segment slider
        as n+2 physical segments for uniform end sensitivity). ``0``..``2``.
    corner_radius:
        Extra convex-corner rounding (mm) applied to *all* shapes for ESD
        relief; ``0`` (default) leaves the perimeter as built.
    tip_radius:
        Rounding (mm) applied specifically to **chevron** tooth-tips, which are
        acute and otherwise taper to fab-resolution copper points (sharp copper
        etches poorly and concentrates ESD). The effective chevron rounding is
        ``max(corner_radius, tip_radius)``; ``0`` leaves sharp tips. Ignored for
        rectangular / interdigitated boundaries (no acute tips).
    relax_finger_constraint:
        Skip the Eq. 73 check (for deliberately non-standard geometry).
    name:
        Base name for the emitted footprint / symbol.
    ground_hatch, ground_margin, ground_hatch_width, ground_hatch_pitch,
    guard_ring, guard_width, guard_gap, guard_break, guard_mask_open:
        Optional, **default-off** board-level support copper (a hatched ground
        pour on B.Cu and/or a grounded guard / ESD ring on F.Cu). See
        :mod:`captouch.params.support`.
    overlay_thickness, overlay_er, board_thickness:
        Front-panel / board-stack context for the **advisory** checks only (never
        drawn). ``overlay_thickness`` 0 (default) means "no overlay specified" and
        switches the overlay-dependent advisories off. See
        :mod:`captouch.params.sensing` and :mod:`captouch.params.advisory`.
    """

    num_segments: int = 4
    segment_shape: str = "chevron"
    segment_width: float | None = None
    segment_height: float = 12.0
    air_gap: float = 0.5
    finger_diameter: float = 8.0
    num_fingers: int = 5
    tooth_depth: float | None = None
    end_dummies: int = 1
    corner_radius: float = 0.0
    tip_radius: float = 0.15
    relax_finger_constraint: bool = False
    name: str = "CT_Slider"

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
    def width(self) -> float:
        """Resolved segment width ``W`` (derived from the finger if unset)."""
        if self.segment_width is not None:
            return self.segment_width
        return self.finger_diameter - 2.0 * self.air_gap

    @property
    def amplitude(self) -> float:
        """Resolved boundary half-amplitude (``tooth_depth`` or ``0.3 * W``)."""
        if self.segment_shape == "rectangular":
            return 0.0
        if self.tooth_depth is not None:
            return self.tooth_depth
        return 0.3 * self.width

    @property
    def pitch(self) -> float:
        """Centre-to-centre spacing of adjacent segments, ``W + A``."""
        return self.width + self.air_gap

    @property
    def num_physical_segments(self) -> int:
        """Total copper segments emitted, active plus end dummies."""
        return self.num_segments + 2 * self.end_dummies

    @property
    def total_length(self) -> float:
        """Overall slider length (left edge to right edge), all segments."""
        m = self.num_physical_segments
        return m * self.width + (m - 1) * self.air_gap

    def resolved(self) -> "SliderParams":
        """Return a copy with ``segment_width`` / ``tooth_depth`` made explicit."""
        return replace(self, segment_width=self.width, tooth_depth=self.amplitude)

    def fit_to_length(self, length: float) -> "SliderParams":
        """Return a copy whose ``num_segments`` best matches a target overall *length*.

        Sizes the slider from its known overall length instead of a segment count:
        solves ``length = m·pitch − A`` for the physical-segment count ``m`` (rounded
        to the nearest whole segment, since the pitch ``W + A`` is fixed by the
        finger/gap and is not stretched), then backs out the active count
        ``num_segments = m − 2·end_dummies`` (floored at the 3-segment minimum). The
        achieved :attr:`total_length` therefore lands within half a pitch of the
        target.
        """
        if self.pitch <= 0:
            raise SliderError(
                f"cannot size from length: segment pitch (W + A) is {self.pitch:.3f} mm "
                f"(<= 0); check finger_diameter / air_gap / segment_width"
            )
        physical = round((length + self.air_gap) / self.pitch)
        return replace(self, num_segments=max(3, physical - 2 * self.end_dummies))


def validate_slider(p: SliderParams) -> SliderParams:
    """Validate *p*, raising :class:`SliderError` on any constraint violation.

    Returns *p* unchanged on success so it can be used inline.
    """
    require_finite(p, SliderError)
    validate_support(p, SliderError)
    validate_sensing(p, SliderError)
    if p.segment_shape not in SEGMENT_SHAPES:
        raise SliderError(f"segment_shape must be one of {SEGMENT_SHAPES}, got {p.segment_shape!r}")
    if p.num_segments < 3:
        raise SliderError(
            f"num_segments must be >=3 for usable interpolation, got {p.num_segments}"
        )
    if not 0 <= p.end_dummies <= 2:
        raise SliderError(f"end_dummies must be 0..2, got {p.end_dummies}")

    if p.width <= 0:
        raise SliderError(
            f"resolved segment width must be > 0, got {p.width:.3f} mm "
            f"(finger_diameter {p.finger_diameter} - 2*air_gap {p.air_gap})"
        )
    if p.segment_height <= 0:
        raise SliderError(f"segment_height must be > 0, got {p.segment_height}")
    if p.air_gap <= 0:
        raise SliderError(f"air_gap must be > 0, got {p.air_gap}")
    if p.corner_radius < 0:
        raise SliderError(f"corner_radius must be >= 0, got {p.corner_radius}")
    if p.tip_radius < 0:
        raise SliderError(f"tip_radius must be >= 0, got {p.tip_radius}")

    if p.segment_shape != "rectangular":
        if p.num_fingers < 1:
            raise SliderError(f"num_fingers must be >=1, got {p.num_fingers}")
        if not 0 < p.amplitude < p.width / 2.0:
            raise SliderError(
                f"tooth_depth (amplitude {p.amplitude:.3f} mm) must be in "
                f"(0, W/2={p.width / 2.0:.3f}) so adjacent teeth do not collide"
            )

    if not p.relax_finger_constraint:
        lhs = p.width + 2.0 * p.air_gap
        if abs(lhs - p.finger_diameter) > FINGER_CONSTRAINT_TOL:
            raise SliderError(
                f"W + 2A = {lhs:.3f} mm violates the finger constraint "
                f"(finger_diameter = {p.finger_diameter} mm, "
                f"tolerance +/-{FINGER_CONSTRAINT_TOL} mm; Infineon AN85951 Eq. 73). "
                f"Set segment_width to ~{p.finger_diameter - 2 * p.air_gap:.3f} mm, "
                f"adjust finger_diameter, or pass relax_finger_constraint=True."
            )
    return p


#: Named starting points drawn from the guidelines doc. Each satisfies the
#: Eq. 73 constraint (or relaxes it explicitly where a vendor's published table
#: does not). Values: guidelines section 2.3 tables.
SLIDER_PRESETS: dict[str, SliderParams] = {
    # Infineon AN85951 recommendation: W=8, A=0.5, ~9 mm finger, +1 dummy/end.
    "infineon": SliderParams(
        name="CT_Slider_Infineon",
        num_segments=5,
        segment_shape="chevron",
        segment_width=8.0,
        segment_height=12.0,
        air_gap=0.5,
        finger_diameter=9.0,
        end_dummies=1,
    ),
    # Microchip AN2934 interpolated slider (Table 1-3): 8 mm finger, derived W.
    "microchip": SliderParams(
        name="CT_Slider_Microchip",
        num_segments=4,
        segment_shape="interdigitated",
        segment_height=12.0,
        air_gap=1.0,
        finger_diameter=8.0,
        num_fingers=5,
        end_dummies=1,
    ),
    # Azoteq AZD125 (Table 6.2): 3-4 elements, 0.5 mm gap, dummies each end.
    "azoteq": SliderParams(
        name="CT_Slider_Azoteq",
        num_segments=4,
        segment_shape="interdigitated",
        segment_height=12.0,
        air_gap=0.5,
        finger_diameter=8.0,
        num_fingers=5,
        end_dummies=1,
    ),
}
