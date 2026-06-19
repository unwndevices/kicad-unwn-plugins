"""Widget parameter dataclasses, presets, and constraint validation.

One dataclass per widget describes *what* to generate; the geometry layer turns
it into polygons. Parameters carry vendor-default presets (from
``docs/capacitive-touch-design-guidelines.md``) and enforce the design
constraints that keep a generated electrode physically sensible.

This module has **no KiCad, geometry, or Qt imports** — it is pure data.
"""

from __future__ import annotations

from .advisory import (
    Advisory,
    check_advisories,
    estimate_cp_pf,
    recommended_series_r,
)
from .fab import (
    DEFAULT_PROFILE,
    FAB_PROFILES,
    FabRules,
    FabViolation,
    check_fab,
)
from .sensing import (
    BOARD_THICKNESS,
    OVERLAY_ER,
    has_overlay,
    validate_sensing,
)
from .serialize import (
    WidgetParams,
    params_from_dict,
    params_from_json,
    params_to_dict,
    params_to_json,
)
from .slider import (
    SLIDER_PRESETS,
    SliderError,
    SliderParams,
    validate_slider,
)
from .support import (
    GROUND_HATCH_PITCH,
    GROUND_HATCH_WIDTH,
    GROUND_MARGIN,
    GUARD_BREAK,
    GUARD_GAP,
    GUARD_WIDTH,
    has_support,
    validate_support,
)
from .trackpad import (
    CLIP_MODES,
    DISABLE_AREA_FRACTION,
    MASK_SHAPES,
    TRACKPAD_PRESETS,
    TrackpadError,
    TrackpadParams,
    validate_trackpad,
)
from .wheel import (
    WHEEL_PRESETS,
    WheelError,
    WheelParams,
    validate_wheel,
)

__all__ = [
    "WidgetParams",
    "params_to_dict",
    "params_from_dict",
    "params_to_json",
    "params_from_json",
    "SliderParams",
    "SliderError",
    "validate_slider",
    "SLIDER_PRESETS",
    "WheelParams",
    "WheelError",
    "validate_wheel",
    "WHEEL_PRESETS",
    "TrackpadParams",
    "TrackpadError",
    "validate_trackpad",
    "TRACKPAD_PRESETS",
    "MASK_SHAPES",
    "CLIP_MODES",
    "DISABLE_AREA_FRACTION",
    "FabRules",
    "FabViolation",
    "FAB_PROFILES",
    "DEFAULT_PROFILE",
    "check_fab",
    "Advisory",
    "check_advisories",
    "estimate_cp_pf",
    "recommended_series_r",
    "has_support",
    "validate_support",
    "has_overlay",
    "validate_sensing",
    "OVERLAY_ER",
    "BOARD_THICKNESS",
    "GROUND_HATCH_PITCH",
    "GROUND_HATCH_WIDTH",
    "GROUND_MARGIN",
    "GUARD_BREAK",
    "GUARD_GAP",
    "GUARD_WIDTH",
]
