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


def test_requirements_pinned_to_tag(artifacts):
    reqs = _read_in_zip(artifacts["archive"], "plugins/requirements.txt").decode()
    assert f"archive/refs/tags/{TAG}.zip" in reqs
    assert "heads/main.zip" not in reqs


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


def test_pin_requirements_rejects_missing_marker():
    with pytest.raises(ValueError):
        build_pcm._pin_requirements("kicad-python>=0.5\n", TAG)
