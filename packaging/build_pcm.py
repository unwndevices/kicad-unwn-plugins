#!/usr/bin/env python3
"""Build the KiCad PCM (Plugin and Content Manager) distribution artifacts.

The monorepo ships one PCM package per tool (``--tool``, default ``captouch``) from
one shared repository index; a tool is described by a :class:`ToolSpec` entry in the
``TOOLS`` registry, so packaging a new tool is a registry entry, not a code fork.

From the selected tool's plugin bundle in ``plugins/<tool>/`` this produces:

* ``<outdir>/<archive>.zip``         the installable PCM package (``metadata.json`` +
                                     ``plugins/`` + ``resources/icon.png``) — what a
                                     user picks via *Manage Plugins → Install from File*.
* ``<outdir>/repo/packages.json``    the repository package index (carries ``download_*``)
                                     for *every* published tool, not just this one.
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
  inside KiCad;
* the index is a *shared* one — each per-tool release upserts its own entry into the
  index already published on Pages, so releasing one tool never drops the others (a
  single release only knows its own ``download_*``, so the others must be carried
  through, not regenerated).

The zip is built deterministically (sorted entries, fixed timestamps) so the same
inputs yield a byte-identical archive and a stable ``download_sha256``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCHEMA_PATH = HERE / "pcm.v2.schema.json"
PCM_ICON = HERE / "pcm-icon.png"

# The shared PCM repository index describes the whole monorepo, not one tool: a
# user adds a single repository URL and sees every published tool. Per-tool
# releases each redeploy this same index (§11 of the return-path-checker spec).
INDEX_NAME = "unwndevices KiCad plugins"
MAINTAINER = "Ciro Caputo Viglione"


@dataclass(frozen=True)
class ToolSpec:
    """Everything the PCM build needs that varies from one tool to the next.

    The monorepo ships one PCM package per tool (captouch today; returnpath next)
    from one shared repository index. A tool is fully described by this record, so
    generalizing the build to a new tool is a registry entry, not a code fork.
    """

    name: str
    """Registry key and release-tag prefix, e.g. ``captouch`` (tag ``captouch-vX.Y.Z``)."""

    identifier: str
    """Reverse-DNS PCM identifier — matches the IPC manifest identifier and the
    managed-venv directory name. Must satisfy three rules at once: the PCM schema
    pattern, the IPC api/schemas/v1 pattern, and KiCad's stricter C++ check
    (``API_PLUGIN::IsValidIdentifier`` wants a word.word.word run — and ``\\w``
    excludes hyphens, so the hyphen must sit only in the trailing repo segment).
    Never change a shipped tool's identifier: it is what KiCad keys installs on."""

    display_name: str
    """PCM ``metadata.json`` ``name``."""

    description: str
    """One-line PCM ``description``."""

    description_full: str
    """Long-form PCM ``description_full``."""

    plugin_subdir: str
    """Bundle directory under ``plugins/`` (e.g. ``captouch``)."""

    package_name: str
    """Distribution / PyPI package name (e.g. ``kicad-captouch``); also the PCM
    archive basename (``<package_name>-pcm-<version>.zip``)."""

    kicad_version: str = "9.0"
    """Minimum KiCad version advertised in the package version record."""


def _returnpath_description_full() -> str:
    return (
        "Check a KiCad board's current-return paths from inside the PCB editor: "
        "split-plane crossings, reference-plane edge clearance, and missing return "
        "vias at layer changes.\n\n"
        "Run it on the live board (unsaved edits included) and the findings appear as "
        "native DRC markers (unwaived errors/warnings), a durable User-layer overlay of "
        "numbered severity-coloured crosshairs (every finding; waived drawn muted), and "
        "selection — clicking a finding flashes the offending trace. Configuration and "
        "waivers are read from the project's return-path.toml / return-path.waivers.toml, "
        "exactly as the CLI, which stays the CI path. Requires KiCad 10+. GPL-3.0."
    )


def _captouch_description_full() -> str:
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


