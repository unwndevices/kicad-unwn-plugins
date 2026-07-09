"""The KiCad-plugin library installer: byte-identity, merging, idempotent tables.

These exercise the headlessly-testable core of Phase 13 — writing the generated
footprint/symbol into a KiCad library and registering it. The "does it place in
the open board and pass DRC" acceptance is a manual in-KiCad step (no live KiCad in
CI); what we can pin here is that the *files* match the standalone output and that
registration is correct and repeatable.
"""

from __future__ import annotations

import pytest

from captouch import engine
from captouch.export import symbol
from captouch.kicad_plugin import library
from captouch.params import (
    KeypadParams,
    MutualSliderParams,
    SliderParams,
    TrackpadParams,
    WheelParams,
)
from kicad_core.sexpr import find, find_all, head, loads

_ALL_WIDGETS = [
    SliderParams(name="CT_Slider"),
    WheelParams(name="CT_Wheel"),
    TrackpadParams(name="CT_Trackpad"),
    MutualSliderParams(name="CT_MutualSlider"),
    KeypadParams(name="CT_Keypad"),
]


def _read(p):
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Byte-identity: the installed files match the standalone exporter output
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("params", _ALL_WIDGETS, ids=lambda p: type(p).__name__)
def test_installed_footprint_is_byte_identical(tmp_path, params):
    geo = engine.build_widget(params)
    fp_text, sym_text = engine.export_widget(geo)

    res = library.install_widget(params, project_dir=tmp_path)

    assert _read(res.fp_path) == fp_text
    # A single-symbol library written from scratch equals the standalone symbol lib.
    assert _read(res.sym_path) == sym_text


def test_footprint_lands_in_pretty_dir_with_kicad_mod_name(tmp_path):
    res = library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)
    assert res.fp_path == tmp_path / "captouch.pretty" / "CT_Slider.kicad_mod"
    assert res.sym_path == tmp_path / "captouch.kicad_sym"
    assert res.fp_id == "captouch:CT_Slider"


# --------------------------------------------------------------------------- #
# Symbol merge: several widgets share one .kicad_sym; re-install replaces in place
# --------------------------------------------------------------------------- #
def test_symbols_accumulate_in_one_library(tmp_path):
    library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)
    res = library.install_widget(WheelParams(name="CT_Wheel"), project_dir=tmp_path)

    lib = loads(_read(res.sym_path))
    names = [s[1] for s in find_all(lib, "symbol")]
    assert names == ["CT_Slider", "CT_Wheel"]


def test_reinstall_replaces_same_named_symbol_without_duplicating(tmp_path):
    library.install_widget(SliderParams(name="CT_Slider", num_segments=4), project_dir=tmp_path)
    library.install_widget(SliderParams(name="CT_Slider", num_segments=6), project_dir=tmp_path)

    lib = loads(_read(tmp_path / "captouch.kicad_sym"))
    symbols = [s for s in find_all(lib, "symbol") if s[1] == "CT_Slider"]
    assert len(symbols) == 1  # replaced, not appended


def test_merge_from_scratch_equals_widget_symbol_lib_text():
    geo = engine.build_widget(SliderParams(name="CT_Slider"))
    merged = symbol.merge_symbol_into_lib(symbol.widget_symbol(geo), None)
    assert merged == symbol.widget_symbol_lib_text(geo)


# --------------------------------------------------------------------------- #
# Library-table registration: project-local, ${KIPRJMOD}, idempotent
# --------------------------------------------------------------------------- #
def test_registers_project_local_libraries(tmp_path):
    res = library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)
    assert res.fp_registered and res.sym_registered

    assert "(version 7)" in _read(tmp_path / "fp-lib-table")
    fp_table = loads(_read(tmp_path / "fp-lib-table"))
    assert head(fp_table) == "fp_lib_table"
    entry = find_all(fp_table, "lib")[0]
    assert find(entry, "name")[1] == "captouch"
    assert find(entry, "type")[1] == "KiCad"
    assert find(entry, "uri")[1] == "${KIPRJMOD}/captouch.pretty"

    sym_table = loads(_read(tmp_path / "sym-lib-table"))
    assert find_all(sym_table, "lib")[0]
    assert find(find_all(sym_table, "lib")[0], "uri")[1] == "${KIPRJMOD}/captouch.kicad_sym"


