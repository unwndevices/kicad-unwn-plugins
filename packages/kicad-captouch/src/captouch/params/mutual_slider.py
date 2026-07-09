"""Linear **mutual-capacitance** (CSX) slider parameters, validation, and presets.

Where the self-cap slider (:mod:`captouch.params.slider`) is a 1-D array of
individually-sensed bars, a mutual-cap slider interleaves **drive (Tx)** and
**sense (Rx)** electrodes: position is read from the mutual-capacitance change at
each Tx×Rx crossing. The vendor-canonical layout is *"a single Y/Rx sense line
spanning multiple X/Tx drive lines"* (Microchip AN2934 Table 2-3; ST; see
``docs/capacitive-touch-design-guidelines.md`` §2.4), which is geometrically a
**diamond trackpad collapsed to one sense row**:

* the **Rx sense line** is one continuous F.Cu row of diamonds joined by necks,
  running the length of the slider (1 pin);
* each **Tx drive electrode** is a vertical pair of diamonds straddling the Rx row,
  linked by a B.Cu strap over two thru-hole vias that hops the Rx neck — exactly
  the trackpad's Tx column (one pin each).

So an ``N``-segment mutual slider has ``N`` Tx drive electrodes (= ``N`` position
nodes) plus ``sense_rows`` Rx lines, i.e. ``N + sense_rows`` pins. This module is a
thin **slider-flavoured façade over :class:`~captouch.params.trackpad.TrackpadParams`**:
:meth:`MutualSliderParams.to_trackpad` maps it onto the trackpad so the whole
diamond/neck/via-bridge geometry, exporter, preview, and DRC gate are reused
verbatim (the geometry layer calls :func:`~captouch.geometry.build_trackpad` with
``min_lines=1`` to permit the single sense row).

This module has **no KiCad, geometry, or Qt imports** — it is pure data.
"""

from __future__ import annotations

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
from .trackpad import TrackpadParams, validate_trackpad

__all__ = [
    "MutualSliderParams",
    "MutualSliderError",
    "validate_mutual_slider",
    "MUTUAL_SLIDER_PRESETS",
    "MIN_SEGMENTS",
    "MAX_SENSE_ROWS",
]

#: Fewest Tx drive electrodes (= position nodes) for usable centroid interpolation
#: — same 3-electrode floor as the self-cap slider (guidelines §2.1 / §3.1).
MIN_SEGMENTS = 3

#: Most Rx sense rows. 1 = the canonical single-Y line (Microchip §2.4); 2 = a
#: dual-row layout for a stronger mutual signal (Infineon "Dual Solid Diamond",
#: AN234185 §3.1.1). More than two rows is a 2-D pad, i.e. a trackpad, not a slider.
MAX_SENSE_ROWS = 2


class MutualSliderError(SliderError):
    """Raised when a :class:`MutualSliderParams` violates a design constraint.

    Subclasses :class:`SliderError` (as :class:`~captouch.params.trackpad.TrackpadError`
    does) so the GUI/CLI ``except SliderError`` paths catch it with one handler.
    """


