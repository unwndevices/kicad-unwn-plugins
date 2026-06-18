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
        diamond_pitch=None,
        diamond_gap=None,
        bridge_width=None,
        via_drill=None,
        via_diameter=None,
        mask_shape=None,
        clip_mode=None,
        corner_radius=None,
        radius=None,
    )
    for prof in ("default", "jlcpcb", "oshpark"):
        p = _trackpad_params_from_args(Namespace(fab_profile=prof, **unset))
        assert p.min_feature == FAB_PROFILES[prof].min_track_width