def test_registration_is_idempotent(tmp_path):
    library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)
    fp_before = _read(tmp_path / "fp-lib-table")

    # A second install of a *different* widget into the same library must not add a
    # second table entry (the nickname is unchanged) nor report a re-registration.
    res2 = library.install_widget(WheelParams(name="CT_Wheel"), project_dir=tmp_path)
    assert not res2.fp_registered and not res2.sym_registered
    assert _read(tmp_path / "fp-lib-table") == fp_before

    fp_table = loads(_read(tmp_path / "fp-lib-table"))
    assert len(find_all(fp_table, "lib")) == 1


def test_registration_preserves_existing_unrelated_entries(tmp_path):
    (tmp_path / "fp-lib-table").write_text(
        "(fp_lib_table (version 7)\n"
        '  (lib (name "MyParts")(type "KiCad")(uri "${KIPRJMOD}/MyParts.pretty")'
        '(options "")(descr "hand-made"))\n)\n',
        encoding="utf-8",
    )
    library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)

    fp_table = loads(_read(tmp_path / "fp-lib-table"))
    names = {find(e, "name")[1] for e in find_all(fp_table, "lib")}
    assert names == {"MyParts", "captouch"}


def test_stale_uri_is_rewritten(tmp_path):
    library.install_widget(SliderParams(name="CT_Slider"), project_dir=tmp_path)
    # Re-register the same nickname at a new URI (e.g. user moved the library).
    target = library.make_target(
        nickname="captouch",
        fp_dir=tmp_path / "sub" / "captouch.pretty",
        sym_path=tmp_path / "sub" / "captouch.kicad_sym",
        project_dir=tmp_path,
        scope="project",
    )
    res = library.install(engine.build_widget(WheelParams(name="CT_Wheel")), target)
    assert res.fp_registered  # URI changed -> rewritten

    fp_table = loads(_read(tmp_path / "fp-lib-table"))
    entries = find_all(fp_table, "lib")
    assert len(entries) == 1
    assert find(entries[0], "uri")[1] == "${KIPRJMOD}/sub/captouch.pretty"


# --------------------------------------------------------------------------- #
# Configurable destinations: split footprint/symbol, global scope, absolute URI
# --------------------------------------------------------------------------- #
def test_footprint_and_symbol_can_target_different_directories(tmp_path):
    fp_dir = tmp_path / "mech" / "touch.pretty"
    sym_path = tmp_path / "elec" / "touch.kicad_sym"
    target = library.make_target(
        nickname="touch",
        fp_dir=fp_dir,
        sym_path=sym_path,
        project_dir=tmp_path,
        scope="project",
    )
    res = library.install(engine.build_widget(SliderParams(name="CT_Slider")), target)

    assert res.fp_path == fp_dir / "CT_Slider.kicad_mod"
    assert res.fp_path.exists()
    assert res.sym_path == sym_path
    assert res.sym_path.exists()
    assert res.fp_id == "touch:CT_Slider"


def test_global_scope_uses_absolute_uri_and_global_tables(tmp_path):
    global_dir = tmp_path / "kicad_cfg"
    global_dir.mkdir()
    lib_dir = tmp_path / "shared"
    target = library.make_target(
        nickname="captouch",
        fp_dir=lib_dir / "captouch.pretty",
        sym_path=lib_dir / "captouch.kicad_sym",
        scope="global",
        global_dir=global_dir,
    )
    res = library.install(engine.build_widget(SliderParams(name="CT_Slider")), target)

    assert res.fp_table == global_dir / "fp-lib-table"
    fp_table = loads(_read(global_dir / "fp-lib-table"))
    uri = find(find_all(fp_table, "lib")[0], "uri")[1]
    assert uri == str((lib_dir / "captouch.pretty").resolve())  # absolute, no ${KIPRJMOD}


def test_make_target_rejects_unknown_scope(tmp_path):
    with pytest.raises(library.LibraryError):
        library.make_target(
            nickname="x",
            fp_dir=tmp_path / "a.pretty",
            sym_path=tmp_path / "a.kicad_sym",
            scope="bogus",
            project_dir=tmp_path,
        )


def test_install_without_target_or_project_dir_errors():
    geo = engine.build_widget(SliderParams(name="CT_Slider"))
    with pytest.raises(library.LibraryError):
        library.install(geo)
