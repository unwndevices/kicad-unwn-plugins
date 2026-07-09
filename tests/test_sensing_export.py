"""Series-R symbol note + the overlay params never change emitted output."""

from __future__ import annotations

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import build_slider, build_trackpad, build_wheel
from captouch.params import SliderParams, TrackpadParams, WheelParams
from kicad_core import sexpr


def _find_property(sym_text: str, name: str):
    """Return the ``(property …)`` node of *name* from a one-symbol library, or None."""
    sym = sexpr.find(sexpr.loads(sym_text), "symbol")  # lib → first symbol
    for prop in sexpr.find_all(sym, "property"):
        if sexpr.children(prop)[0] == name:
            return prop
    return None


def _series_r_property(sym_text: str) -> str | None:
    prop = _find_property(sym_text, "Series_R")
    return sexpr.children(prop)[1] if prop is not None else None


def test_self_cap_symbols_carry_560r_note():
    for geo in (build_slider(SliderParams(name="S")), build_wheel(WheelParams(name="W"))):
        value = _series_r_property(symbol.widget_symbol_lib_text(geo))
        assert value is not None
        assert "560 Ω" in value and "self-cap" in value


def test_mutual_cap_symbol_carries_2k_note():
    geo = build_trackpad(TrackpadParams(name="T", num_rows=3, num_cols=3))
    value = _series_r_property(symbol.widget_symbol_lib_text(geo))
    assert value is not None
    assert "2 kΩ" in value and "mutual-cap" in value


def test_series_r_property_is_hidden():
    geo = build_slider(SliderParams(name="S"))
    prop = _find_property(symbol.widget_symbol_lib_text(geo), "Series_R")
    assert prop is not None
    assert sexpr.find(sexpr.find(prop, "effects"), "hide") is not None


@pytest.mark.parametrize(
    "build,params_cls,kwargs",
    [
        (build_slider, SliderParams, {}),
        (build_wheel, WheelParams, {}),
        (build_trackpad, TrackpadParams, {"num_rows": 3, "num_cols": 3}),
    ],
)
def test_overlay_params_do_not_change_emitted_output(build, params_cls, kwargs):
    # Overlay / board fields feed advisories only — toggling them must leave the
    # footprint and symbol byte-identical (Phase 9 verification rule).
    a = build(params_cls(name="X", **kwargs))
    b = build(
        params_cls(name="X", overlay_thickness=2.0, overlay_er=7.8, board_thickness=0.8, **kwargs)
    )
    if isinstance(a.params, TrackpadParams):
        fp_a, fp_b = footprint.trackpad_footprint_text(a), footprint.trackpad_footprint_text(b)
    else:
        fp_a, fp_b = footprint.widget_footprint_text(a), footprint.widget_footprint_text(b)
    assert fp_a == fp_b
    assert symbol.widget_symbol_lib_text(a) == symbol.widget_symbol_lib_text(b)