# The registry of tools that ship a PCM package. core (no plugin) stays reserved on
# paper and registers itself once it ships — see docs/return-path-checker-v1-spec.md §11.
TOOLS: dict[str, ToolSpec] = {
    "captouch": ToolSpec(
        name="captouch",
        identifier="com.github.unwndevices.kicad-captouch",
        display_name="Capacitive-Touch Footprint Generator",
        description=(
            "Generate parametric capacitive-touch slider, wheel, trackpad, "
            "mutual-slider, and keypad footprints (plus symbols) and add them to the "
            "open project's library."
        ),
        description_full=_captouch_description_full(),
        plugin_subdir="captouch",
        package_name="kicad-captouch",
    ),
    "returnpath": ToolSpec(
        name="returnpath",
        identifier="com.github.unwndevices.kicad-returnpath",
        display_name="Return-Path Checker",
        description=(
            "Check the open board's current-return paths (split-plane crossings, "
            "plane-edge clearance, missing return vias) and surface the findings as DRC "
            "markers, a User-layer overlay, and selection."
        ),
        description_full=_returnpath_description_full(),
        plugin_subdir="returnpath",
        package_name="kicad-returnpath",
        kicad_version="10.0",
    ),
}

# Back-compat alias: the default tool's identifier. Kept because callers and tests
# reference ``build_pcm.IDENTIFIER`` directly.
IDENTIFIER = TOOLS["captouch"].identifier

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


