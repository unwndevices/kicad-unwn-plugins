"""JSON (de)serialisation of widget parameter sets."""

from __future__ import annotations

import pytest

from captouch.params import (
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    ButtonParams,
    KeypadParams,
    SliderParams,
    TrackpadParams,
    WheelParams,
    params_from_json,
    params_to_json,
)

_ALL_PRESETS = [
    *SLIDER_PRESETS.values(),
    *WHEEL_PRESETS.values(),
    *TRACKPAD_PRESETS.values(),
    SliderParams(),
    WheelParams(),
    TrackpadParams(),
    KeypadParams(),
    ButtonParams(),
]


@pytest.mark.parametrize("p", _ALL_PRESETS)
def test_json_round_trip_is_faithful(p):
    back = params_from_json(params_to_json(p))
    assert back == p
    assert type(back) is type(p)
    # Re-serialising the round-tripped value is byte-identical.
    assert params_to_json(back) == params_to_json(p)


def test_widget_tag_selects_type():
    assert isinstance(params_from_json(params_to_json(WheelParams())), WheelParams)
    assert isinstance(params_from_json(params_to_json(TrackpadParams())), TrackpadParams)


def test_unknown_fields_ignored_and_missing_default():
    text = '{"widget": "slider", "params": {"num_segments": 6, "bogus": 99}}'
    p = params_from_json(text)
    assert isinstance(p, SliderParams)
    assert p.num_segments == 6
    assert p.air_gap == SliderParams().air_gap  # missing key -> default


def test_bad_widget_key_rejected():
    with pytest.raises(ValueError, match="widget"):
        params_from_json('{"widget": "octopad", "params": {}}')
