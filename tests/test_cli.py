"""CLI behaviour, focused on the fab-rule guard wiring (warn / --strict)."""

from __future__ import annotations

import pytest

from captouch import __version__
from captouch.cli import main


def test_version_flag_prints_version_and_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_gui_check_constructs_and_exits(capsys):
    pytest.importorskip("PySide6")
    rc = main(["gui", "--check"])
    assert rc == 0
    assert "gui ok" in capsys.readouterr().out


def test_slider_default_writes_files_and_exits_zero(tmp_path):
    rc = main(["slider", "--out", str(tmp_path), "--name", "S"])
    assert rc == 0
    assert (tmp_path / "S.kicad_mod").exists()
    assert (tmp_path / "S.kicad_sym").exists()


def test_slider_length_sizes_segment_count(tmp_path, capsys):
    rc = main(["slider", "--out", str(tmp_path), "--name", "S", "--length", "80"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sized from length" in out and "target 80.00 mm" in out
    assert (tmp_path / "S.kicad_mod").exists()


def test_slider_length_conflicts_with_num_segments(tmp_path, capsys):
    rc = main(["slider", "--out", str(tmp_path), "--length", "80", "--num-segments", "5"])
    assert rc == 2
    assert "not both" in capsys.readouterr().out


def test_mutual_slider_default_writes_files_and_exits_zero(tmp_path, capsys):
    rc = main(["mutual-slider", "--out", str(tmp_path), "--name", "MS"])
    assert rc == 0
    assert (tmp_path / "MS.kicad_mod").exists()
    assert (tmp_path / "MS.kicad_sym").exists()
    out = capsys.readouterr().out
    assert "mutual-cap slider" in out and "2 kΩ series resistor" in out  # mutual series-R


def test_mutual_slider_length_sizes_node_count(tmp_path, capsys):
    rc = main(["mutual-slider", "--out", str(tmp_path), "--name", "MS", "--length", "60"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sized from length" in out and "target 60.00 mm" in out
    assert (tmp_path / "MS.kicad_mod").exists()


def test_mutual_slider_length_conflicts_with_num_segments(tmp_path, capsys):
    rc = main(["mutual-slider", "--out", str(tmp_path), "--length", "60", "--num-segments", "5"])
    assert rc == 2
    assert "not both" in capsys.readouterr().out


def test_mutual_slider_save_and_from_params_round_trip(tmp_path):
    out, regen, pj = tmp_path / "a", tmp_path / "b", tmp_path / "p.json"
    rc = main(
        [
            "mutual-slider",
            "--out",
            str(out),
            "--name",
            "MS",
            "--sense-rows",
            "2",
            "--save-params",
            str(pj),
        ]
    )
    assert rc == 0 and pj.exists()
    assert main(["from-params", str(pj), "--out", str(regen)]) == 0
    # Regenerating from the saved params reproduces the files byte-for-byte.
    assert (out / "MS.kicad_mod").read_text() == (regen / "MS.kicad_mod").read_text()
    assert (out / "MS.kicad_sym").read_text() == (regen / "MS.kicad_sym").read_text()


def test_wheel_outer_diameter_sizes_segment_count(tmp_path, capsys):
    rc = main(["wheel", "--out", str(tmp_path), "--name", "W", "--outer-diameter", "50"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sized from diameter" in out and "target 50.00 mm" in out
    assert (tmp_path / "W.kicad_mod").exists()


def test_wheel_outer_diameter_conflicts_with_num_segments(tmp_path, capsys):
    rc = main(["wheel", "--out", str(tmp_path), "--outer-diameter", "50", "--num-segments", "5"])
    assert rc == 2
    assert "not both" in capsys.readouterr().out


def test_wheel_spiral_shape_writes_both_files(tmp_path, capsys):
    rc = main(
        ["wheel", "--out", str(tmp_path), "--name", "SW", "--shape", "spiral", "--spiral-angle", "45"]
    )
    assert rc == 0
    assert "spiral wheel" in capsys.readouterr().out
    assert (tmp_path / "SW.kicad_mod").exists()
    assert (tmp_path / "SW.kicad_sym").exists()


def test_save_params_and_from_params_round_trip(tmp_path):
    out, regen, pj = tmp_path / "a", tmp_path / "b", tmp_path / "p.json"
    rc = main(
        [
            "slider",
            "--out",
            str(out),
            "--name",
            "S",
            "--num-segments",
            "5",
            "--save-params",
            str(pj),
        ]
    )
    assert rc == 0
    assert pj.exists()
    assert main(["from-params", str(pj), "--out", str(regen)]) == 0
    # Regenerating from the saved params reproduces the files byte-for-byte.
    assert (out / "S.kicad_mod").read_text() == (regen / "S.kicad_mod").read_text()
    assert (out / "S.kicad_sym").read_text() == (regen / "S.kicad_sym").read_text()


def test_from_params_dispatches_by_widget(tmp_path):
    pj = tmp_path / "t.json"
    main(["trackpad", "--out", str(tmp_path / "a"), "--name", "T", "--save-params", str(pj)])
    assert main(["from-params", str(pj), "--out", str(tmp_path / "b")]) == 0
    assert (tmp_path / "b" / "T.kicad_mod").exists()
    assert (tmp_path / "b" / "T.kicad_sym").exists()


def _zones(text):
    from captouch import sexpr

    return len(sexpr.find_all(sexpr.loads(text), "zone"))


def test_support_flags_emit_zones_and_report(tmp_path, capsys):
    rc = main(["slider", "--out", str(tmp_path), "--name", "S", "--ground-hatch", "--guard-ring"])
    assert rc == 0
    assert _zones((tmp_path / "S.kicad_mod").read_text()) == 2  # ground + guard
    out = capsys.readouterr().out
    assert "support copper" in out and "GND pin" in out


def test_support_off_by_default_no_zones(tmp_path):
    main(["wheel", "--out", str(tmp_path), "--name", "W"])
    assert _zones((tmp_path / "W.kicad_mod").read_text()) == 0


def test_support_flags_round_trip_through_params(tmp_path):
    # The support fields survive --save-params / from-params (JSON carries them).
    pj = tmp_path / "p.json"
    main(
        [
            "slider",
            "--out",
            str(tmp_path / "a"),
            "--name",
            "S",
            "--guard-ring",
            "--save-params",
            str(pj),
        ]
    )
    assert main(["from-params", str(pj), "--out", str(tmp_path / "b")]) == 0
    assert (tmp_path / "a" / "S.kicad_mod").read_text() == (
        tmp_path / "b" / "S.kicad_mod"
    ).read_text()
    assert _zones((tmp_path / "b" / "S.kicad_mod").read_text()) == 1


def test_from_params_bad_widget_errors(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"widget": "octopad", "params": {}}')
    assert main(["from-params", str(bad), "--out", str(tmp_path)]) == 2
    assert "error" in capsys.readouterr().out


def test_list_fab_profiles_lists_and_exits_zero(capsys):
    rc = main(["trackpad", "--list-fab-profiles"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "default" in out and "jlcpcb" in out and "oshpark" in out


def test_trackpad_warns_but_still_generates_under_loose_profile(tmp_path, capsys):
    # The default trackpad's 0.15 mm annular ring is below OSH Park's floor, but
    # without --strict the files are still written and a warning is printed.
    rc = main(["trackpad", "--out", str(tmp_path), "--name", "T", "--fab-profile", "oshpark"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "warning:" in out
    assert "annular ring" in out
    assert (tmp_path / "T.kicad_mod").exists()


def test_strict_blocks_generation_and_writes_nothing(tmp_path, capsys):
    rc = main(
        ["trackpad", "--out", str(tmp_path), "--name", "T", "--fab-profile", "oshpark", "--strict"]
    )
    out = capsys.readouterr().out
    assert rc == 3
    assert "error:" in out and "refusing to generate" in out
    assert not (tmp_path / "T.kicad_mod").exists()
    assert not (tmp_path / "T.kicad_sym").exists()


def test_strict_passes_when_geometry_clears_the_profile(tmp_path):
    # Default profile: the stock trackpad clears every rule, so --strict succeeds.
    rc = main(["trackpad", "--out", str(tmp_path), "--name", "T", "--strict"])
    assert rc == 0
    assert (tmp_path / "T.kicad_mod").exists()


# -- mask-shape flags ------------------------------------------------------- #
def test_trackpad_circle_mask_writes_circle_outline(tmp_path):
    rc = main(
        [
            "trackpad",
            "--out",
            str(tmp_path),
            "--name",
            "T",
            "--num-rows",
            "4",
            "--num-cols",
            "4",
            "--mask-shape",
            "circle",
        ]
    )
    assert rc == 0
    assert "(fp_circle" in (tmp_path / "T.kicad_mod").read_text()  # F.Fab circle


def test_trackpad_rrect_mask_writes_poly_outline(tmp_path):
    rc = main(
        [
            "trackpad",
            "--out",
            str(tmp_path),
            "--name",
            "T",
            "--mask-shape",
            "rrect",
            "--corner-radius",
            "2",
        ]
    )
    assert rc == 0
    assert "(fp_poly" in (tmp_path / "T.kicad_mod").read_text()  # F.Fab polyline


def test_trackpad_conform_circle_reports_partial_channels(tmp_path, capsys):
    rc = main(
        [
            "trackpad",
            "--out",
            str(tmp_path),
            "--name",
            "T",
            "--num-rows",
            "7",
            "--num-cols",
            "7",
            "--mask-shape",
            "circle",
            "--clip-mode",
            "conform",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "partial channel" in out
    assert "Rx1" in out and "disabling" in out
    assert (tmp_path / "T.kicad_mod").exists()


def test_trackpad_panel_size_derives_counts(tmp_path, capsys):
    # 52x38 @ 5 mm -> round to 10x8 diamonds; outline held at the requested size.
    rc = main(
        [
            "trackpad",
            "--out",
            str(tmp_path),
            "--name",
            "T",
            "--panel-width",
            "52",
            "--panel-height",
            "38",
            "--diamond-pitch",
            "5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "10x8 diamonds" in out  # num_cols x num_rows, derived from the panel
    assert "outline 52.00 x 38.00 mm" in out
    assert "sized from panel" in out
    assert (tmp_path / "T.kicad_mod").exists()


def test_trackpad_panel_requires_both_dims(tmp_path, capsys):
    rc = main(["trackpad", "--out", str(tmp_path), "--name", "T", "--panel-width", "50"])
    assert rc == 2
    assert "must be given together" in capsys.readouterr().out


def test_trackpad_panel_conflicts_with_counts(tmp_path, capsys):
    rc = main(
        [
            "trackpad",
            "--out",
            str(tmp_path),
            "--name",
            "T",
            "--panel-width",
            "50",
            "--panel-height",
            "50",
            "--num-cols",
            "5",
        ]
    )
    assert rc == 2
    assert "not both" in capsys.readouterr().out


def test_trackpad_corner_radius_without_rrect_errors(tmp_path, capsys):
    rc = main(["trackpad", "--out", str(tmp_path), "--name", "T", "--corner-radius", "2"])
    assert rc == 2  # SliderError path; nothing written
    assert not (tmp_path / "T.kicad_mod").exists()
    assert "corner_radius" in capsys.readouterr().out


def test_trackpad_min_feature_tracks_fab_profile():
    from argparse import Namespace

    from captouch.cli import _trackpad_params_from_args
    from captouch.params import FAB_PROFILES

    unset = dict(
        preset=None,
        name=None,
        num_rows=None,
        num_cols=None,
        panel_width=None,
        panel_height=None,
        diamond_pitch=None,
        diamond_gap=None,
        bridge_width=None,
        via_drill=None,
        via_diameter=None,
        mask_shape=None,
        clip_mode=None,
        corner_radius=None,
        radius=None,
        # support-copper flags (all off / unset)
        ground_hatch=False,
        guard_ring=False,
        guard_no_mask_open=False,
        ground_margin=None,
        ground_hatch_width=None,
        ground_hatch_pitch=None,
        guard_width=None,
        guard_gap=None,
        guard_break=None,
        # overlay / sensitivity flags (all unset)
        overlay_thickness=None,
        overlay_er=None,
        board_thickness=None,
    )
    for prof in ("default", "jlcpcb", "oshpark"):
        p = _trackpad_params_from_args(Namespace(fab_profile=prof, **unset))
        assert p.min_feature == FAB_PROFILES[prof].min_track_width


# --------------------------------------------------------------------------- #
# sensitivity / filtering advisories
# --------------------------------------------------------------------------- #
def test_series_r_advisory_always_in_output(tmp_path, capsys):
    rc = main(["slider", "--out", str(tmp_path), "--name", "S"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "560 Ω series resistor" in out  # self-cap recommendation


def test_overlay_thickness_flag_triggers_sizing_advisory(tmp_path, capsys):
    rc = main(
        [
            "slider",
            "--out",
            str(tmp_path),
            "--name",
            "S",
            "--segment-height",
            "8",
            "--overlay-thickness",
            "2",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0  # advisory, not a block
    assert "below the finger + 2·overlay minimum" in out
    assert (tmp_path / "S.kicad_mod").exists()


def test_strict_blocks_on_blocking_advisory_and_writes_nothing(tmp_path, capsys):
    rc = main(
        [
            "slider",
            "--out",
            str(tmp_path),
            "--name",
            "S",
            "--segment-height",
            "8",
            "--overlay-thickness",
            "2",
            "--strict",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 3
    assert "error:" in out and "refusing to generate" in out
    assert not (tmp_path / "S.kicad_mod").exists()


def test_strict_passes_when_advisories_are_informational_only(tmp_path):
    # No overlay + a well-sized default slider: only the (non-blocking) series-R
    # advisory, so --strict still succeeds.
    rc = main(["slider", "--out", str(tmp_path), "--name", "S", "--strict"])
    assert rc == 0
    assert (tmp_path / "S.kicad_mod").exists()


def test_trackpad_overlay_too_thick_blocks_under_strict(tmp_path, capsys):
    rc = main(
        ["trackpad", "--out", str(tmp_path), "--name", "T", "--overlay-thickness", "5", "--strict"]
    )
    out = capsys.readouterr().out
    assert rc == 3
    assert "trackpad maximum" in out
    assert not (tmp_path / "T.kicad_mod").exists()


# --------------------------------------------------------------------------- #
# keypad
# --------------------------------------------------------------------------- #
def test_keypad_default_writes_files_and_exits_zero(tmp_path, capsys):
    rc = main(["keypad", "--out", str(tmp_path), "--name", "KP"])
    assert rc == 0
    assert (tmp_path / "KP.kicad_mod").exists()
    assert (tmp_path / "KP.kicad_sym").exists()
    out = capsys.readouterr().out
    assert "keypad" in out and "560 Ω series resistor" in out  # self-cap series-R


def test_keypad_shape_and_size_flags(tmp_path, capsys):
    rc = main(
        [
            "keypad",
            "--out",
            str(tmp_path),
            "--name",
            "KP",
            "--num-rows",
            "2",
            "--num-cols",
            "4",
            "--button-shape",
            "circle",
            "--button-size",
            "12",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "circle keypad: 2x4 buttons (8 keys, 8 pins)" in out


def test_keypad_list_presets(capsys):
    rc = main(["keypad", "--list-presets"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "numeric" in out and "round" in out and "compact" in out


def test_keypad_save_and_from_params_round_trip(tmp_path):
    pj = tmp_path / "kp.json"
    main(["keypad", "--out", str(tmp_path / "a"), "--preset", "round", "--save-params", str(pj)])
    assert '"widget": "keypad"' in pj.read_text()
    assert main(["from-params", str(pj), "--out", str(tmp_path / "b")]) == 0
    a = tmp_path / "a" / "CT_Keypad_Round.kicad_mod"
    b = tmp_path / "b" / "CT_Keypad_Round.kicad_mod"
    assert a.read_text() == b.read_text()  # byte-identical round-trip


def test_keypad_support_flags_emit_zones(tmp_path):
    rc = main(["keypad", "--out", str(tmp_path), "--name", "KP", "--ground-hatch", "--guard-ring"])
    assert rc == 0
    assert _zones((tmp_path / "KP.kicad_mod").read_text()) == 2  # ground + guard


def test_keypad_strict_blocks_on_overlay_sizing(tmp_path, capsys):
    # A 5 mm button under a 2 mm overlay is below the 3×overlay minimum -> blocks.
    rc = main(
        [
            "keypad",
            "--out",
            str(tmp_path),
            "--name",
            "KP",
            "--button-size",
            "5",
            "--overlay-thickness",
            "2",
            "--strict",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 3
    assert "refusing to generate" in out
    assert not (tmp_path / "KP.kicad_mod").exists()


# --------------------------------------------------------------------------- #
# --dxf flag (mechanical / CAD handoff)
# --------------------------------------------------------------------------- #
def test_slider_dxf_flag_writes_dxf(tmp_path, capsys):
    rc = main(["slider", "--out", str(tmp_path), "--name", "S", "--dxf"])
    assert rc == 0
    dxf_path = tmp_path / "S.dxf"
    assert dxf_path.exists()
    assert "wrote " in capsys.readouterr().out
    text = dxf_path.read_text()
    assert text.startswith("0\nSECTION\n") and text.rstrip().endswith("EOF")


def test_no_dxf_flag_writes_no_dxf(tmp_path):
    rc = main(["wheel", "--out", str(tmp_path), "--name", "W"])
    assert rc == 0
    assert not (tmp_path / "W.dxf").exists()


def test_keypad_dxf_flag_writes_dxf(tmp_path):
    rc = main(["keypad", "--out", str(tmp_path), "--name", "KP", "--dxf"])
    assert rc == 0
    assert (tmp_path / "KP.dxf").exists()


def test_from_params_dxf_flag_writes_dxf(tmp_path):
    pj = tmp_path / "p.json"
    assert main(["trackpad", "--out", str(tmp_path), "--name", "T", "--save-params", str(pj)]) == 0
    regen = tmp_path / "regen"
    assert main(["from-params", str(pj), "--out", str(regen), "--dxf"]) == 0
    assert (regen / "T.dxf").exists()
