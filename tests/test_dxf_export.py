"""DXF export: structure, units, layers, and a geometry round-trip.

The DXF emitter is hand-rolled (no DXF library, mirroring ``sexpr``), so the
round-trip is proven with a tiny independent tag-stream reader here: emit → parse
back → assert the entities carry the right geometry on the right layers, with the
documented Y flip. This is the analogue of the ``sexpr.dumps(sexpr.loads(...))``
round-trip the KiCad exporters use.
"""

from __future__ import annotations

import pytest

from captouch.export import dxf
from captouch.geometry import (
    build_button,
    build_keypad,
    build_mutual_slider,
    build_slider,
    build_trackpad,
    build_wheel,
)
from captouch.params import (
    ButtonParams,
    KeypadParams,
    MutualSliderParams,
    SliderParams,
    TrackpadParams,
    WheelParams,
)


# --------------------------------------------------------------------------- #
# A minimal, independent ASCII-DXF reader (tag-pair stream -> entities).
# --------------------------------------------------------------------------- #
def _tags(text):
    """The DXF as a flat list of ``(code:int, value:str)`` pairs."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    assert len(lines) % 2 == 0, "DXF must be an even stream of code/value lines"
    return [(int(lines[i]), lines[i + 1]) for i in range(0, len(lines), 2)]


def _header_vars(tags):
    """``$VAR -> value`` for the simple (single-value) header variables we emit."""
    out = {}
    for i, (code, value) in enumerate(tags):
        if code == 9 and i + 1 < len(tags):
            out[value] = tags[i + 1][1]
    return out


def _entities(tags):
    """Parse the ENTITIES section into dicts of polylines and circles.

    Returns ``[{"type": "POLYLINE", "layer": str, "closed": bool, "points": [...]},
    {"type": "CIRCLE", "layer": str, "center": (x, y), "radius": float}, ...]``.
    """
    # Restrict to the ENTITIES section.
    start = next(
        i for i, t in enumerate(tags) if t == (0, "SECTION") and tags[i + 1] == (2, "ENTITIES")
    )
    end = next(i for i in range(start, len(tags)) if tags[i] == (0, "ENDSEC"))
    body = tags[start + 2 : end]

    ents = []
    cur = None
    in_vertex = False
    for code, value in body:
        if code == 0:
            if value == "POLYLINE":
                cur = {"type": "POLYLINE", "layer": None, "closed": False, "points": []}
                ents.append(cur)
                in_vertex = False
            elif value == "VERTEX":
                cur["points"].append([None, None])
                in_vertex = True
            elif value == "SEQEND":
                in_vertex = False
            elif value == "CIRCLE":
                cur = {"type": "CIRCLE", "layer": None, "center": [None, None], "radius": None}
                ents.append(cur)
                in_vertex = False
            continue
        if cur is None:
            continue
        if code == 8 and not in_vertex:
            cur["layer"] = value
        elif code == 70 and cur["type"] == "POLYLINE" and not in_vertex:
            cur["closed"] = bool(int(value) & 1)
        elif in_vertex and code == 10:
            cur["points"][-1][0] = float(value)
        elif in_vertex and code == 20:
            cur["points"][-1][1] = float(value)
        elif cur["type"] == "CIRCLE" and code == 10:
            cur["center"][0] = float(value)
        elif cur["type"] == "CIRCLE" and code == 20:
            cur["center"][1] = float(value)
        elif cur["type"] == "CIRCLE" and code == 40:
            cur["radius"] = float(value)
    return ents


def _by_layer(ents, layer, kind=None):
    return [e for e in ents if e["layer"] == layer and (kind is None or e["type"] == kind)]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _slider():
    return build_slider(SliderParams(name="CT_Slider", segment_shape="rectangular"))


def _wheel():
    return build_wheel(
        WheelParams(
            name="CT_Wheel",
            num_segments=5,
            ring_width=5.0,
            air_gap=0.5,
            finger_diameter=8.0,
            segment_width=7.0,
        )
    )


def _trackpad():
    return build_trackpad(TrackpadParams(name="CT_Trackpad", num_rows=3, num_cols=3))


def _keypad_circle():
    return build_keypad(
        KeypadParams(name="CT_Keypad", num_rows=2, num_cols=3, button_shape="circle")
    )


def _button_circle():
    return build_button(ButtonParams(name="CT_Button", outline="circle", style="radial"))


# --------------------------------------------------------------------------- #
# structure & header
# --------------------------------------------------------------------------- #
def test_dxf_is_well_formed_tag_stream():
    text = dxf.widget_dxf_text(_slider())
    tags = _tags(text)  # asserts even code/value stream
    assert tags[0] == (0, "SECTION")
    assert tags[-1] == (0, "EOF")
    # The three sections we emit, in order.
    section_names = [tags[i + 1][1] for i, t in enumerate(tags) if t == (0, "SECTION")]
    assert section_names == ["HEADER", "TABLES", "ENTITIES"]


def test_header_declares_metric_millimetres():
    hv = _header_vars(_tags(dxf.widget_dxf_text(_slider())))
    assert hv["$ACADVER"] == dxf.DXF_VERSION == "AC1009"
    assert hv["$INSUNITS"] == "4"  # millimetres
    assert hv["$MEASUREMENT"] == "1"  # metric


def test_extents_cover_the_geometry():
    geo = _slider()
    tags = _tags(dxf.widget_dxf_text(geo))
    # $EXTMIN/$EXTMAX carry their value on the *following* 10/20 pair.
    ext = {}
    for i, (code, value) in enumerate(tags):
        if code == 9 and value in ("$EXTMIN", "$EXTMAX"):
            ext[value] = (float(tags[i + 1][1]), float(tags[i + 2][1]))
    minx, miny, maxx, maxy = geo.bounds
    # Y is flipped, so the geometry's y-range maps to [-maxy, -miny]; extents must
    # enclose the copper (courtyard/fab grow it slightly outward).
    assert ext["$EXTMIN"][0] <= minx and ext["$EXTMAX"][0] >= maxx
    assert ext["$EXTMIN"][1] <= -maxy and ext["$EXTMAX"][1] >= -miny


def test_only_used_layers_are_declared():
    # A plain slider touches F.Cu, F.Fab, F.CrtYd — but not B.Cu or Vias.
    ents = _entities(_tags(dxf.widget_dxf_text(_slider())))
    layers = {e["layer"] for e in ents}
    assert layers == {"F.Cu", "F.Fab", "F.CrtYd"}


# --------------------------------------------------------------------------- #
# per-widget copper / outline content
# --------------------------------------------------------------------------- #
def test_slider_one_closed_fcu_ring_per_electrode():
    geo = _slider()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    fcu = _by_layer(ents, "F.Cu", "POLYLINE")
    assert len(fcu) == len(geo.electrodes)
    assert all(e["closed"] for e in fcu)
    # F.Fab is the bounding rectangle; F.CrtYd is the grown rectangle.
    assert len(_by_layer(ents, "F.Fab", "POLYLINE")) == 1
    assert len(_by_layer(ents, "F.CrtYd", "POLYLINE")) == 1


def test_slider_first_electrode_round_trips_with_y_flip():
    geo = _slider()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    fcu = _by_layer(ents, "F.Cu", "POLYLINE")
    drawn = fcu[0]["points"]
    expected = [(x, -y) for (x, y) in geo.electrodes[0].points]
    assert len(drawn) == len(expected)
    for (dx, dy), (ex, ey) in zip(drawn, expected):
        assert dx == pytest.approx(ex, abs=1e-4)
        assert dy == pytest.approx(ey, abs=1e-4)


def test_wheel_outline_is_two_circles_plus_round_courtyard():
    geo = _wheel()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    # The wheel's fab is the outer edge + the centre keep-out; the courtyard is a
    # single grown circle — all CIRCLE entities, not polylines.
    fab = _by_layer(ents, "F.Fab", "CIRCLE")
    assert len(fab) == 2
    radii = sorted(c["radius"] for c in fab)
    assert radii[0] == pytest.approx(geo.inner_radius, abs=1e-4)
    assert radii[1] == pytest.approx(geo.outer_radius, abs=1e-4)
    crt = _by_layer(ents, "F.CrtYd", "CIRCLE")
    assert len(crt) == 1 and crt[0]["radius"] > geo.outer_radius
    # One F.Cu ring per wedge.
    assert len(_by_layer(ents, "F.Cu", "POLYLINE")) == len(geo.electrodes)


def test_keypad_round_buttons_emit_true_fab_circles():
    geo = _keypad_circle()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    fab = _by_layer(ents, "F.Fab", "CIRCLE")
    assert len(fab) == geo.params.num_buttons  # one nominal circle per button
    assert all(c["radius"] == pytest.approx(geo.params.button_size / 2.0, abs=1e-4) for c in fab)
    # Copper is the polyline-approximated electrode rings.
    assert len(_by_layer(ents, "F.Cu", "POLYLINE")) == len(geo.electrodes)


def test_button_circle_emits_fab_circle_and_copper():
    geo = _button_circle()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    fab = _by_layer(ents, "F.Fab", "CIRCLE")
    assert len(fab) == 1
    assert fab[0]["radius"] == pytest.approx(geo.params.size / 2.0, abs=1e-4)
    assert len(_by_layer(ents, "F.Cu", "POLYLINE")) == len(geo.electrodes)


def test_trackpad_has_two_copper_layers_and_via_circles():
    geo = _trackpad()
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    assert _by_layer(ents, "F.Cu", "POLYLINE")  # Rx rows + Tx diamonds
    assert _by_layer(ents, "B.Cu", "POLYLINE")  # via-bridge straps
    via_circles = _by_layer(ents, "Vias", "CIRCLE")
    expected_vias = sum(len(net.vias) for net in geo.nets)
    assert expected_vias > 0
    assert len(via_circles) == expected_vias
    assert all(
        c["radius"] == pytest.approx(geo.params.via_diameter / 2.0, abs=1e-4) for c in via_circles
    )


def test_mutual_slider_round_trips():
    geo = build_mutual_slider(MutualSliderParams(name="CT_MutualSlider"))
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    assert _by_layer(ents, "F.Cu", "POLYLINE")
    assert _by_layer(ents, "Vias", "CIRCLE")


# --------------------------------------------------------------------------- #
# support copper
# --------------------------------------------------------------------------- #
def test_support_copper_lands_on_ground_guard_and_via_layers():
    geo = build_slider(SliderParams(name="CT_Slider_Support", ground_hatch=True, guard_ring=True))
    ents = _entities(_tags(dxf.widget_dxf_text(geo)))
    assert _by_layer(ents, "B.Cu", "POLYLINE")  # hatched ground pour outline
    assert _by_layer(ents, "Vias", "CIRCLE")  # GND net-tie
    # The guard ring is F.Cu copper in addition to the electrodes.
    fcu = _by_layer(ents, "F.Cu", "POLYLINE")
    assert len(fcu) == len(geo.electrodes) + 1


def test_no_support_copper_uses_no_back_or_via_layers():
    ents = _entities(_tags(dxf.widget_dxf_text(_slider())))
    assert _by_layer(ents, "B.Cu") == []
    assert _by_layer(ents, "Vias") == []


# --------------------------------------------------------------------------- #
# file writer
# --------------------------------------------------------------------------- #
def test_write_widget_dxf_writes_file(tmp_path):
    out = tmp_path / "part.dxf"
    written = dxf.write_widget_dxf(_slider(), out)
    assert written == out
    text = out.read_text()
    assert text == dxf.widget_dxf_text(_slider())
    assert _tags(text)[-1] == (0, "EOF")
