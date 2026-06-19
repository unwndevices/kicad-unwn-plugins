"""GUI tests for the Phase-2 slider app (headless / offscreen Qt).

Coverage mirrors the phase's "done when":
  * editing a parameter updates the preview (live rebuild + WYSIWYG), and
  * the exported file matches the preview (byte-identical to the displayed
    geometry's exporter output).

Plus the supporting behaviours: preset round-trip, the ``changed`` signal,
validation that preserves the last good preview, and layer toggles.
"""

from __future__ import annotations

import pytest

from captouch.export import footprint, symbol
from captouch.geometry import (
    MutualSliderGeometry,
    TrackpadGeometry,
    WheelGeometry,
    build_mutual_slider,
    build_slider,
    build_trackpad,
    build_wheel,
)
from captouch.geometry._base import polygon_points
from captouch.params import (
    MUTUAL_SLIDER_PRESETS,
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    MutualSliderParams,
    SliderParams,
    TrackpadParams,
)

pytestmark = pytest.mark.usefixtures("qapp")


# --------------------------------------------------------------------------- #
# parameter panel
# --------------------------------------------------------------------------- #
def test_panel_defaults_build_valid_geometry(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    geo = build_slider(panel.params())  # must not raise
    assert len(geo.active) == 4  # SliderParams() default


@pytest.mark.parametrize("key", sorted(SLIDER_PRESETS))
def test_preset_roundtrips_through_panel(qapp, key):
    from captouch.gui.panel import ParamPanel

    preset = SLIDER_PRESETS[key]
    panel = ParamPanel()
    panel.set_params(preset)
    got = panel.params()

    # The resolved (engine-visible) parameters must survive the round-trip.
    assert got.segment_shape == preset.segment_shape
    assert got.num_segments == preset.num_segments
    assert got.end_dummies == preset.end_dummies
    assert got.width == pytest.approx(preset.width)
    assert got.air_gap == pytest.approx(preset.air_gap)
    assert got.amplitude == pytest.approx(preset.amplitude)
    # Whether a field is auto-derived is preserved too.
    assert (got.segment_width is None) == (preset.segment_width is None)
    build_slider(got)  # the loaded params still build


def test_editing_emits_changed_but_loading_does_not(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    hits = []
    panel.changed.connect(lambda: hits.append(1))

    # Programmatic load is silent.
    panel.set_params(SLIDER_PRESETS["infineon"])
    assert hits == []

    # A user edit fires exactly one signal.
    panel.num_segments.setValue(panel.num_segments.value() + 1)
    assert len(hits) == 1


def test_panel_cannot_emit_subminimum_segments(qapp):
    """The spin box clamps num_segments to the >=3 engine minimum."""
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    panel.num_segments.setValue(1)
    assert panel.params().num_segments == 3


def test_slider_panel_length_driven_derives_count(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    assert not panel.length_driven.isChecked()
    assert panel.num_segments.isEnabled() and not panel.target_length.isEnabled()

    panel.length_driven.setChecked(True)
    panel.target_length.setValue(80.0)
    p = panel.params()
    assert p.num_segments == 9  # derived for the 80 mm target at the default pitch
    assert abs(p.total_length - 80.0) <= p.pitch / 2 + 1e-9
    assert not panel.num_segments.isEnabled()  # read-only in size mode
    build_slider(p)
    # Loading a preset switches back to count-driven.
    panel.set_params(SLIDER_PRESETS["infineon"])
    assert not panel.length_driven.isChecked()


# --------------------------------------------------------------------------- #
# preview — WYSIWYG
# --------------------------------------------------------------------------- #
def test_preview_polygons_match_geometry_points(qapp):
    from captouch.gui.preview import PreviewView

    geo = build_slider(SLIDER_PRESETS["infineon"])
    view = PreviewView()
    view.set_geometry(geo)

    for e in geo.electrodes:
        drawn = view.electrode_polygon_points(e.pad_number)
        assert drawn == e.points, f"pad {e.pad_number} preview != geometry"


def test_layer_toggle_changes_item_visibility(qapp):
    from captouch.gui.preview import PreviewView

    view = PreviewView()
    view.set_geometry(build_slider(SliderParams()))
    pad = "1"
    assert view._electrode_items[pad].isVisible()  # copper on by default
    view.set_layer_visible("copper", False)
    assert not view._electrode_items[pad].isVisible()
    view.set_layer_visible("copper", True)
    assert view._electrode_items[pad].isVisible()


# --------------------------------------------------------------------------- #
# main window — live rebuild, validation, export
# --------------------------------------------------------------------------- #
def test_editing_updates_preview_live(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    before = len(win.preview.geometry_model.electrodes)
    win.panel.num_segments.setValue(win.panel.num_segments.value() + 1)  # emits changed
    after = len(win.preview.geometry_model.electrodes)
    assert after == before + 1  # one more active electrode is now on screen


def test_invalid_params_keep_last_preview(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win.panel.set_params(SLIDER_PRESETS["infineon"])
    win._rebuild()
    good = win.preview.geometry_model
    assert good is not None

    # Reachable invalid state: explicit W with W + 2A far from the finger.
    win.panel.segment_width_auto.setChecked(False)
    win.panel.segment_width.setValue(8.0)
    win.panel.air_gap.setValue(0.5)
    win.panel.finger_diameter.setValue(20.0)
    win._rebuild()

    assert win._status.text().startswith("⚠")  # warning shown
    assert win.preview.geometry_model is good  # preview untouched
    assert win._export_btn.isEnabled()  # last good geometry still exportable


def test_export_matches_preview(qapp, tmp_path):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win.panel.set_params(SLIDER_PRESETS["microchip"])
    win._rebuild()
    geo = win.preview.geometry_model

    fp_path, sym_path = win.export_to(tmp_path)

    # Files exist and are byte-identical to the exporter's output for the
    # geometry currently on screen — i.e. the export matches the preview.
    assert fp_path.read_text() == footprint.slider_footprint_text(geo)
    assert sym_path.read_text() == symbol.slider_symbol_lib_text(geo)

    # Sanity: one pad per electrode.
    assert fp_path.read_text().count("(pad ") == len(geo.electrodes)


def test_export_without_geometry_raises(qapp, tmp_path):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._geo = None
    with pytest.raises(RuntimeError):
        win.export_to(tmp_path)


# --------------------------------------------------------------------------- #
# widget switcher — wheel
# --------------------------------------------------------------------------- #
def test_default_widget_is_slider(qapp):
    from captouch.gui.app import MainWindow
    from captouch.gui.panel import ParamPanel

    win = MainWindow()
    assert isinstance(win.panel, ParamPanel)


def test_switch_to_wheel_builds_wheel_geometry(qapp):
    from captouch.gui.app import MainWindow
    from captouch.gui.wheel_panel import WheelPanel

    win = MainWindow()
    win._on_widget_changed(1)  # 0 = Slider, 1 = Wheel
    assert isinstance(win.panel, WheelPanel)
    assert isinstance(win.preview.geometry_model, WheelGeometry)


def test_wheel_preview_matches_geometry(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(1)
    win.panel.set_params(WHEEL_PRESETS["infineon"])
    win._rebuild()
    geo = win.preview.geometry_model
    for e in geo.electrodes:
        assert win.preview.electrode_polygon_points(e.pad_number) == e.points


def test_wheel_export_matches_preview(qapp, tmp_path):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(1)
    win.panel.set_params(WHEEL_PRESETS["microchip"])
    win._rebuild()
    geo = win.preview.geometry_model

    fp_path, sym_path = win.export_to(tmp_path)
    assert fp_path.read_text() == footprint.widget_footprint_text(geo)
    assert sym_path.read_text() == symbol.widget_symbol_lib_text(geo)
    assert fp_path.read_text().count("(pad ") == len(geo.electrodes)


def test_wheel_panel_diameter_driven_derives_count(qapp):
    from captouch.gui.wheel_panel import WheelPanel

    panel = WheelPanel()
    assert not panel.diameter_driven.isChecked()
    assert panel.num_segments.isEnabled() and not panel.target_diameter.isEnabled()

    panel.diameter_driven.setChecked(True)
    panel.target_diameter.setValue(50.0)
    p = panel.params()
    assert abs(p.outer_diameter - 50.0) <= p.pitch + 1e-9
    assert not panel.num_segments.isEnabled()  # read-only in size mode
    build_wheel(p)
    # Loading a preset switches back to count-driven.
    panel.set_params(WHEEL_PRESETS["microchip"])
    assert not panel.diameter_driven.isChecked()


# --------------------------------------------------------------------------- #
# widget switcher — trackpad
# --------------------------------------------------------------------------- #
def test_trackpad_panel_defaults_build_valid_geometry(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    geo = build_trackpad(panel.params())  # must not raise
    assert len(geo.nets) == TrackpadParams().num_pins


@pytest.mark.parametrize("key", sorted(TRACKPAD_PRESETS))
def test_trackpad_preset_roundtrips_through_panel(qapp, key):
    from captouch.gui.trackpad_panel import TrackpadPanel

    preset = TRACKPAD_PRESETS[key]
    panel = TrackpadPanel()
    panel.set_params(preset)
    got = panel.params()
    assert (got.num_rows, got.num_cols) == (preset.num_rows, preset.num_cols)
    assert got.diamond_pitch == pytest.approx(preset.diamond_pitch)
    assert got.diamond_gap == pytest.approx(preset.diamond_gap)
    build_trackpad(got)  # the loaded params still build


def test_switch_to_trackpad_builds_trackpad_geometry(qapp):
    from captouch.gui.app import MainWindow
    from captouch.gui.trackpad_panel import TrackpadPanel

    win = MainWindow()
    win._on_widget_changed(2)  # 0 = Slider, 1 = Wheel, 2 = Trackpad
    assert isinstance(win.panel, TrackpadPanel)
    assert isinstance(win.preview.geometry_model, TrackpadGeometry)


def test_trackpad_preview_matches_geometry(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(2)
    win.panel.set_params(TRACKPAD_PRESETS["compact"])
    win._rebuild()
    geo = win.preview.geometry_model
    # Drawn pieces (B.Cu straps first, then F.Cu copper) match the geometry's
    # exact emitted points — the WYSIWYG guarantee, now across two layers.
    for net in geo.nets:
        expected = [polygon_points(p) for p in net.bcu] + [polygon_points(p) for p in net.fcu]
        assert win.preview.net_polygon_points(net.pad_number) == expected


def test_trackpad_panel_size_driven_derives_counts(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    # Off by default: count-driven, no panel recorded.
    assert not panel.size_driven.isChecked()
    assert panel.params().panel_width is None
    assert panel.num_rows.isEnabled() and not panel.panel_width.isEnabled()

    panel.size_driven.setChecked(True)
    panel.diamond_pitch.setValue(5.0)
    panel.panel_width.setValue(300.0)
    panel.panel_height.setValue(200.0)
    p = panel.params()
    assert (p.num_cols, p.num_rows) == (60, 40)  # round(dim / pitch)
    assert (p.panel_width, p.panel_height) == (300.0, 200.0)
    assert (p.width, p.height) == (300.0, 200.0)  # outline pinned to the target
    # The manual count spins are read-only while size-driven.
    assert not panel.num_rows.isEnabled() and panel.panel_width.isEnabled()
    build_trackpad(p)  # must not raise


def test_trackpad_panel_restores_size_mode_on_load(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(TrackpadParams.from_size(120, 80, diamond_pitch=4.0, name="RT"))
    assert panel.size_driven.isChecked()
    got = panel.params()
    assert (got.panel_width, got.panel_height) == (120.0, 80.0)
    assert (got.num_cols, got.num_rows) == (30, 20)
    # Loading a plain count-driven params switches the mode back off.
    panel.set_params(TrackpadParams(num_rows=4, num_cols=5))
    assert not panel.size_driven.isChecked()
    assert panel.params().panel_width is None


def test_trackpad_panel_mask_controls_drive_params(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(TrackpadParams(num_rows=4, num_cols=4))
    assert panel.params().mask_shape == "rect"

    panel.mask_shape.setCurrentText("circle")
    p = panel.params()
    assert p.mask_shape == "circle" and p.radius is None  # Auto → inscribed default
    assert build_trackpad(p).fab_primitives[0][0] == "circle"  # must not raise

    panel.mask_shape.setCurrentText("rrect")
    panel.corner_radius.setValue(2.5)
    assert panel.params().mask_shape == "rrect"
    assert panel.params().corner_radius == 2.5


def test_trackpad_panel_roundtrips_circle_params(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle", radius=9.0))
    got = panel.params()
    assert got.mask_shape == "circle" and got.radius == 9.0


def test_trackpad_panel_clip_mode_drives_param_and_enable_state(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(TrackpadParams(num_rows=6, num_cols=6))
    assert panel.params().clip_mode == "inscribe"
    assert not panel.clip_mode.isEnabled()  # inert for the rect mask

    panel.mask_shape.setCurrentText("circle")
    assert panel.clip_mode.isEnabled()
    panel.clip_mode.setCurrentText("conform")
    p = panel.params()
    assert p.mask_shape == "circle" and p.clip_mode == "conform"
    assert build_trackpad(p).partial_channels()  # cut rim → flagged channels


def test_trackpad_panel_roundtrips_conform(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(
        TrackpadParams(num_rows=5, num_cols=5, mask_shape="circle", clip_mode="conform")
    )
    assert panel.params().clip_mode == "conform"


@pytest.mark.parametrize("shape,kw", [("rrect", {"corner_radius": 2.0}), ("circle", {})])
def test_trackpad_masked_outline_renders(qapp, shape, kw):
    from captouch.gui.preview import PreviewView

    geo = build_trackpad(TrackpadParams(num_rows=4, num_cols=4, mask_shape=shape, **kw))
    view = PreviewView()
    view.set_geometry(geo)  # must not raise on the rrect/circle outline kinds
    assert len(view._layer_items["fab"]) == 1
    assert len(view._layer_items["courtyard"]) == 1


def test_trackpad_export_matches_preview(qapp, tmp_path):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(2)
    win.panel.set_params(TRACKPAD_PRESETS["infineon"])
    win._rebuild()
    geo = win.preview.geometry_model

    fp_path, sym_path = win.export_to(tmp_path)
    assert fp_path.read_text() == footprint.trackpad_footprint_text(geo)
    assert sym_path.read_text() == symbol.trackpad_symbol_lib_text(geo)
    # One distinct pad number per Rx/Tx line, but many pads (multi-layer nets).
    assert fp_path.read_text().count("(pad ") > len(geo.nets)


# --------------------------------------------------------------------------- #
# widget switcher — mutual slider
# --------------------------------------------------------------------------- #
def test_mutual_slider_panel_defaults_build_valid_geometry(qapp):
    from captouch.gui.mutual_slider_panel import MutualSliderPanel

    panel = MutualSliderPanel()
    geo = build_mutual_slider(panel.params())  # must not raise
    assert len(geo.nets) == MutualSliderParams().num_pins


@pytest.mark.parametrize("key", sorted(MUTUAL_SLIDER_PRESETS))
def test_mutual_slider_preset_roundtrips_through_panel(qapp, key):
    from captouch.gui.mutual_slider_panel import MutualSliderPanel

    preset = MUTUAL_SLIDER_PRESETS[key]
    panel = MutualSliderPanel()
    panel.set_params(preset)
    got = panel.params()
    assert (got.num_segments, got.sense_rows) == (preset.num_segments, preset.sense_rows)
    assert got.diamond_pitch == pytest.approx(preset.diamond_pitch)
    assert got.diamond_gap == pytest.approx(preset.diamond_gap)
    build_mutual_slider(got)  # the loaded params still build


def test_switch_to_mutual_slider_builds_geometry(qapp):
    from captouch.gui.app import MainWindow
    from captouch.gui.mutual_slider_panel import MutualSliderPanel

    win = MainWindow()
    win._on_widget_changed(3)  # 0 Slider, 1 Wheel, 2 Trackpad, 3 Mutual slider
    assert isinstance(win.panel, MutualSliderPanel)
    assert isinstance(win.preview.geometry_model, MutualSliderGeometry)
    assert "mutual-cap slider" in win._status.text()


def test_mutual_slider_panel_length_driven_derives_count(qapp):
    from captouch.gui.mutual_slider_panel import MutualSliderPanel

    panel = MutualSliderPanel()
    assert not panel.length_driven.isChecked()
    assert panel.num_segments.isEnabled() and not panel.target_length.isEnabled()

    panel.length_driven.setChecked(True)
    panel.target_length.setValue(60.0)
    p = panel.params()
    assert abs(p.total_length - 60.0) <= p.diamond_pitch / 2 + 1e-9
    assert not panel.num_segments.isEnabled()  # read-only in size mode
    build_mutual_slider(p)
    # Loading a preset switches back to count-driven.
    panel.set_params(MUTUAL_SLIDER_PRESETS["microchip"])
    assert not panel.length_driven.isChecked()


def test_mutual_slider_preview_matches_geometry(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(3)
    win.panel.set_params(MUTUAL_SLIDER_PRESETS["dual"])
    win._rebuild()
    geo = win.preview.geometry_model
    for net in geo.nets:
        expected = [polygon_points(p) for p in net.bcu] + [polygon_points(p) for p in net.fcu]
        assert win.preview.net_polygon_points(net.pad_number) == expected


def test_mutual_slider_export_matches_preview(qapp, tmp_path):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(3)
    win.panel.set_params(MUTUAL_SLIDER_PRESETS["microchip"])
    win._rebuild()
    geo = win.preview.geometry_model

    fp_path, sym_path = win.export_to(tmp_path)
    assert fp_path.read_text() == footprint.mutual_slider_footprint_text(geo)
    assert sym_path.read_text() == symbol.mutual_slider_symbol_lib_text(geo)
    assert fp_path.read_text().count("(pad ") > len(geo.nets)  # multi-layer nets


def test_load_params_switches_to_mutual_slider(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # starts on the slider panel
    win.load_params(MutualSliderParams(num_segments=6, sense_rows=1, name="CT_MS"))
    assert isinstance(win._geo, MutualSliderGeometry)  # selector switched
    assert win.panel.params().num_segments == 6


# --------------------------------------------------------------------------- #
# fab-rule warning banner
# --------------------------------------------------------------------------- #
def test_fab_banner_hidden_for_clean_default(qapp):
    from captouch.gui.app import MainWindow

    # Default slider on the default profile clears every rule → no banner.
    # (isVisibleTo reflects the widget's own flag; the offscreen window is unshown.)
    win = MainWindow()
    assert win._fab_profile.currentText() == "default"
    assert not win._fab_banner.isVisibleTo(win)


def test_fab_banner_appears_when_profile_tightens(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(2)  # trackpad: its 0.15 mm annular trips OSH Park
    assert not win._fab_banner.isVisibleTo(win)  # still clean on the default profile

    win._fab_profile.setCurrentText("oshpark")  # fires currentIndexChanged → rebuild
    assert win._fab_banner.isVisibleTo(win)
    assert "annular ring" in win._fab_banner.text()

    win._fab_profile.setCurrentText("default")  # back to a profile it clears
    assert not win._fab_banner.isVisibleTo(win)


def test_fab_banner_hidden_on_invalid_geometry(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(2)
    win._fab_profile.setCurrentText("oshpark")
    assert win._fab_banner.isVisibleTo(win)

    # Drive the trackpad into an invalid state (gap too wide for the pitch).
    win.panel.set_params(TrackpadParams(diamond_pitch=2.0, diamond_gap=2.0))
    win._rebuild()
    assert win._status.text().startswith("⚠")  # error shown
    assert not win._fab_banner.isVisibleTo(win)  # banner cleared, no valid geometry


def test_load_params_switches_widget_and_loads(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # starts on the slider panel
    win.load_params(TrackpadParams(num_rows=4, num_cols=5, name="CT_T"))
    assert isinstance(win._geo, TrackpadGeometry)  # selector switched to trackpad
    got = win.panel.params()
    assert (got.num_rows, got.num_cols) == (4, 5)


def test_gui_save_load_params_round_trip(qapp):
    from captouch.gui.app import MainWindow
    from captouch.params import WheelParams, params_from_json, params_to_json

    win = MainWindow()
    win._on_widget_changed(1)  # wheel
    win.panel.set_params(WheelParams(num_segments=6, name="CT_W"))
    saved = params_to_json(win.panel.params())

    other = MainWindow()
    other.load_params(params_from_json(saved))
    assert isinstance(other._geo, WheelGeometry)
    assert other.panel.params().num_segments == 6


@pytest.mark.parametrize("ext", ["png", "svg"])
def test_preview_save_image(qapp, tmp_path, ext):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # __init__ renders the default slider geometry
    out = tmp_path / f"preview.{ext}"
    win.preview.save_image(str(out))
    assert out.exists() and out.stat().st_size > 0
    if ext == "svg":
        assert "<svg" in out.read_text(errors="ignore")


def test_fields_have_tooltips(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    assert panel.air_gap.toolTip()
    assert panel.num_segments.toolTip()
    assert panel.segment_width.toolTip()


def test_invalid_param_outlines_offending_field_and_clears(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # slider panel
    # W=20 with A=0.5, finger=8 violates W+2A=finger; the message names
    # segment_width + finger_diameter (both in valid spin-box range).
    win.panel.set_params(SliderParams(segment_width=20.0, air_gap=0.5, finger_diameter=8.0))
    win._rebuild()
    assert win._status.text().startswith("⚠")
    assert win.panel.segment_width.styleSheet()  # outlined
    assert win.panel.finger_diameter.styleSheet()
    assert not win.panel.air_gap.styleSheet()  # not named -> untouched

    win.panel.set_params(SliderParams())  # valid again
    win._rebuild()
    assert not win.panel.segment_width.styleSheet()  # cleared
    assert not win.panel.finger_diameter.styleSheet()


# --------------------------------------------------------------------------- #
# support copper (optional hatched ground + guard ring, default off)
# --------------------------------------------------------------------------- #
def test_support_off_by_default_emits_no_zone(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    p = panel.params()
    assert not p.ground_hatch and not p.guard_ring  # default off
    assert "(zone" not in footprint.widget_footprint_text(build_slider(p))


def test_support_spins_enable_gate_on_their_checkbox(qapp):
    from captouch.gui.panel import ParamPanel

    panel = ParamPanel()
    # Both features off → their spins are disabled.
    assert not panel.ground_margin.isEnabled()
    assert not panel.guard_width.isEnabled()

    panel.ground_hatch.setChecked(True)
    assert panel.ground_margin.isEnabled() and panel.ground_hatch_pitch.isEnabled()
    assert not panel.guard_width.isEnabled()  # guard still off

    panel.guard_ring.setChecked(True)
    assert panel.guard_width.isEnabled() and panel.guard_mask_open.isEnabled()


def test_toggling_ground_hatch_rebuilds_and_emits_zone(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # slider panel, support off
    assert "(zone" not in footprint.widget_footprint_text(win.preview.geometry_model)

    win.panel.ground_hatch.setChecked(True)  # emits changed → live rebuild
    geo = win.preview.geometry_model
    assert geo.params.ground_hatch
    assert "(zone" in footprint.widget_footprint_text(geo)  # export now has a zone
    assert win.preview._layer_items["ground"]  # preview gained the ground pour


def test_guard_ring_draws_guard_layer_and_zone(qapp):
    from captouch.gui.preview import PreviewView

    geo = build_slider(SliderParams(guard_ring=True))
    view = PreviewView()
    view.set_geometry(geo)
    assert view._layer_items["guard"]  # the F.Cu ring band is drawn
    assert "(zone" in footprint.widget_footprint_text(geo)


def test_trackpad_support_overlay_and_zone(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    win._on_widget_changed(2)  # trackpad
    win.panel.guard_ring.setChecked(True)
    geo = win.preview.geometry_model
    assert geo.params.guard_ring
    assert "(zone" in footprint.trackpad_footprint_text(geo)
    assert win.preview._layer_items["guard"]


def test_support_params_round_trip_through_panel(qapp):
    from captouch.gui.wheel_panel import WheelPanel
    from captouch.params import WheelParams

    panel = WheelPanel()
    src = WheelParams(
        ground_hatch=True,
        guard_ring=True,
        guard_mask_open=False,
        ground_margin=3.0,
        guard_gap=1.5,
    )
    panel.set_params(src)
    got = panel.params()
    assert got.ground_hatch and got.guard_ring and not got.guard_mask_open
    assert got.ground_margin == pytest.approx(3.0)
    assert got.guard_gap == pytest.approx(1.5)


def test_invalid_support_outlines_offending_field(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # slider panel
    # Hatch pitch must exceed line width; this violates it and names both fields.
    win.panel.set_params(
        SliderParams(ground_hatch=True, ground_hatch_width=0.5, ground_hatch_pitch=0.1)
    )
    win._rebuild()
    assert win._status.text().startswith("⚠")
    assert win.panel.ground_hatch_pitch.styleSheet()  # outlined
    assert win.panel.ground_hatch_width.styleSheet()
    assert not win.panel.ground_margin.styleSheet()  # not named → untouched

    win.panel.set_params(SliderParams())  # valid again
    win._rebuild()
    assert not win.panel.ground_hatch_pitch.styleSheet()  # cleared


# --------------------------------------------------------------------------- #
# sensitivity / filtering advisories (overlay inputs + banner/info line)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "factory_path",
    [
        "captouch.gui.panel.ParamPanel",
        "captouch.gui.wheel_panel.WheelPanel",
        "captouch.gui.trackpad_panel.TrackpadPanel",
    ],
)
def test_overlay_fields_flow_into_params(qapp, factory_path):
    import importlib

    mod_name, cls_name = factory_path.rsplit(".", 1)
    panel = getattr(importlib.import_module(mod_name), cls_name)()
    panel.overlay_thickness.setValue(1.5)
    panel.overlay_er.setValue(7.8)
    panel.board_thickness.setValue(0.8)
    p = panel.params()
    assert p.overlay_thickness == pytest.approx(1.5)
    assert p.overlay_er == pytest.approx(7.8)
    assert p.board_thickness == pytest.approx(0.8)


def test_series_r_advice_line_always_shown(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()  # default slider, no overlay
    win._rebuild()
    assert not win._advice_line.isHidden()  # isVisible() needs a shown window
    assert "560 Ω" in win._advice_line.text()


def test_undersized_overlay_raises_warning_banner(qapp):
    from captouch.gui.app import MainWindow

    win = MainWindow()
    # segment_height 8 mm < finger 8 + 2 x 2 mm overlay = 12 mm -> blocking advisory.
    win.panel.set_params(SliderParams(segment_height=8.0, overlay_thickness=2.0))
    win._rebuild()
    assert not win._fab_banner.isHidden()  # isVisible() needs a shown window
    assert "electrode vs overlay sizing" in win._fab_banner.text()
    # the full guidance is on the tooltip
    assert "Microchip AN2934" in win._fab_banner.toolTip()


def test_sensing_fields_load_from_params(qapp):
    from captouch.gui.trackpad_panel import TrackpadPanel

    panel = TrackpadPanel()
    panel.set_params(TrackpadParams(overlay_thickness=2.0, overlay_er=4.5, board_thickness=1.0))
    assert panel.overlay_thickness.value() == pytest.approx(2.0)
    assert panel.overlay_er.value() == pytest.approx(4.5)
    assert panel.board_thickness.value() == pytest.approx(1.0)
