"""Widget parameter dataclasses, presets, and constraint validation.

One dataclass per widget describes *what* to generate; the geometry layer turns
it into polygons. Parameters carry vendor-default presets (from
``docs/capacitive-touch-design-guidelines.md``) and enforce the design
constraints that keep a generated electrode physically sensible.

This module has **no KiCad, geometry, or Qt imports** — it is pure data.
"""

from __future__ import annotations

from .slider import (
    SLIDER_PRESETS,
    SliderError,
    SliderParams,
    validate_slider,
)

__all__ = [
    "SliderParams",
    "SliderError",
    "validate_slider",
    "SLIDER_PRESETS",
]
