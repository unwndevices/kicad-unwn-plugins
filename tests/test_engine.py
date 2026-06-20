"""The shared build/export dispatch must match the per-widget exporters exactly.

Every frontend (CLI, GUI, KiCad plugin) routes through :mod:`captouch.engine`, so
its output must be byte-identical to the dedicated ``*_footprint_text`` /
``*_symbol_lib_text`` functions — otherwise a part placed via the plugin would
differ from the same part exported from the CLI.
"""

from __future__ import annotations

import pytest

from captouch import engine
from captouch.export import footprint, symbol
from captouch.geometry import (
    build_keypad,
    build_mutual_slider,
    build_slider,
    build_trackpad,
    build_wheel,
)
from captouch.params import (
    KeypadParams,
    MutualSliderParams,
    SliderParams,
    TrackpadParams,
    WheelParams,
)

# (params, builder, footprint_text_fn, symbol_text_fn) per widget type.
_CASES = [
    (
        SliderParams(name="CT_Slider"),
        build_slider,
        footprint.slider_footprint_text,
        symbol.slider_symbol_lib_text,
    ),
    (
        WheelParams(name="CT_Wheel"),
        build_wheel,
        footprint.wheel_footprint_text,
        symbol.wheel_symbol_lib_text,
    ),
    (
        TrackpadParams(name="CT_Trackpad"),
        build_trackpad,
        footprint.trackpad_footprint_text,
        symbol.trackpad_symbol_lib_text,
    ),
    (
        MutualSliderParams(name="CT_MutualSlider"),
        build_mutual_slider,
        footprint.mutual_slider_footprint_text,
        symbol.mutual_slider_symbol_lib_text,
    ),
    (
        KeypadParams(name="CT_Keypad"),
        build_keypad,
        footprint.keypad_footprint_text,
        symbol.keypad_symbol_lib_text,
    ),
]


@pytest.mark.parametrize("params,build,fp_fn,sym_fn", _CASES)
def test_dispatch_matches_per_widget_functions(params, build, fp_fn, sym_fn):
    geo = engine.build_widget(params)
    # build_widget must produce the same geometry the dedicated builder does.
    assert type(geo) is type(build(params))

    fp_text, sym_text = engine.export_widget(geo)
    assert fp_text == fp_fn(geo)
    assert sym_text == sym_fn(geo)


def test_build_widget_raises_on_invalid_params():
    from captouch.params import SliderError

    with pytest.raises(SliderError):
        engine.build_widget(SliderParams(num_segments=1))  # below the 3-segment minimum