def _package_metadata(
    tool: ToolSpec, version: str, repo_slug: str, *, with_download: dict | None
) -> dict:
    """The ``metadata.json`` Package object for *tool*.

    *with_download* is ``None`` for the copy embedded in the archive (the spec forbids
    ``download_*`` there) and the download dict for the repository copy.
    """
    ver: dict = {
        "version": version,
        "status": "stable",
        "kicad_version": tool.kicad_version,
        "runtime": "ipc",
    }
    if with_download is not None:
        ver.update(with_download)
    return {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": tool.display_name,
        "description": tool.description,
        "description_full": tool.description_full,
        "identifier": tool.identifier,
        "type": "plugin",
        "author": {
            "name": MAINTAINER,
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


def _fetch_published_packages(index_url: str) -> list[dict]:
    """Return the ``packages`` array already published at *index_url*.

    The shared index must survive a per-tool release: a single release carries only
    its own ``download_*``, so the other tools' entries have to be read back from the
    live ``packages.json`` and preserved. A ``404`` means nothing has been published
    yet (the first-ever release) — start from an empty list. Any *other* failure is
    deliberately left to propagate: silently starting from empty on a transient error
    would clobber every already-published tool, which is exactly the bug this avoids.
    """
    try:
        with urllib.request.urlopen(index_url) as resp:  # noqa: S310 — fixed https index URL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    packages = payload.get("packages", [])
    if not isinstance(packages, list):
        raise ValueError(f"{index_url} has a non-list 'packages' field")
    return packages


def _merge_packages(existing: list[dict], entry: dict) -> list[dict]:
    """Upsert *entry* into *existing* by identifier, returning a sorted list.

    The tool being released replaces any prior entry with the same identifier (a
    version bump), and every other tool is carried through untouched. Sorting by
    identifier keeps the emitted index byte-stable no matter which tool triggered
    the build.
    """
    ident = entry["identifier"]
    merged = [p for p in existing if p.get("identifier") != ident]
    merged.append(entry)
    merged.sort(key=lambda p: p["identifier"])
    return merged


def build(
    *,
    version: str,
    tag: str,
    repo_slug: str,
    pages_url: str,
    plugin_dir: Path,
    outdir: Path,
    timestamp: int,
    tool: ToolSpec = TOOLS["captouch"],
    existing_packages: list[dict] | None = None,
) -> dict:
    """Build the package archive and the repository index. Returns the artifact paths.

    *existing_packages* is the ``packages`` array already published in the shared
    index; this tool is upserted into it so a per-tool release keeps every other
    tool. ``None`` (the default) builds a single-tool index — the first-ever release,
    or a caller that has nothing to merge.
    """
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

    archive_meta = _package_metadata(tool, version, repo_slug, with_download=None)
    _validate(archive_meta, "Package", schema)
    (staging / "metadata.json").write_text(
        json.dumps(archive_meta, indent=2) + "\n", encoding="utf-8"
    )

    # 2. zip it, then size/hash it
    archive = outdir / f"{tool.package_name}-pcm-{version}.zip"
    install_size = _dir_size(staging)
    _write_zip(staging, archive)
    download_size = archive.stat().st_size
    download_sha256 = _sha256(archive)
    download_url = f"https://github.com/{repo_slug}/releases/download/{tag}/{archive.name}"

    # 3. repository index: packages.json carries the download_* keys
    repo_dir = outdir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    repo_meta = _package_metadata(
        tool,
        version,
        repo_slug,
        with_download={
            "download_url": download_url,
            "download_sha256": download_sha256,
            "download_size": download_size,
            "install_size": install_size,
        },
    )
    merged = _merge_packages(existing_packages or [], repo_meta)
    packages = {"$schema": "https://go.kicad.org/pcm/schemas/v2", "packages": merged}
    _validate(packages, "PackageArray", schema)
    (repo_dir / "packages.json").write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")

    # 4. resources.zip — icons keyed by identifier, for the PCM browse UI. It covers
    #    every tool in the merged index (not just the one released), so browsing shows
    #    an icon for each. All tools share the same PCM icon, keyed by identifier.
    resources_zip = repo_dir / "resources.zip"
    res_staging = outdir / "_resources"
    if res_staging.exists():
        shutil.rmtree(res_staging)
    for ident in sorted({p["identifier"] for p in merged}):
        (res_staging / ident).mkdir(parents=True)
        shutil.copy2(PCM_ICON, res_staging / ident / "icon.png")
    _write_zip(res_staging, resources_zip)

    # 5. repository.json — the shared index URL a user adds to the PCM (repo-wide,
    #    not per-tool; each tool release redeploys it).
    packages_json = repo_dir / "packages.json"
    repository = {
        "$schema": "https://go.kicad.org/pcm/schemas/v2",
        "name": INDEX_NAME,
        "schema_version": 2,
        "maintainer": {"name": MAINTAINER, "contact": {"web": pages_url}},
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
    parser.add_argument(
        "--tool",
        default="captouch",
        choices=sorted(TOOLS),
        help="which tool to package (default: captouch)",
    )
    parser.add_argument("--tag", help="git tag for the release (default: <tool>-v<version>)")
    parser.add_argument("--repo", default="unwndevices/kicad-unwn-plugins", help="owner/name slug")
    parser.add_argument(
        "--pages-url",
        help="base URL hosting the repository index (default: https://<owner>.github.io/<name>)",
    )
    parser.add_argument(
        "--base-index-url",
        help="URL of the live packages.json to merge this tool into "
        "(default: <pages-url>/packages.json). A 404 there is treated as an empty index.",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="emit a single-tool index instead of upserting into the published one "
        "(use for the first-ever release or an offline build)",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        help="plugin bundle dir (default: plugins/<tool subdir>)",
    )
    parser.add_argument("--outdir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument(
        "--timestamp",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        help="repository.json update_timestamp (unix seconds); CI passes the build time",
    )
    args = parser.parse_args(argv)

    tool = TOOLS[args.tool]
    tag = args.tag or f"{tool.name}-v{args.version}"
    plugin_dir = args.plugin_dir or (REPO_ROOT / "plugins" / tool.plugin_subdir)
    owner, _, name = args.repo.partition("/")
    pages_url = args.pages_url or f"https://{owner}.github.io/{name}"

    if args.no_merge:
        existing_packages = None
    else:
        index_url = args.base_index_url or f"{pages_url.rstrip('/')}/packages.json"
        existing_packages = _fetch_published_packages(index_url)
        carried = [p["identifier"] for p in existing_packages if p.get("identifier") != tool.identifier]
        print(f"merging into published index ({len(carried)} other tool(s) carried through)")

    result = build(
        version=args.version,
        tag=tag,
        repo_slug=args.repo,
        pages_url=pages_url,
        plugin_dir=plugin_dir.resolve(),
        outdir=args.outdir,
        timestamp=args.timestamp,
        tool=tool,
        existing_packages=existing_packages,
    )
    print(f"package:  {result['archive']}")
    print(f"  sha256: {result['download_sha256']}")
    print(f"  size:   {result['download_size']} bytes (install {result['install_size']} bytes)")
    print(f"repo:     {result['repository_json'].parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
