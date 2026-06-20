"""One-call build + export dispatch shared by the CLI, GUI, and KiCad plugin.

The per-widget ``build_*`` / ``*_footprint_text`` / ``*_symbol_lib_text`` functions
already exist in :mod:`captouch.geometry` and :mod:`captouch.export`; this module
is the single place that maps a :class:`~captouch.params.WidgetParams` to its
geometry and then to its ``.kicad_mod`` / ``.kicad_sym`` text, so every frontend
emits *byte-identical* output from the same code path.

The dispatch mirrors the type hierarchy: a :class:`MutualSliderGeometry` is a
:class:`TrackpadGeometry`, so both take the trackpad exporter (the mutual-slider
exporters are exact aliases); every other widget is electrode-based and takes the
shared ``widget_*`` exporter.
"""

from __future__ import annotations

from .export import footprint, symbol
from .export.footprint import WidgetGeometry
from .geometry import (
    TrackpadGeometry,
    build_keypad,
    build_mutual_slider,
    build_slider,
    build_trackpad,
    build_wheel,
)
from .params import (
    KeypadParams,
    MutualSliderParams,
    TrackpadParams,
    WheelParams,
    WidgetParams,
)

__all__ = ["build_widget", "export_widget", "WidgetGeometry"]


def build_widget(params: WidgetParams) -> WidgetGeometry:
    """Build the geometry for any widget from its parameter dataclass.

    Raises the widget's :class:`~captouch.params.SliderError` subclass on invalid
    parameters, exactly as the underlying ``build_*`` function does.
    """
    if isinstance(params, WheelParams):
        return build_wheel(params)
    if isinstance(params, MutualSliderParams):  # subclass check before TrackpadParams
        return build_mutual_slider(params)
    if isinstance(params, TrackpadParams):
        return build_trackpad(params)
    if isinstance(params, KeypadParams):
        return build_keypad(params)
    return build_slider(params)


def export_widget(geo: WidgetGeometry) -> tuple[str, str]:
    """Return ``(footprint_text, symbol_lib_text)`` for a built geometry.

    Both strings are byte-identical to the dedicated per-widget exporters (and so
    to the standalone CLI output) — this is the single source of truth the GUI and
    the KiCad plugin reuse to stay faithful to the on-screen preview.
    """
    if isinstance(geo, TrackpadGeometry):  # also catches MutualSliderGeometry
        return footprint.trackpad_footprint_text(geo), symbol.trackpad_symbol_lib_text(geo)
    return footprint.widget_footprint_text(geo), symbol.widget_symbol_lib_text(geo)
