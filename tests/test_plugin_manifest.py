"""The KiCad plugin bundle: a valid manifest and a working project-dir resolver.

KiCad validates ``plugin.json`` against its ``api/schemas/v1`` schema, so a
malformed manifest silently fails to load. These checks pin the manifest's required
shape, that every referenced file (entrypoint + icons) exists, and that the
testable half of the entrypoint — turning the open board's path into a project
directory, and the ``--project-dir`` dispatch — behaves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from captouch.kicad_plugin import plugin

BUNDLE = Path(__file__).resolve().parent.parent / "kicad-plugin"
MANIFEST = BUNDLE / "plugin.json"

# The scope vocabulary and required keys from KiCad's api.v1 schema (definitions
# Plugin/Action). Kept here so the test fails loudly if we drift from the schema.
_VALID_SCOPES = {"pcb", "schematic", "footprint", "symbol", "project_manager"}
_PLUGIN_REQUIRED = {"identifier", "name", "description", "runtime", "actions"}
_ACTION_REQUIRED = {"identifier", "name", "description", "entrypoint"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_valid_json_and_present():
    assert MANIFEST.exists()
    assert isinstance(json.loads(MANIFEST.read_text(encoding="utf-8")), dict)


def test_manifest_has_required_plugin_fields(manifest):
    assert _PLUGIN_REQUIRED <= set(manifest)
    assert manifest["runtime"]["type"] == "python"
    assert manifest["actions"], "at least one action"


def test_action_fields_and_scopes_are_valid(manifest):
    action = manifest["actions"][0]
    assert _ACTION_REQUIRED <= set(action)
    assert set(action["scopes"]) <= _VALID_SCOPES
    assert "pcb" in action["scopes"]  # this plugin places into the PCB


def test_referenced_files_exist(manifest):
    action = manifest["actions"][0]
    assert (BUNDLE / action["entrypoint"]).exists()
    for key in ("icons-light", "icons-dark"):
        for icon in action.get(key, []):
            assert (BUNDLE / icon).exists(), icon
            assert icon.endswith(".png")  # schema requires PNG icons


def test_entrypoint_shim_exists():
    assert (BUNDLE / "entry.py").exists()
    assert (BUNDLE / "requirements.txt").exists()


# --------------------------------------------------------------------------- #
# project-dir resolution
# --------------------------------------------------------------------------- #
def test_project_dir_from_directory(tmp_path):
    assert plugin.project_dir_from_path(tmp_path) == tmp_path.resolve()


def test_project_dir_from_board_file(tmp_path):
    board = tmp_path / "myboard.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    assert plugin.project_dir_from_path(board) == tmp_path.resolve()


def test_project_dir_from_kicad_pro_path(tmp_path):
    # A non-existent .kicad_pro path still resolves to its directory by suffix.
    assert plugin.project_dir_from_path(tmp_path / "proj.kicad_pro") == tmp_path.resolve()


class _FakeProject:
    def __init__(self, path):
        self.path = path


class _FakeBoard:
    def __init__(self, *, project_path=None, name=None):
        self._project_path = project_path
        self.name = name

    def get_project(self):
        return _FakeProject(self._project_path) if self._project_path else None


def test_board_project_dir_prefers_project_path(tmp_path):
    board = _FakeBoard(project_path=str(tmp_path / "p.kicad_pro"), name="/elsewhere/b.kicad_pcb")
    assert plugin._board_project_dir(board) == tmp_path.resolve()


def test_board_project_dir_falls_back_to_board_file(tmp_path):
    board = _FakeBoard(project_path=None, name=str(tmp_path / "b.kicad_pcb"))
    assert plugin._board_project_dir(board) == tmp_path.resolve()


def test_board_project_dir_raises_when_unknown():
    with pytest.raises(plugin.PluginError):
        plugin._board_project_dir(_FakeBoard())


# --------------------------------------------------------------------------- #
# main() dispatch (without a live KiCad or GUI loop)
# --------------------------------------------------------------------------- #
def test_main_with_project_dir_launches_gui(tmp_path, monkeypatch):
    captured = {}

    def fake_launch(project_dir):
        captured["dir"] = project_dir
        return 0

    monkeypatch.setattr(plugin, "_launch_gui", fake_launch)
    rc = plugin.main(["--project-dir", str(tmp_path)])
    assert rc == 0
    assert captured["dir"] == tmp_path.resolve()


def test_main_reports_connection_failure(monkeypatch, capsys):
    def boom():
        raise plugin.PluginError("no socket")

    monkeypatch.setattr(plugin, "connect_project_dir", boom)
    rc = plugin.main([])
    assert rc == 2
    assert "could not reach KiCad" in capsys.readouterr().err
