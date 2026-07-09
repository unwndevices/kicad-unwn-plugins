#!/usr/bin/env python3
"""Build the KiCad PCM (Plugin and Content Manager) distribution artifacts.

From the single-source plugin bundle in ``plugins/captouch/`` this produces:

* ``<outdir>/<archive>.zip``         the installable PCM package (``metadata.json`` +
                                     ``plugins/`` + ``resources/icon.png``) — what a
                                     user picks via *Manage Plugins → Install from File*.
* ``<outdir>/repo/packages.json``    the repository package index (carries ``download_*``).
* ``<outdir>/repo/repository.json``  the descriptor a user adds as a PCM repository URL
                                     to get install + automatic update notifications.
* ``<outdir>/repo/resources.zip``    per-package icons for the PCM browse UI.

Three things make the output correct rather than merely plausible:

* the package archive omits the ``download_*`` keys — per the PCM spec they belong
  *only* in the repository copy, never in the archive's own ``metadata.json``;
* the bundled ``requirements.txt`` is pinned to the released tag, so the plugin's
  managed venv installs the exact released ``kicad-captouch`` (not a moving ``main``);
* every emitted JSON is validated against the vendored KiCad PCM v2 schema before
  it is written, so an invalid package fails the build instead of failing silently
  inside KiCad.

The zip is built deterministically (sorted entries, fixed timestamps) so the same
inputs yield a byte-identical archive and a stable ``download_sha256``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

# Reverse-DNS package identifier; matches the IPC manifest's identifier and the
# managed-venv directory name. Must satisfy three rules at once: the PCM schema
# pattern, the IPC api/schemas/v1 pattern, and KiCad's stricter C++ check
# (API_PLUGIN::IsValidIdentifier wants a word.word.word run — and \w excludes
# hyphens, so the hyphen must sit only in the trailing GitHub-repo segment).
IDENTIFIER = "com.github.unwndevices.kicad-captouch"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCHEMA_PATH = HERE / "pcm.v2.schema.json"
PCM_ICON = HERE / "pcm-icon.png"

# Files copied from the plugin bundle into the package's ``plugins/`` directory.
# README.md / make_icons.py are developer files KiCad does not need at runtime.
_PLUGIN_FILES = (
    "plugin.json",
    "entry.py",
    "requirements.txt",
    "icon-light-24.png",
    "icon-light-48.png",
    "icon-dark-24.png",
    "icon-dark-48.png",
)

# A reproducible-build epoch for zip entries (the DOS epoch zipfile floors to).
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(instance: object, definition: str, schema: dict) -> None:
    """Validate *instance* against ``#/definitions/<definition>`` of the PCM schema.

    Imported lazily so the module imports without ``jsonschema`` present; the build
    (and the test that drives it) require it, but consumers that only import the
    pure helpers do not.
    """
    import jsonschema

    sub = {
        "$schema": schema.get("$schema", "http://json-schema.org/draft-07/schema#"),
        "definitions": schema["definitions"],
        "$ref": f"#/definitions/{definition}",
    }
    jsonschema.validate(instance=instance, schema=sub)


def _pin_requirements(text: str, tag: str) -> str:
    """Pin the GitHub-zip dependency from the moving ``main`` branch to *tag*."""
    moving = "archive/refs/heads/main.zip"
    pinned = f"archive/refs/tags/{tag}.zip"
    if moving not in text:
        raise ValueError(
            f"requirements.txt does not reference {moving!r}; cannot pin to {tag}. "
            "Update build_pcm.py if the dependency line changed."
        )
    return text.replace(moving, pinned)


def _description_full() -> str:
    return (
        "Generate parametric capacitive-touch interface footprints — sliders, "
        "wheels, trackpads, mutual-capacitance sliders, and self-cap keypads — and "
        "their matching symbols, then install them straight into the open board's "
        "project library, ready to place with KiCad's own Add Footprint / Add Symbol "
        "pickers.\n\n"
        "The generator opens a live-preview design window from inside KiCad (Tools → "
        "External Plugins). Generation is done by the standalone kicad-captouch engine "
        "via direct S-expression emission, so the placed footprint is byte-identical "
        "to the CLI/GUI output. GPL-3.0."
    )


def _package_metadata(version: str, repo_slug: str, *, with_download: dict | None) -> dict:
    """The ``metadata.json`` Package object.

    *with_download* is ``None`` for the copy embedded in the archive (the spec forbids
    ``download_*`` there) and the download dict for the repository copy.
    """
    ver: dict = {
        "version": version,
        "status": "stable",
        "kicad_version": "9.0",
        "runtime": "ipc",
    }
    if with_download is not None:
        ver.update(with_download)
    return {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": "Capacitive-Touch Footprint Generator",
        "description": (
            "Generate parametric capacitive-touch slider, wheel, trackpad, "
            "mutual-slider, and keypad footprints (plus symbols) and add them to the "
            "open project's library."
        ),
        "description_full": _description_full(),
        "identifier": IDENTIFIER,
        "type": "plugin",
        "author": {
            "name": "Ciro Caputo Viglione",
            "contact": {"web": f"https://github.com/{repo_slug}"},
        },
        "license": "GPL-3.0-or-later",
        "resources": {"GitHub": f"https://github.com/{repo_slug}"},
        "versions": [ver],
    }


def _stage_plugins(plugin_dir: Path, dest_plugins: Path, tag: str) -> None:
    dest_plugins.mkdir(parents=True, exist_ok=True)
    for name in _PLUGIN_FILES:
        src = plugin_dir / name
        if not src.exists():
            raise FileNotFoundError(f"plugin bundle is missing {name}: {src}")
        if name == "requirements.txt":
            (dest_plugins / name).write_text(
                _pin_requirements(src.read_text(encoding="utf-8"), tag), encoding="utf-8"
            )
        else:
            shutil.copy2(src, dest_plugins / name)


def _write_zip(staging: Path, archive: Path) -> None:
    """Zip *staging*'s contents deterministically into *archive*."""
    files = sorted(p for p in staging.rglob("*") if p.is_file())
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(staging).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def build(
    *,
    version: str,
    tag: str,
    repo_slug: str,
    pages_url: str,
    plugin_dir: Path,
    outdir: Path,
    timestamp: int,
) -> dict:
    """Build the package archive and the repository index. Returns the artifact paths."""
    schema = _load_schema()
    outdir = outdir.resolve()
    staging = outdir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "plugins").mkdir(parents=True)
    (staging / "resources").mkdir(parents=True)

    # 1. assemble the package tree
    _stage_plugins(plugin_dir, staging / "plugins", tag)
    shutil.copy2(PCM_ICON, staging / "resources" / "icon.png")

    archive_meta = _package_metadata(version, repo_slug, with_download=None)
    _validate(archive_meta, "Package", schema)
    (staging / "metadata.json").write_text(
        json.dumps(archive_meta, indent=2) + "\n", encoding="utf-8"
    )

    # 2. zip it, then size/hash it
    archive = outdir / f"kicad-captouch-pcm-{version}.zip"
    install_size = _dir_size(staging)
    _write_zip(staging, archive)
    download_size = archive.stat().st_size
    download_sha256 = _sha256(archive)
    download_url = f"https://github.com/{repo_slug}/releases/download/{tag}/{archive.name}"

    # 3. repository index: packages.json carries the download_* keys
    repo_dir = outdir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    repo_meta = _package_metadata(
        version,
        repo_slug,
        with_download={
            "download_url": download_url,
            "download_sha256": download_sha256,
            "download_size": download_size,
            "install_size": install_size,
        },
    )
    packages = {"$schema": "https://go.kicad.org/pcm/schemas/v2", "packages": [repo_meta]}
    _validate(packages, "PackageArray", schema)
    (repo_dir / "packages.json").write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")

    # 4. resources.zip — icons keyed by identifier, for the PCM browse UI
    resources_zip = repo_dir / "resources.zip"
    res_staging = outdir / "_resources"
    if res_staging.exists():
        shutil.rmtree(res_staging)
    (res_staging / IDENTIFIER).mkdir(parents=True)
    shutil.copy2(PCM_ICON, res_staging / IDENTIFIER / "icon.png")
    _write_zip(res_staging, resources_zip)

    # 5. repository.json — the URL the user adds to the PCM
    packages_json = repo_dir / "packages.json"
    repository = {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": "kicad-captouch — Capacitive-Touch Footprint Generator",
        "schema_version": 2,
        "maintainer": {"name": "Ciro Caputo Viglione", "contact": {"web": pages_url}},
        "packages": {
            "url": f"{pages_url.rstrip('/')}/packages.json",
            "sha256": _sha256(packages_json),
            "update_timestamp": timestamp,
        },
        "resources": {
            "url": f"{pages_url.rstrip('/')}/resources.zip",
            "sha256": _sha256(resources_zip),
            "update_timestamp": timestamp,
        },
    }
    _validate(repository, "Repository", schema)
    (repo_dir / "repository.json").write_text(
        json.dumps(repository, indent=2) + "\n", encoding="utf-8"
    )

    shutil.rmtree(staging)
    shutil.rmtree(res_staging)
    return {
        "archive": archive,
        "download_sha256": download_sha256,
        "download_size": download_size,
        "install_size": install_size,
        "packages_json": packages_json,
        "repository_json": repo_dir / "repository.json",
        "resources_zip": resources_zip,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build KiCad PCM package + repository index.")
    parser.add_argument("--version", required=True, help="package version, e.g. 0.1.0")
    parser.add_argument("--tag", help="git tag for the release (default: v<version>)")
    parser.add_argument("--repo", default="unwndevices/kicad-captouch", help="owner/name slug")
    parser.add_argument(
        "--pages-url",
        help="base URL hosting the repository index (default: https://<owner>.github.io/<name>)",
    )
    parser.add_argument("--plugin-dir", type=Path, default=REPO_ROOT / "plugins" / "captouch")
    parser.add_argument("--outdir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument(
        "--timestamp",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        help="repository.json update_timestamp (unix seconds); CI passes the build time",
    )
    args = parser.parse_args(argv)

    tag = args.tag or f"v{args.version}"
    owner, _, name = args.repo.partition("/")
    pages_url = args.pages_url or f"https://{owner}.github.io/{name}"

    result = build(
        version=args.version,
        tag=tag,
        repo_slug=args.repo,
        pages_url=pages_url,
        plugin_dir=args.plugin_dir.resolve(),
        outdir=args.outdir,
        timestamp=args.timestamp,
    )
    print(f"package:  {result['archive']}")
    print(f"  sha256: {result['download_sha256']}")
    print(f"  size:   {result['download_size']} bytes (install {result['install_size']} bytes)")
    print(f"repo:     {result['repository_json'].parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