@dataclass(frozen=True)
class MutualSliderParams:
    """Parameters for a linear mutual-cap (CSX) diamond slider.

    All lengths are in millimetres. Defaults follow the guidelines (§2.4).

    Attributes
    ----------
    num_segments:
        Number of **Tx (drive)** electrodes along the slider — one per position
        node, ``>= MIN_SEGMENTS`` (3) for usable interpolation. Maps to the
        trackpad's ``num_cols``.
    sense_rows:
        Number of **Rx (sense)** rows, ``1``..:data:`MAX_SENSE_ROWS`. ``1`` (default)
        is the canonical single continuous sense line (Microchip §2.4); ``2`` is a
        dual-row layout for stronger mutual coupling (Infineon DSD). Maps to the
        trackpad's ``num_rows``.
    diamond_pitch:
        Centre-to-centre spacing ``P`` of the drive electrodes along the slider —
        the position-resolution granularity (and, ``× sense_rows``, the slider's
        transverse height). ~6 mm suits an ~8 mm finger so a contact always spans
        >=2 nodes.
    diamond_gap:
        Copper-to-copper gap ``A`` between the facing edges of adjacent Rx/Tx
        diamonds (vendor range 0.1–1 mm, typ 0.3–0.5).
    bridge_width:
        Width of the F.Cu necks (Rx) and B.Cu straps (Tx) joining the diamonds.
    via_drill, via_diameter:
        Bridge-via finished hole and outer-copper diameters
        (``via_diameter >= via_drill + 2·MIN_ANNULAR``).
    name:
        Base name for the emitted footprint / symbol.
    ground_hatch, ground_margin, ground_hatch_width, ground_hatch_pitch,
    guard_ring, guard_width, guard_gap, guard_break, guard_mask_open:
        Optional, **default-off** board-level support copper. See
        :mod:`captouch.params.support`.
    overlay_thickness, overlay_er, board_thickness:
        Front-panel / board-stack context for the **advisory** checks only (never
        drawn). See :mod:`captouch.params.sensing` and :mod:`captouch.params.advisory`.
    """

    num_segments: int = 5
    sense_rows: int = 1
    diamond_pitch: float = 6.0
    diamond_gap: float = 0.5
    bridge_width: float = 0.2
    via_drill: float = 0.3
    via_diameter: float = 0.6
    name: str = "CT_MutualSlider"

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
    def num_nodes(self) -> int:
        """Independently-sensed crossings, ``num_segments · sense_rows``."""
        return self.num_segments * self.sense_rows

    @property
    def num_pins(self) -> int:
        """Total pins / pads, ``num_segments + sense_rows`` (one per Tx/Rx line)."""
        return self.num_segments + self.sense_rows

    @property
    def total_length(self) -> float:
        """Overall slider length, the diamond-lattice extent ``num_segments · pitch``."""
        return self.num_segments * self.diamond_pitch

    @property
    def height(self) -> float:
        """Transverse extent of the slider, ``sense_rows · pitch``."""
        return self.sense_rows * self.diamond_pitch

    def resolved(self) -> "MutualSliderParams":
        """Return a copy (parity with the other widgets; nothing to resolve here)."""
        return replace(self)

    def to_trackpad(self) -> TrackpadParams:
        """Map onto an equivalent :class:`TrackpadParams` (the shared geometry engine).

        ``num_segments → num_cols`` (Tx drive electrodes) and
        ``sense_rows → num_rows`` (Rx sense lines); the diamond/bridge/via fields,
        the optional support copper, and the overlay context all pass through. The
        outer mask is always a plain rectangle (a 1-D strip), so no curved-mask
        fields are set.
        """
        return TrackpadParams(
            name=self.name,
            num_rows=self.sense_rows,
            num_cols=self.num_segments,
            diamond_pitch=self.diamond_pitch,
            diamond_gap=self.diamond_gap,
            bridge_width=self.bridge_width,
            via_drill=self.via_drill,
            via_diameter=self.via_diameter,
            mask_shape="rect",
            ground_hatch=self.ground_hatch,
            ground_margin=self.ground_margin,
            ground_hatch_width=self.ground_hatch_width,
            ground_hatch_pitch=self.ground_hatch_pitch,
            guard_ring=self.guard_ring,
            guard_width=self.guard_width,
            guard_gap=self.guard_gap,
            guard_break=self.guard_break,
            guard_mask_open=self.guard_mask_open,
            overlay_thickness=self.overlay_thickness,
            overlay_er=self.overlay_er,
            board_thickness=self.board_thickness,
        )

    def fit_to_length(self, length: float) -> "MutualSliderParams":
        """Return a copy whose ``num_segments`` best matches a target overall *length*.

        Sizes the slider from its known length instead of a node count: rounds
        ``length / diamond_pitch`` to the nearest whole segment (the pitch is fixed
        by the diamond geometry and is not stretched), floored at
        :data:`MIN_SEGMENTS`. The achieved :attr:`total_length` lands within half a
        pitch of the target.
        """
        if self.diamond_pitch <= 0:
            raise MutualSliderError(
                f"cannot size from length: diamond_pitch is {self.diamond_pitch} mm (<= 0)"
            )
        segments = max(MIN_SEGMENTS, round(length / self.diamond_pitch))
        return replace(self, num_segments=segments)


def validate_mutual_slider(p: MutualSliderParams) -> MutualSliderParams:
    """Validate *p*, raising :class:`MutualSliderError` on any constraint violation.

    Checks the slider-level constraints (segment count, sense-row count) with the
    mutual-slider field names, then defers the diamond/gap/bridge/via geometry
    checks to :func:`~captouch.params.trackpad.validate_trackpad` (with
    ``min_lines=1`` to allow the single sense row), reusing the shared engine.
    Returns *p* unchanged on success so it can be used inline.
    """
    require_finite(p, MutualSliderError)
    validate_support(p, MutualSliderError)
    validate_sensing(p, MutualSliderError)
    if p.num_segments < MIN_SEGMENTS:
        raise MutualSliderError(
            f"num_segments must be >= {MIN_SEGMENTS} for usable interpolation, got {p.num_segments}"
        )
    if not 1 <= p.sense_rows <= MAX_SENSE_ROWS:
        raise MutualSliderError(
            f"sense_rows must be 1..{MAX_SENSE_ROWS} (1 = single sense line, "
            f"{MAX_SENSE_ROWS} = dual-row; more rows is a trackpad), got {p.sense_rows}"
        )
    # Diamond / gap / bridge / via geometry is identical to the trackpad's; reuse
    # its validator (min_lines=1 permits the single sense row). It raises a
    # TrackpadError (also a SliderError) naming the shared field on violation.
    validate_trackpad(p.to_trackpad(), min_lines=1)
    return p


#: Named starting points from the guidelines doc (§2.4). The two-layer mutual
#: slider needs vias, so these all exercise the bridge geometry.
MUTUAL_SLIDER_PRESETS: dict[str, MutualSliderParams] = {
    # Microchip AN2934 Table 2-3 interleaved: a single Y/Rx line spanning the X/Tx
    # drive electrodes — the canonical, pin-frugal mutual slider (N + 1 pins).
    "microchip": MutualSliderParams(
        name="CT_MutualSlider_Microchip",
        num_segments=5,
        sense_rows=1,
        diamond_pitch=6.0,
        diamond_gap=0.5,
    ),
    # Dual-row (Infineon DSD, AN234185 §3.1.1): two Rx rows for a stronger mutual
    # signal, at the cost of one extra sense pin (N + 2 pins).
    "dual": MutualSliderParams(
        name="CT_MutualSlider_Dual",
        num_segments=5,
        sense_rows=2,
        diamond_pitch=5.0,
        diamond_gap=0.5,
    ),
    # Small smoke/demo slider — the fewest nodes that still interpolate.
    "compact": MutualSliderParams(
        name="CT_MutualSlider_Compact",
        num_segments=3,
        sense_rows=1,
        diamond_pitch=5.0,
        diamond_gap=0.5,
    ),
}
