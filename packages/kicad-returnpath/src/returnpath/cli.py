"""``return-path`` command-line frontend (spec §10).

Surface::

    return-path check BOARD.kicad_pcb [config/waiver/selection/output options]

Config (§6) is discovered/overridden per :mod:`returnpath.config`; the waiver sidecar
(§7.2) is discovered/managed per :mod:`returnpath.waivers`. Exit codes (§10) are computed
from **unwaived** findings only: ``0`` clean, ``1`` an unwaived finding at or above
``--fail-on`` (default ``error``), ``2`` a usage / parse error (bad args, unreadable board,
non-KiCad-10 schema, invalid config/waivers).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .config import ConfigError, build_config
from .detector import Finding
from .engine import analyze_board
from .parser import Board, ParserContractError
from .report import FORMAT_EXT, REPORT_FORMATS, SEVERITY_ORDER, render_report
from .waivers import (
    WAIVERS_FILENAME,
    WaiverError,
    append_waiver,
    apply_waivers,
    discover_waivers,
    dump_waivers,
    git_author,
    load_waivers,
    stale_findings,
    today_stamp,
    waiver_for,
    waiver_from_hash,
)


def _check(args: argparse.Namespace) -> int:
    board_path: Path = args.board
    if not board_path.is_file():
        print(f"error: board not found: {board_path}", flush=True)
        return 2

    try:
        text = board_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {board_path}: {exc}", flush=True)
        return 2

    try:
        config = build_config(
            board_path,
            explicit=args.config,
            reference_nets=tuple(args.reference_nets) if args.reference_nets else None,
            include=tuple(args.include) if args.include else None,
            exclude=tuple(args.exclude) if args.exclude else None,
            sets=args.set,
        )
    except ConfigError as exc:
        print(f"error: {exc}", flush=True)
        return 2

    try:
        board, findings = analyze_board(text, config=config)
    except ParserContractError as exc:
        print(f"error: {board_path.name}: {exc}", flush=True)
        return 2
    except (ValueError, IndexError) as exc:
        print(f"error: {board_path.name}: could not parse board: {exc}", flush=True)
        return 2

    waiver_path: Path | None
    try:
        if args.waive is not None:
            # --waive resolves (and may create) its own target, so a not-yet-existing
            # explicit --waivers path is fine here — don't fail discovery before writing.
            waiver_path = _do_waive(args.waive, args.reason, findings, board_path, args.waivers)
        else:
            waiver_path = None if args.no_waivers else discover_waivers(board_path, args.waivers)
        waivers = load_waivers(waiver_path)
    except WaiverError as exc:
        print(f"error: {exc}", flush=True)
        return 2

    result = apply_waivers(findings, waivers)

    if args.prune_waivers:
        _do_prune(waiver_path, result.stale)

    report_findings = result.findings + stale_findings(result.stale)

    try:
        formats = _resolve_formats(args.format)
        _emit_reports(formats, board_path.name, report_findings, board, args)
    except ReportError as exc:
        print(f"error: {exc}", flush=True)
        return 2
    except OSError as exc:
        print(f"error: cannot write report: {exc}", flush=True)
        return 2

    return _exit_code(report_findings, args.fail_on)


class ReportError(Exception):
    """A bad ``--format`` / ``--output`` / ``--out-dir`` combination (CLI exit 2)."""


def _resolve_formats(raw: list[str] | None) -> list[str]:
    """Flatten repeatable / comma-separated ``--format`` values into an ordered, deduped list.

    Defaults to ``["text"]`` (§10). Every entry must be a known format (§8.2).
    """
    if not raw:
        return ["text"]
    formats: list[str] = []
    for chunk in raw:
        for name in chunk.split(","):
            name = name.strip()
            if not name:
                continue
            if name not in REPORT_FORMATS:
                raise ReportError(
                    f"unknown format {name!r}; choose from {', '.join(REPORT_FORMATS)}"
                )
            if name not in formats:
                formats.append(name)
    return formats or ["text"]


def _emit_reports(
    formats: list[str],
    board_name: str,
    findings: list[Finding],
    board: Board,
    args: argparse.Namespace,
) -> None:
    """Write each requested format to ``--out-dir``, ``--output`` (single), or stdout (§10)."""
    if args.out_dir is not None:
        out_dir: Path = args.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(board_name).stem
        for fmt in formats:
            path = out_dir / f"{stem}.return-path.{FORMAT_EXT[fmt]}"
            path.write_text(render_report(fmt, board_name, findings, board), encoding="utf-8")
            print(f"wrote {fmt} → {path}", flush=True)
        return

    if len(formats) != 1:
        raise ReportError(
            "multiple --format values need --out-dir; use one format for --output/stdout"
        )
    fmt = formats[0]
    body = render_report(fmt, board_name, findings, board)
    if args.output is not None:
        args.output.write_text(body, encoding="utf-8")
        print(f"wrote {fmt} → {args.output}", flush=True)
    else:
        print(body)


def _do_waive(
    hash_id: str,
    reason: str | None,
    findings: list[Finding],
    board_path: Path,
    explicit: Path | None,
) -> Path:
    """Append a waiver for *hash_id* to the sidecar, echoing a matching finding (§7.2, §10)."""
    if not reason:
        raise WaiverError("--waive requires --reason")
    target = explicit or discover_waivers(board_path) or board_path.parent / WAIVERS_FILENAME
    author, today = git_author(), today_stamp()
    match = next((f for f in findings if f.id == hash_id), None)
    if match is not None:
        entry = waiver_for(match, reason, author=author, today=today)
    else:
        entry = waiver_from_hash(hash_id, reason, author=author, today=today)
        print(
            f"note: no finding this run matches {hash_id}; wrote a bare waiver entry",
            flush=True,
        )
    append_waiver(target, entry)
    print(f"waived {hash_id} → {target.name}", flush=True)
    return target


def _do_prune(waiver_path: Path | None, stale: list) -> None:
    """Remove stale/expired waivers from the sidecar (only on explicit ``--prune-waivers``)."""
    if waiver_path is None or not waiver_path.is_file():
        return
    stale_ids = {w.id for w in stale}
    kept = [w for w in load_waivers(waiver_path) if w.id not in stale_ids]
    waiver_path.write_text(dump_waivers(kept), encoding="utf-8")
    if stale_ids:
        print(f"pruned {len(stale_ids)} stale waiver(s) from {waiver_path.name}", flush=True)


def _exit_code(findings: list[Finding], fail_on: str) -> int:
    """Exit code from **unwaived** findings only (§10) — waiving the last error greens the build."""
    if fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER[fail_on]
    worst = max(
        (SEVERITY_ORDER.get(f.severity, 0) for f in findings if not f.waived),
        default=0,
    )
    return 1 if worst >= threshold else 0


def _add_check_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("check", help="check a board's current return paths")
    p.add_argument(
        "board", type=Path, help="path to a .kicad_pcb (KiCad 10, file version 20260206)"
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="explicit return-path.toml (else discovered upward from the board)",
    )
    p.add_argument(
        "--reference-nets",
        nargs="+",
        default=None,
        metavar="NET",
        help="override reference (plane) net names (default: GND + power)",
    )
    p.add_argument(
        "--include",
        action="append",
        metavar="NET",
        help="force-check a net even if excluded (repeatable)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        metavar="NET",
        help="skip a net or netclass (repeatable)",
    )
    p.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="ad-hoc threshold/severity override, e.g. min_crossing_span_mm=0.2 (repeatable)",
    )
    p.add_argument(
        "--waivers",
        type=Path,
        default=None,
        metavar="PATH",
        help="explicit return-path.waivers.toml (else discovered alongside the config)",
    )
    p.add_argument(
        "--no-waivers",
        action="store_true",
        help="ignore the waiver sidecar for this run",
    )
    p.add_argument(
        "--waive",
        metavar="HASH",
        default=None,
        help="append a waiver for the finding with this content hash (needs --reason)",
    )
    p.add_argument(
        "--reason",
        metavar="TEXT",
        default=None,
        help="the review reason recorded with --waive",
    )
    p.add_argument(
        "--prune-waivers",
        action="store_true",
        help="remove stale (unmatched) waiver entries from the sidecar",
    )
    p.add_argument(
        "--format",
        action="append",
        metavar="FMT",
        help="report format(s): text|json|svg|html, comma-separated/repeatable (default: text)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="write a single-format report to a file (else stdout)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="write all requested formats into a directory",
    )
    p.add_argument(
        "--fail-on",
        choices=("error", "warning", "info", "none"),
        default="error",
        help="exit non-zero when an unwaived finding reaches this level (default: error)",
    )
    p.set_defaults(func=_check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="return-path",
        description="Geometric current-return-path checker for KiCad PCBs.",
    )
    parser.add_argument("--version", action="version", version=f"return-path {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_check_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
