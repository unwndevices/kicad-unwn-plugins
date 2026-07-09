"""``return-path`` command-line frontend (spec §10).

Walking-skeleton surface::

    return-path check BOARD.kicad_pcb [--reference-nets NET ...] [--fail-on LEVEL]

Exit codes (§10): ``0`` clean, ``1`` a finding at or above ``--fail-on`` (default
``error``), ``2`` a usage / parse error (bad args, unreadable board, non-KiCad-10
schema). The richer config / waiver / multi-format surface lands in later issues.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .config import ConfigError, build_config
from .detector import check_return_path
from .parser import ParserContractError, parse_board
from .report import SEVERITY_ORDER, format_text_report


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

    reference_nets = config.reference_nets
    min_pour_area = config.for_net().min_pour_area_mm2
    try:
        board = parse_board(text, reference_nets, min_pour_area_mm2=min_pour_area)
    except ParserContractError as exc:
        print(f"error: {board_path.name}: {exc}", flush=True)
        return 2
    except (ValueError, IndexError) as exc:
        print(f"error: {board_path.name}: could not parse board: {exc}", flush=True)
        return 2

    findings = check_return_path(
        board,
        reference_nets=reference_nets,
        config=config,
        net_to_netclass=board.net_classes,
    )
    print(format_text_report(board_path.name, findings))
    return _exit_code(findings, args.fail_on)


def _exit_code(findings: list, fail_on: str) -> int:
    if fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER[fail_on]
    worst = max((SEVERITY_ORDER.get(f.severity, 0) for f in findings), default=0)
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
        "--fail-on",
        choices=("error", "warning", "info", "none"),
        default="error",
        help="exit non-zero when a finding reaches this level (default: error)",
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
