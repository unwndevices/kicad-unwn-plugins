"""Pure geometry layer: parameters -> Shapely polygons.

Functions here turn a widget's :mod:`captouch.params` dataclass into the
polygons (electrodes, courtyard bounds) that the exporters and the GUI both
consume — the single source of truth that keeps the preview byte-faithful to the
exported copper.

**No KiCad or Qt imports.** Depends only on Shapely.
"""

from __future__ import annotations

from ._base import Electrode
from .keypad import KeypadGeometry, build_keypad
from .mutual_slider import MutualSliderGeometry, build_mutual_slider
from .slider import SliderGeometry, build_slider
from .trackpad import TrackpadGeometry, TrackpadNet, Via, build_trackpad
from .wheel import WheelGeometry, build_wheel
from .zones import SupportCopper, build_support, net_tie_number

__all__ = [
    "build_slider",
    "SliderGeometry",
    "build_wheel",
    "WheelGeometry",
    "build_trackpad",
    "TrackpadGeometry",
    "TrackpadNet",
    "Via",
    "build_mutual_slider",
    "MutualSliderGeometry",
    "build_keypad",
    "KeypadGeometry",
    "Electrode",
    "SupportCopper",
    "build_support",
    "net_tie_number",
]
