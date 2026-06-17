"""Rotary (wheel) self-capacitance slider parameters, validation, and presets.

A wheel is **a slider bent into a closed ring**: ``num_segments`` electrodes laid
head-to-tail around an annulus so the centroid wraps from the last channel back
to the first. There are therefore **no end electrodes** — the ring is continuous
(Microchip AN2934 §1.2.4; Infineon AN85951 §2.4.2). See
``docs/capacitive-touch-design-guidelines.md`` section 3 / 6.3.

Geometry reuses the slider's pitch rules, bent into polar coordinates. Following
the guidelines' explicit recommendation ("treat wheel radius as derived:
``circumference = num_segments × (segment_width + gap)`` with a centre keep-out
hole"), the **mean radius is derived from the pitch**; the user sets the radial
``ring_width`` and the same ``W`` / ``A`` / finger rules as the slider:

* ``W`` (arc width at the mean radius) derives from the finger as
  ``finger_diameter - 2*air_gap`` so the Infineon ``W + 2A = finger`` constraint
  (Eq. 73) still holds along the arc, unless given explicitly;
* mean circumference ``= num_segments * (W + A)`` → ``mean_radius``;
* ``inner_radius = mean_radius - ring_width/2`` is the centre keep-out hole,
  ``outer_radius = mean_radius + ring_width/2`` the outer edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .slider import FINGER_CONSTRAINT_TOL, SEGMENT_SHAPES, SliderError

__all__ = ["WheelParams", "WheelError", "validate_wheel", "WHEEL_PRESETS"]


class WheelError(SliderError):
    """Raised when a :class:`WheelParams` violates a design constraint.

    Subclasses :class:`SliderError` so callers can catch either with one except.
    """


@dataclass(frozen=True)
class WheelParams:
    """Parameters for a continuous self-capacitance wheel / rotary slider.

    All lengths are in millimetres. Defaults follow the guidelines (section 6.3).

    Attributes
    ----------
    num_segments:
        Number of electrodes around the ring. >=3 is required (a wheel "only
        needs three elements"; guidelines section 3.1).
    segment_shape:
        Boundary style, as for the slider: ``"rectangular"`` (radial bars),
        ``"chevron"`` (triangle-wave arcs), or ``"interdigitated"`` (square-wave
        comb teeth). Teeth oscillate *angularly* and run *radially*.
    segment_width:
        Arc width ``W`` of a segment at the mean radius. ``None`` (default)
        derives it from the finger as ``finger_diameter - 2 * air_gap``.
    ring_width:
        Radial extent of the ring (outer_radius - inner_radius).
    air_gap:
        Inter-electrode gap ``A`` (uniform copper-to-copper clearance, in mm).
    finger_diameter:
        Finger contact-disc diameter used by the Eq. 73 arc-width constraint.
    num_fingers:
        Teeth per boundary (spread radially across the ring width).
    tooth_depth:
        Half-amplitude (mm) of the boundary waveform at the mean radius. ``None``
        derives ``0.3 * W``. Must stay below ``W / 2``.
    corner_radius:
        Extra convex-corner rounding (mm) for ESD relief; ``0`` (default) leaves
        corners as built. Note: chevron wheels additionally get an automatic
        minimum tip relief during the build (a wheel's short ring makes chevron
        tooth-tips acute, and sharp copper points etch poorly — KiCad DRC flags
        them as copper slivers), so a chevron wheel is DRC-clean even at ``0``.
    arc_resolution:
        Circle tessellation quality: polyline segments per 90° of arc (KiCad
        custom-pad polygons cannot hold true arcs, so circles are approximated).
    relax_finger_constraint:
        Skip the Eq. 73 check (for deliberately non-standard geometry).
    name:
        Base name for the emitted footprint / symbol.
    """

    num_segments: int = 5
    segment_shape: str = "chevron"
    segment_width: float | None = None
    ring_width: float = 5.0
    air_gap: float = 0.5
    finger_diameter: float = 8.0
    num_fingers: int = 3
    tooth_depth: float | None = None
    corner_radius: float = 0.0
    arc_resolution: int = 16
    relax_finger_constraint: bool = False
    name: str = "CT_Wheel"

    # -- resolved (derived) quantities ------------------------------------- #
    @property
    def width(self) -> float:
        """Resolved arc width ``W`` at the mean radius (derived if unset)."""
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
        """Arc centre-to-centre spacing at the mean radius, ``W + A``."""
        return self.width + self.air_gap

    @property
    def mean_circumference(self) -> float:
        """Circumference of the mean circle, ``num_segments * pitch``."""
        return self.num_segments * self.pitch

    @property
    def mean_radius(self) -> float:
        """Radius at which the arc width is ``W`` (derived from the pitch)."""
        return self.mean_circumference / (2.0 * math.pi)

    @property
    def inner_radius(self) -> float:
        """Inner edge of the ring — the centre keep-out hole radius."""
        return self.mean_radius - self.ring_width / 2.0

    @property
    def outer_radius(self) -> float:
        """Outer edge of the ring."""
        return self.mean_radius + self.ring_width / 2.0

    @property
    def outer_diameter(self) -> float:
        return 2.0 * self.outer_radius

    @property
    def center_hole_diameter(self) -> float:
        """Diameter of the central keep-out hole (``2 * inner_radius``)."""
        return 2.0 * self.inner_radius

    @property
    def arc_per_segment_deg(self) -> float:
        """Angular span of one segment + gap, ``360 / num_segments`` degrees."""
        return 360.0 / self.num_segments

    def resolved(self) -> "WheelParams":
        """Return a copy with ``segment_width`` / ``tooth_depth`` made explicit."""
        return replace(self, segment_width=self.width, tooth_depth=self.amplitude)


def validate_wheel(p: WheelParams) -> WheelParams:
    """Validate *p*, raising :class:`WheelError` on any constraint violation.

    Returns *p* unchanged on success so it can be used inline.
    """
    if p.segment_shape not in SEGMENT_SHAPES:
        raise WheelError(
            f"segment_shape must be one of {SEGMENT_SHAPES}, got {p.segment_shape!r}"
        )
    if p.num_segments < 3:
        raise WheelError(
            f"num_segments must be >=3 for a usable wheel, got {p.num_segments}"
        )
    if p.width <= 0:
        raise WheelError(
            f"resolved arc width must be > 0, got {p.width:.3f} mm "
            f"(finger_diameter {p.finger_diameter} - 2*air_gap {p.air_gap})"
        )
    if p.ring_width <= 0:
        raise WheelError(f"ring_width must be > 0, got {p.ring_width}")
    if p.air_gap <= 0:
        raise WheelError(f"air_gap must be > 0, got {p.air_gap}")
    if p.corner_radius < 0:
        raise WheelError(f"corner_radius must be >= 0, got {p.corner_radius}")
    if p.arc_resolution < 2:
        raise WheelError(f"arc_resolution must be >= 2, got {p.arc_resolution}")

    if p.inner_radius <= 0:
        raise WheelError(
            f"ring_width {p.ring_width} mm is too wide for the derived mean radius "
            f"{p.mean_radius:.3f} mm (inner radius would be {p.inner_radius:.3f} mm). "
            f"Reduce ring_width, add segments, or widen W."
        )

    # The M gaps must still fit around the inner (smallest) circle, or adjacent
    # segments merge at the hole. Necessary condition: inner arc pitch > gap.
    inner_arc_pitch = p.inner_radius * (2.0 * math.pi / p.num_segments)
    if inner_arc_pitch <= p.air_gap:
        raise WheelError(
            f"segments collide at the centre hole: inner arc pitch "
            f"{inner_arc_pitch:.3f} mm <= air_gap {p.air_gap} mm. "
            f"Reduce ring_width, reduce num_segments, or increase W to grow the "
            f"mean radius and so the centre hole."
        )

    if p.segment_shape != "rectangular":
        if p.num_fingers < 1:
            raise WheelError(f"num_fingers must be >=1, got {p.num_fingers}")
        if not 0 < p.amplitude < p.width / 2.0:
            raise WheelError(
                f"tooth_depth (amplitude {p.amplitude:.3f} mm) must be in "
                f"(0, W/2={p.width / 2.0:.3f}) so adjacent teeth do not collide"
            )

    if not p.relax_finger_constraint:
        lhs = p.width + 2.0 * p.air_gap
        if abs(lhs - p.finger_diameter) > FINGER_CONSTRAINT_TOL:
            raise WheelError(
                f"W + 2A = {lhs:.3f} mm violates the finger constraint "
                f"(finger_diameter = {p.finger_diameter} mm, "
                f"tolerance +/-{FINGER_CONSTRAINT_TOL} mm; Infineon AN85951 Eq. 73). "
                f"Set segment_width to ~{p.finger_diameter - 2 * p.air_gap:.3f} mm, "
                f"adjust finger_diameter, or pass relax_finger_constraint=True."
            )
    return p


#: Named starting points drawn from the guidelines doc (section 3.2 tables). Each
#: satisfies the Eq. 73 arc-width constraint.
WHEEL_PRESETS: dict[str, WheelParams] = {
    # ST AN2869 normal rotary (Fig 15): 5 electrodes, arc width ~8 mm, gap <=0.5.
    "st_rotary": WheelParams(
        name="CT_Wheel_ST",
        num_segments=5,
        segment_shape="chevron",
        segment_width=8.0,
        ring_width=5.0,
        air_gap=0.5,
        finger_diameter=9.0,  # 8 + 2*0.5
        num_fingers=3,
    ),
    # Microchip AN2934 interpolated wheel (Table 1-5): interdigitated, derived W,
    # 4 mm ring, ~5 mm centre hole, 1 mm gap.
    "microchip": WheelParams(
        name="CT_Wheel_Microchip",
        num_segments=4,
        segment_shape="interdigitated",
        ring_width=4.0,
        air_gap=1.0,
        finger_diameter=8.0,
        num_fingers=4,
    ),
    # Infineon CY3280-SRM-style radial slider (AN64846): many fine segments.
    "infineon": WheelParams(
        name="CT_Wheel_Infineon",
        num_segments=8,
        segment_shape="chevron",
        ring_width=5.0,
        air_gap=0.5,
        finger_diameter=8.0,
        num_fingers=3,
    ),
}
