"""Widget parameter dataclasses, presets, and constraint validation.

One dataclass per widget describes *what* to generate; the geometry layer turns
it into polygons. Parameters carry vendor-default presets (from
``docs/capacitive-touch-design-guidelines.md``) and enforce the design
constraints that keep a generated electrode physically sensible.

This module has **no KiCad, geometry, or Qt imports** — it is pure data.
"""

from __future__ import annotations

from .fab import (
    DEFAULT_PROFILE,
    FAB_PROFILES,
    FabRules,
    FabViolation,
    check_fab,
)
from .slider import (
    SLIDER_PRESETS,
    SliderError,
    SliderParams,
    validate_slider,
)
from .trackpad import (
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
    "FabRules",
    "FabViolation",
    "FAB_PROFILES",
    "DEFAULT_PROFILE",
    "check_fab",
]
