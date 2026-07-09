"""IPC entrypoint: run the return-path check on the *live* KiCad board (spec §9).

Invoked by KiCad as the plugin action (via ``plugins/returnpath/entry.py``). The flow
keeps the core CLI text emitter authoritative — kipy is used only to reach the running
KiCad, read the open board, and draw the results back:

1. connect to the running KiCad over the IPC socket (env-configured by KiCad);
2. ``Board.get_as_string()`` → the live ``.kicad_pcb`` text (unsaved edits included, §9);
3. run the shared :func:`returnpath.engine.check_live_board` on it (config + waivers
   discovered from the board's on-disk path) — the *same* analysis as a headless run;
4. surface the findings (spec §8.3): ``InjectDrcError`` markers for unwaived
   ``error``/``warning``; durable ``User.*`` overlay graphics for *every* finding (waived
   muted); ``add_to_selection`` to flash a finding's trace.

Only the pure pieces are exercised in tests: :mod:`returnpath.kicad_plugin.surfaces`
(marker/overlay/selection policy), :func:`board_path_for_discovery`, and the
``--board-file`` dispatch of :func:`main`. The live kipy connection, the marker/overlay
drawing, and the Qt-free selection round-trip need a real KiCad and are the manual
in-KiCad acceptance step (no live KiCad in CI). kicad-python is pinned to **0.7.1** and
the broken ``kipy.board_rules`` / ``kipy.schematic_types`` imports are avoided (§9 gotcha).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ..engine import CheckResult, check_live_board
from ..report import format_text_report
from .surfaces import (
    crosshair_lines,
    drc_marker_findings,
    overlay_marks,
    trace_for_finding,
)

# The KiCad board layer the durable overlay is drawn on (a User.* layer survives a
# native DRC run, unlike the injected markers; §8.3).
OVERLAY_LAYER = "User.1"

# KiCad's internal unit is the nanometre; board coordinates from the parser are millimetres.
_MM_TO_NM = 1_000_000

_PROJECT_FILE_SUFFIXES = {".kicad_pcb", ".kicad_pro", ".kicad_sch"}


class PluginError(RuntimeError):
    """Raised when the open board's on-disk location cannot be determined."""


def board_path_for_discovery(path: str | Path) -> Path:
    """A board-file path whose ``.parent`` is the project directory (for config/waivers).

    :func:`returnpath.engine.check_live_board` discovers ``return-path.toml`` /
    ``return-path.waivers.toml`` by walking upward from ``board_path.parent`` (§6.2/§7.2).
    KiCad may hand us the board file, a ``.kicad_pro``, or the project directory; all
    collapse to a path *inside* the project dir so discovery starts there. The board file
    need not exist on disk — only its directory is used.
    """
    p = Path(path).expanduser()
    if p.suffix in _PROJECT_FILE_SUFFIXES or (p.exists() and p.is_file()):
        return p.resolve()
    return p.resolve() / "board.kicad_pcb"


def _board_disk_path(board: object) -> Path:
    """On-disk path for an open kipy ``Board`` — its project path, else the board file."""
    get_project = getattr(board, "get_project", None)
    if callable(get_project):
        try:
            project = get_project()
        except Exception:  # noqa: BLE001 — any IPC hiccup falls back to the board file
            project = None
        path = getattr(project, "path", None) if project is not None else None
        if path:
            return board_path_for_discovery(path)
    name = getattr(board, "name", None)
    if name:
        return board_path_for_discovery(name)
    raise PluginError("could not determine the open board's on-disk path")


# --------------------------------------------------------------------------- #
# live-KiCad surfacing (manual-acceptance path — needs a running KiCad)
# --------------------------------------------------------------------------- #
def _connect_board() -> Any:
    """Connect to the running KiCad over IPC and return the open board (lazy kipy import)."""
    from kipy import KiCad  # lazy: only needed when actually running inside KiCad

    kicad = KiCad()  # reads KICAD_API_SOCKET / KICAD_API_TOKEN from the environment
    return kicad.get_board()


def _inject_drc_markers(board: object, result: CheckResult) -> int:
    """Inject a native DRC marker for each unwaived error/warning (§8.3). Best-effort."""
    findings = drc_marker_findings(result.findings)
    inject = getattr(board, "inject_drc_error", None) or getattr(board, "InjectDrcError", None)
    if not callable(inject):
        return 0
    for f in findings:
        severity = "error" if f.severity == "error" else "warning"
        inject(
            message=f.message,
            severity=severity,
            position=(round(f.x * _MM_TO_NM), round(f.y * _MM_TO_NM)),
        )
    return len(findings)


