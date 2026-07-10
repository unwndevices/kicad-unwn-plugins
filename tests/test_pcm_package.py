"""The PCM distribution build: a schema-valid package and repository index.

KiCad silently rejects a PCM package whose ``metadata.json`` violates the schema, so
these tests drive ``packaging/build_pcm.py`` end-to-end and assert the things that
are easy to get wrong and impossible to see fail from inside KiCad:

* the archive layout (``metadata.json`` at the root, the IPC ``plugin.json`` directly
  under ``plugins/``, a 64x64 ``resources/icon.png``);
* the spec rule that ``download_*`` keys appear only in the repository's
  ``packages.json``, never in the archive's own ``metadata.json``;
* that the bundled ``requirements.txt`` is pinned to the release tag (not ``main``);
* that the advertised ``download_sha256`` actually matches the archive bytes;
* that every emitted JSON validates against the vendored PCM v2 schema.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packaging"))

# Skip cleanly where jsonschema isn't installed (it's in the dev extra); the build
# itself validates, so without it there is nothing meaningful to assert.
pytest.importorskip("jsonschema")

import build_pcm  # noqa: E402  (after the sys.path tweak)

VERSION = "0.1.0"
TAG = "v0.1.0"
PLUGIN_DIR = REPO_ROOT / "plugins" / "captouch"


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("pcm")
    return build_pcm.build(
        version=VERSION,
        tag=TAG,
        repo_slug="unwndevices/kicad-unwn-plugins",
        pages_url="https://unwndevices.github.io/kicad-unwn-plugins",
        plugin_dir=PLUGIN_DIR,
        outdir=out,
        timestamp=1_700_000_000,
    )


@pytest.fixture(scope="module")
def schema() -> dict:
    return build_pcm._load_schema()


def _archive_names(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def _read_in_zip(archive: Path, name: str) -> bytes:
    with zipfile.ZipFile(archive) as zf:
        return zf.read(name)


def test_archive_layout(artifacts):
    names = set(_archive_names(artifacts["archive"]))
    assert "metadata.json" in names
    assert "resources/icon.png" in names
    # The IPC manifest sits directly under plugins/, not in a second-level subdir.
    assert "plugins/plugin.json" in names
    assert "plugins/entry.py" in names
    assert "plugins/requirements.txt" in names
    assert not any(n.startswith("plugins/") and n.count("/") > 1 for n in names)


def test_archive_metadata_is_schema_valid_without_download_keys(artifacts, schema):
    meta = json.loads(_read_in_zip(artifacts["archive"], "metadata.json"))
    build_pcm._validate(meta, "Package", schema)  # raises if invalid
    assert meta["identifier"] == build_pcm.IDENTIFIER
    assert meta["type"] == "plugin"
    ver = meta["versions"][0]
    assert ver["runtime"] == "ipc"
    assert ver["status"] == "stable"
    # The spec forbids download_* inside the archive's own metadata.
    assert not any(k.startswith("download_") for k in ver)
    assert "install_size" not in ver


def test_requirements_pin_the_tool_wheel_to_version(artifacts):
    reqs = _read_in_zip(artifacts["archive"], "plugins/requirements.txt").decode()
    # The tool's own distribution is pinned to the released version as a PyPI wheel;
    # KiCad installs the venv with --only-binary :all:, so no source archives allowed.
    assert f"kicad-captouch[gui]=={VERSION}" in reqs
    assert "archive/refs" not in reqs and ".zip" not in reqs
    # Third-party deps are left untouched (not pinned by the build).
    assert "kicad-python>=0.5" in reqs


def test_packages_json_has_matching_download_metadata(artifacts, schema):
    packages = json.loads(artifacts["packages_json"].read_text())
    build_pcm._validate(packages, "PackageArray", schema)
    ver = packages["packages"][0]["versions"][0]
    assert ver["download_sha256"] == artifacts["download_sha256"]
    assert ver["download_size"] == artifacts["download_size"]
    assert ver["install_size"] == artifacts["install_size"]
    assert ver["download_url"].endswith(f"/releases/download/{TAG}/{artifacts['archive'].name}")


def test_repository_json_is_schema_valid(artifacts, schema):
    repo = json.loads(artifacts["repository_json"].read_text())
    build_pcm._validate(repo, "Repository", schema)
    assert repo["schema_version"] == 2
    assert repo["packages"]["url"].endswith("/packages.json")
    assert repo["resources"]["url"].endswith("/resources.zip")
    assert repo["packages"]["sha256"] == build_pcm._sha256(artifacts["packages_json"])
    assert repo["resources"]["sha256"] == build_pcm._sha256(artifacts["resources_zip"])


def test_build_is_deterministic(tmp_path):
    def once(sub: str) -> str:
        res = build_pcm.build(
            version=VERSION,
            tag=TAG,
            repo_slug="unwndevices/kicad-unwn-plugins",
            pages_url="https://unwndevices.github.io/kicad-unwn-plugins",
            plugin_dir=PLUGIN_DIR,
            outdir=tmp_path / sub,
            timestamp=1_700_000_000,
        )
        return res["download_sha256"]

    assert once("a") == once("b")


def test_pin_requirements_appends_version_and_keeps_extras():
    out = build_pcm._pin_requirements(
        "kicad-python==0.7.1\nkicad-returnpath\n", "kicad-returnpath", "1.2.3"
    )
    assert "kicad-returnpath==1.2.3" in out
    assert "kicad-python==0.7.1" in out  # third-party line untouched


def test_pin_requirements_preserves_extras_group():
    out = build_pcm._pin_requirements("kicad-captouch[gui]\n", "kicad-captouch", "0.4.0")
    assert "kicad-captouch[gui]==0.4.0" in out


def test_pin_requirements_rejects_missing_package_line():
    with pytest.raises(ValueError):
        build_pcm._pin_requirements("kicad-python>=0.5\n", "kicad-returnpath", "0.1.0")


# ---- per-tool generalization (#15) -----------------------------------------


def test_tool_registry_lists_captouch():
    """captouch is registered and its identifier is the (unchanged) one KiCad keys on."""
    spec = build_pcm.TOOLS["captouch"]
    assert spec.identifier == build_pcm.IDENTIFIER
    assert spec.identifier == "com.github.unwndevices.kicad-captouch"
    assert spec.package_name == "kicad-captouch"


def test_build_defaults_to_captouch_and_is_byte_identical(artifacts, tmp_path):
    """Building with no explicit tool must reproduce the captouch archive verbatim."""
    default = build_pcm.build(
        version=VERSION,
        tag=TAG,
        repo_slug="unwndevices/kicad-unwn-plugins",
        pages_url="https://unwndevices.github.io/kicad-unwn-plugins",
        plugin_dir=PLUGIN_DIR,
        outdir=tmp_path / "default",
        timestamp=1_700_000_000,
    )
    assert default["archive"].name == "kicad-captouch-pcm-0.1.0.zip"
    assert default["download_sha256"] == artifacts["download_sha256"]


def test_build_honours_an_arbitrary_tool_spec(tmp_path):
    """A different ToolSpec drives the archive name, identifier and resources key."""
    spec = build_pcm.ToolSpec(
        name="demo",
        identifier="com.github.unwndevices.kicad-demo",
        display_name="Demo Tool",
        description="short",
        description_full="full",
        plugin_subdir="demo",
        package_name="kicad-demo",
    )
    # Stage a bundle whose requirements.txt names this tool's own package, so the
    # build's version pin has a matching line to rewrite.
    plugin_dir = tmp_path / "bundle"
    plugin_dir.mkdir()
    for f in PLUGIN_DIR.iterdir():
        if f.name != "requirements.txt":
            (plugin_dir / f.name).write_bytes(f.read_bytes())
    (plugin_dir / "requirements.txt").write_text("kicad-python>=0.5\nkicad-demo\n")
    res = build_pcm.build(
        version=VERSION,
        tag="demo-v0.1.0",
        repo_slug="unwndevices/kicad-unwn-plugins",
        pages_url="https://unwndevices.github.io/kicad-unwn-plugins",
        plugin_dir=plugin_dir,
        outdir=tmp_path / "out",
        timestamp=1_700_000_000,
        tool=spec,
    )
    assert res["archive"].name == "kicad-demo-pcm-0.1.0.zip"
    meta = json.loads(_read_in_zip(res["archive"], "metadata.json"))
    assert meta["identifier"] == "com.github.unwndevices.kicad-demo"
    assert meta["name"] == "Demo Tool"
    # resources.zip keys each icon directory by the tool's identifier
    with zipfile.ZipFile(res["resources_zip"]) as zf:
        assert "com.github.unwndevices.kicad-demo/icon.png" in zf.namelist()


def test_cli_tool_flag_builds_selected_tool(tmp_path):
    # --no-merge keeps the build offline: without it main() fetches the live index.
    rc = build_pcm.main(
        ["--version", VERSION, "--tool", "captouch", "--outdir", str(tmp_path), "--no-merge"]
    )
    assert rc == 0
    assert (tmp_path / "kicad-captouch-pcm-0.1.0.zip").exists()


# ---- shared-index merge (#15) ----------------------------------------------


def _other_tool_entry() -> dict:
    """A stand-in for a tool already published in the shared index."""
    return {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": "Other Tool",
        "description": "an already-published tool",
        "description_full": "an already-published tool",
        "identifier": "com.github.unwndevices.kicad-other",
        "type": "plugin",
        "author": {"name": build_pcm.MAINTAINER, "contact": {"web": "https://example.invalid"}},
        "license": "GPL-3.0-or-later",
        "resources": {"GitHub": "https://example.invalid"},
        "versions": [
            {
                "version": "9.9.9",
                "status": "stable",
                "kicad_version": "9.0",
                "runtime": "ipc",
                "download_url": "https://example.invalid/other.zip",
                "download_sha256": "0" * 64,
                "download_size": 1,
                "install_size": 1,
            }
        ],
    }


def test_merge_upserts_and_sorts():
    other = _other_tool_entry()
    entry = {"identifier": "com.github.unwndevices.kicad-captouch", "name": "cap"}
    merged = build_pcm._merge_packages([other], entry)
    idents = [p["identifier"] for p in merged]
    assert idents == sorted(idents)
    assert other in merged and entry in merged


def test_merge_replaces_same_identifier():
    old = {
        "identifier": "com.github.unwndevices.kicad-captouch",
        "versions": [{"version": "0.0.1"}],
    }
    new = {
        "identifier": "com.github.unwndevices.kicad-captouch",
        "versions": [{"version": "0.2.0"}],
    }
    merged = build_pcm._merge_packages([old], new)
    assert merged == [new]  # the bump replaces the prior entry, no duplicate


def test_build_carries_other_tools_into_the_index(tmp_path, schema):
    """Releasing captouch must not drop a tool already in the shared index."""
    other = _other_tool_entry()
    res = build_pcm.build(
        version=VERSION,
        tag=TAG,
        repo_slug="unwndevices/kicad-unwn-plugins",
        pages_url="https://unwndevices.github.io/kicad-unwn-plugins",
        plugin_dir=PLUGIN_DIR,
        outdir=tmp_path,
        timestamp=1_700_000_000,
        existing_packages=[other],
    )
    packages = json.loads(res["packages_json"].read_text())
    build_pcm._validate(packages, "PackageArray", schema)
    idents = {p["identifier"] for p in packages["packages"]}
    assert idents == {other["identifier"], build_pcm.IDENTIFIER}
    # resources.zip carries an icon for every tool in the merged index.
    with zipfile.ZipFile(res["resources_zip"]) as zf:
        names = set(zf.namelist())
    assert f"{other['identifier']}/icon.png" in names
    assert f"{build_pcm.IDENTIFIER}/icon.png" in names


def test_fetch_published_packages_treats_404_as_empty(monkeypatch):
    import urllib.error

    def boom(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(build_pcm.urllib.request, "urlopen", boom)
    assert build_pcm._fetch_published_packages("https://example.invalid/packages.json") == []


def test_fetch_published_packages_reraises_other_errors(monkeypatch):
    import urllib.error

    def boom(url):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)

    monkeypatch.setattr(build_pcm.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        build_pcm._fetch_published_packages("https://example.invalid/packages.json")
