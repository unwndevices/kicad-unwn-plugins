"""JSON (de)serialisation of a widget parameter set.

A saved file is ``{"widget": "slider"|"wheel"|"trackpad", "params": {…}}`` — the
``widget`` tag lets a parameter set round-trip through the CLI and the GUI's
widget switcher. Only known dataclass fields are read back, so a file written by
a newer build still loads (unknown keys ignored, missing keys take defaults).

Pure data: no KiCad/geometry/Qt imports.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Union

from .keypad import KeypadParams
from .mutual_slider import MutualSliderParams
from .slider import SliderParams
from .trackpad import TrackpadParams
from .wheel import WheelParams

WidgetParams = Union[SliderParams, WheelParams, TrackpadParams, MutualSliderParams, KeypadParams]

_WIDGET_FOR_TYPE: dict[type, str] = {
    SliderParams: "slider",
    WheelParams: "wheel",
    TrackpadParams: "trackpad",
    MutualSliderParams: "mutual-slider",
    KeypadParams: "keypad",
}
_TYPE_FOR_WIDGET: dict[str, type[WidgetParams]] = {
    "slider": SliderParams,
    "wheel": WheelParams,
    "trackpad": TrackpadParams,
    "mutual-slider": MutualSliderParams,
    "keypad": KeypadParams,
}


def params_to_dict(p: WidgetParams) -> dict:
    """Tag *p* with its widget kind and flatten its fields to a plain dict."""
    try:
        widget = _WIDGET_FOR_TYPE[type(p)]
    except KeyError:
        raise TypeError(f"not a widget parameter set: {type(p).__name__}") from None
    return {"widget": widget, "params": asdict(p)}


def params_from_dict(d: dict) -> WidgetParams:
    """Rebuild a widget parameter set from :func:`params_to_dict` output."""
    widget = d.get("widget")
    cls = _TYPE_FOR_WIDGET.get(widget) if isinstance(widget, str) else None
    if cls is None:
        raise ValueError(f"unknown or missing 'widget' key: {widget!r}")
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in d.get("params", {}).items() if k in known}
    return cls(**kwargs)


def params_to_json(p: WidgetParams) -> str:
    """Serialise *p* to JSON text (trailing newline)."""
    return json.dumps(params_to_dict(p), indent=2) + "\n"


def params_from_json(text: str) -> WidgetParams:
    """Parse JSON *text* written by :func:`params_to_json` back into params."""
    return params_from_dict(json.loads(text))
