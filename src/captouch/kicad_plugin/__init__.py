"""KiCad IPC Action Plugin support (Phase 13).

The plugin runs the same engine the CLI and GUI use, then installs the generated
footprint + symbol into a KiCad **library** (project-local by default) and registers
it so KiCad's *Add Footprint* / *Add Symbol* pickers can place it — resolving v1's
deferred "insert directly into the open board" question via the stable IPC API
(``kicad-python``), without re-authoring the version-resilient text emitter.

:mod:`library` is pure file I/O and is always importable. The :func:`main`
entrypoint connects to a running KiCad (kipy) and launches the GUI, so it is
imported lazily to keep this package free of kipy/Qt at import time.
"""

from __future__ import annotations

from .library import (
    DEFAULT_NICKNAME,
    InstallResult,
    LibraryError,
    LibraryTarget,
    install,
    install_widget,
    kicad_config_dir,
    make_target,
    project_target,
)

__all__ = [
    "DEFAULT_NICKNAME",
    "InstallResult",
    "LibraryError",
    "LibraryTarget",
    "install",
    "install_widget",
    "kicad_config_dir",
    "make_target",
    "project_target",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked by KiCad as an IPC plugin action (see :mod:`plugin`)."""
    from .plugin import main as _main

    return _main(argv)
