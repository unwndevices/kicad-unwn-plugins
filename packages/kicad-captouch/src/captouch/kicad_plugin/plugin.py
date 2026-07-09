"""IPC entrypoint: connect to the running KiCad, find the open project, run the GUI.

Invoked by KiCad as the plugin action (via ``kicad-plugin/entry.py``). The flow is
deliberately thin — the version-resilient text emitter stays the single source of
truth, and the IPC API (``kicad-python`` / kipy) is used only to learn *which*
project is open:

1. connect to the running KiCad over the IPC socket (env-configured by KiCad);
2. read the open board's project directory;
3. launch the live-preview GUI in *install mode* targeting that project, so the
   designed widget is written into the project's ``captouch`` library and shows up
   in KiCad's *Add Footprint* / *Add Symbol* pickers.

Only :func:`project_dir_from_path` and the :func:`main` dispatch are exercised in
tests; the kipy connection and the Qt event loop need a real KiCad / display and
are covered by the manual in-KiCad acceptance step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# A path KiCad might hand us for the "project": any of these *files* resolves to its
# containing directory; anything else is treated as the directory itself.
_PROJECT_FILE_SUFFIXES = {".kicad_pcb", ".kicad_pro", ".kicad_sch"}


class PluginError(RuntimeError):
    """Raised when the open board's project cannot be determined."""


def project_dir_from_path(path: str | Path) -> Path:
    """Resolve a board/project path to its project *directory*.

    KiCad may report the project as a directory or as a ``.kicad_pro`` /
    ``.kicad_pcb`` file path; both collapse to the directory that holds the
    ``fp-lib-table`` / ``sym-lib-table``.
    """
    p = Path(path).expanduser()
    if p.suffix in _PROJECT_FILE_SUFFIXES or (p.exists() and p.is_file()):
        return p.resolve().parent
    return p.resolve()


def _board_project_dir(board: object) -> Path:
    """Project directory for an open kipy ``Board`` (project path, else board file)."""
    get_project = getattr(board, "get_project", None)
    if callable(get_project):
        try:
            project = get_project()
        except Exception:  # noqa: BLE001 — any IPC hiccup falls back to the board file
            project = None
        path = getattr(project, "path", None) if project is not None else None
        if path:
            return project_dir_from_path(path)
    name = getattr(board, "name", None)
    if name:
        return project_dir_from_path(name)
    raise PluginError("could not determine the open board's project directory")


def connect_project_dir() -> Path:
    """Connect to the running KiCad over IPC and return the open project directory.

    Imports kipy lazily so the package stays importable without it (e.g. in tests).
    """
    from kipy import KiCad  # lazy: only needed when actually running inside KiCad

    kicad = KiCad()  # reads KICAD_API_SOCKET / KICAD_API_TOKEN from the environment
    return _board_project_dir(kicad.get_board())


def _launch_gui(project_dir: Path) -> int:
    """Run the live-preview GUI in install mode for *project_dir*."""
    try:
        from ..gui.app import run
    except ImportError as exc:  # PySide6 missing
        print(
            f"error: the generator GUI needs PySide6 ({exc}); "
            f"install it with: pip install 'kicad-captouch[gui]'",
            file=sys.stderr,
        )
        return 2
    return run([], project_dir=project_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="captouch-kicad-plugin",
        description="KiCad IPC plugin: design a capacitive-touch widget and add it "
        "to the open board's project library.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        metavar="DIR",
        help="target this project directory directly instead of connecting to a "
        "running KiCad (for testing / headless use)",
    )
    args = parser.parse_args(argv)

    if args.project_dir is not None:
        project_dir = project_dir_from_path(args.project_dir)
    else:
        try:
            project_dir = connect_project_dir()
        except Exception as exc:  # noqa: BLE001 — surface any connection failure plainly
            print(f"error: could not reach KiCad over the IPC API: {exc}", file=sys.stderr)
            print(
                "  Run this from inside KiCad (Tools → External Plugins → "
                "Capacitive-Touch Generator),",
                file=sys.stderr,
            )
            print(
                "  or pass --project-dir DIR to target a project without a live connection.",
                file=sys.stderr,
            )
            return 2

    return _launch_gui(project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
