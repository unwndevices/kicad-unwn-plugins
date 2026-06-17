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
from captouch.geometry import WheelGeometry, build_slider
from captouch.params import SLIDER_PRESETS, WHEEL_PRESETS, SliderParams

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