def _draw_overlay(board: object, result: CheckResult) -> int:
    """Draw the durable ``User.*`` crosshair + label overlay for every finding (§8.3)."""
    marks = overlay_marks(result.findings)
    draw = getattr(board, "create_items", None)
    if not callable(draw):
        return 0
    from kipy.board_types import BoardShape, BoardText  # lazy; avoid at import time

    items: list[object] = []
    for mark in marks:
        for (x0, y0), (x1, y1) in crosshair_lines(mark):
            seg = BoardShape()
            seg.layer = OVERLAY_LAYER
            seg.start = (round(x0 * _MM_TO_NM), round(y0 * _MM_TO_NM))
            seg.end = (round(x1 * _MM_TO_NM), round(y1 * _MM_TO_NM))
            items.append(seg)
        text = BoardText()
        text.layer = OVERLAY_LAYER
        text.value = mark.label
        text.position = (round(mark.x * _MM_TO_NM), round(mark.y * _MM_TO_NM))
        items.append(text)
    draw(items)
    return len(marks)


def _flash_trace(board: object, result: CheckResult, finding_index: int) -> bool:
    """Select/flash the trace for the finding at *finding_index* in the report order (§8.3)."""
    ordered = overlay_marks(result.findings)
    if not 0 <= finding_index < len(ordered):
        return False
    trace = trace_for_finding(result.board, ordered[finding_index].finding)
    if trace is None:
        return False
    select = getattr(board, "add_to_selection", None)
    if not callable(select):
        return False
    live = _match_live_track(board, trace)
    if live is None:
        return False
    select([live])
    return True


def _match_live_track(board: object, trace: object) -> object | None:
    """Find the live kipy track matching a parsed :class:`~returnpath.parser.Trace`.

    Matched on net + layer + coincident endpoints — the parser and the live board share
    the same coordinates, so a nanometre-rounded endpoint match is exact.
    """
    get_tracks = getattr(board, "get_tracks", None)
    if not callable(get_tracks):
        return None
    want = {
        (round(x * _MM_TO_NM), round(y * _MM_TO_NM))
        for x, y in getattr(trace, "line").coords  # noqa: B009 — attribute known present
    }
    for track in get_tracks():
        start = getattr(track, "start", None)
        end = getattr(track, "end", None)
        if start is None or end is None:
            continue
        pts = {(round(start.x), round(start.y)), (round(end.x), round(end.y))}
        if pts <= want:
            return track
    return None


def run_in_kicad() -> int:
    """Connect to KiCad, check the live board, and surface the findings (§8.3)."""
    board: Any = _connect_board()
    text = board.get_as_string()
    result = check_live_board(text, _board_disk_path(board))
    markers = _inject_drc_markers(board, result)
    overlay = _draw_overlay(board, result)
    print(format_text_report(_board_name(board), result.findings))
    print(f"\nreturn-path: {markers} DRC marker(s), {overlay} overlay mark(s) drawn.")
    return 0


def _board_name(board: object) -> str:
    return str(getattr(board, "name", None) or "live board")


# --------------------------------------------------------------------------- #
# headless dispatch (testable — no live KiCad)
# --------------------------------------------------------------------------- #
def run_board_file(board_file: Path) -> int:
    """Run the check on a ``.kicad_pcb`` *file* and print the text report + surface counts.

    The headless equivalent of :func:`run_in_kicad`: it proves the plugin core runs the
    *same* analysis (and marker/overlay policy) as a headless CLI run, without a live KiCad.
    """
    text = board_file.read_text(encoding="utf-8")
    result = check_live_board(text, board_file)
    markers = drc_marker_findings(result.findings)
    marks = overlay_marks(result.findings)
    print(format_text_report(board_file.name, result.findings))
    print(
        f"\nreturn-path surfaces: {len(markers)} DRC marker(s) "
        f"(unwaived error/warning), {len(marks)} overlay mark(s)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="return-path-kicad-plugin",
        description="KiCad IPC plugin: check the open board's return paths and surface "
        "the findings as DRC markers, a User-layer overlay, and selection.",
    )
    parser.add_argument(
        "--board-file",
        type=Path,
        metavar="PATH",
        help="check this .kicad_pcb file directly instead of connecting to a running "
        "KiCad (for testing / headless use)",
    )
    args = parser.parse_args(argv)

    if args.board_file is not None:
        if not args.board_file.is_file():
            print(f"error: board not found: {args.board_file}", file=sys.stderr)
            return 2
        return run_board_file(args.board_file)

    try:
        return run_in_kicad()
    except Exception as exc:  # noqa: BLE001 — surface any connection/surfacing failure plainly
        print(f"error: could not run in KiCad over the IPC API: {exc}", file=sys.stderr)
        print(
            "  Run this from inside KiCad (Tools → External Plugins → Return-Path Checker),",
            file=sys.stderr,
        )
        print(
            "  or pass --board-file BOARD.kicad_pcb to check a board without a live connection.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
