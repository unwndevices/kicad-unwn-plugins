"""The check pipeline shared by the CLI (§10) and the in-KiCad IPC plugin (§9).

The CLI parses arguments and manages waivers; the plugin connects to KiCad and draws
markers/overlays. Both must run the *same* analysis so the plugin reports the same
findings as a headless run (spec §9). This module is that single core:

* :func:`analyze_board` — board text + resolved config → ``(Board, findings)`` (the
  parse → classify → content-hash stamp path, with no waiver/report/exit policy).
  The CLI calls it so its ``--waive`` / ``--prune`` / report emission wrap the exact
  same findings the plugin surfaces.
* :func:`check_live_board` — the plugin's one-call entry: discover the project's
  config + waiver sidecar from the board's on-disk path, analyze the *live* board text
  (unsaved edits included, via ``Board.get_as_string()``), apply the waivers, and hand
  back a :class:`CheckResult` carrying both the report set (active + stale) and the raw
  pre-waiver findings (which the findings-list panel and un-waive flow, #24, consume).

Neither entry parses CLI args or touches KiCad — the kipy/Qt surface lives in
:mod:`returnpath.kicad_plugin`, so this module stays importable headless.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config, build_config
from .detector import Finding, check_return_path
from .parser import Board, parse_board
from .waivers import (
    apply_waivers,
    discover_waivers,
    load_waivers,
    stale_findings,
    with_ids,
)

__all__ = ["CheckResult", "analyze_board", "check_live_board"]


def analyze_board(board_text: str, *, config: Config) -> tuple[Board, list[Finding]]:
    """Parse *board_text* under *config* and return ``(board, findings)`` with ids stamped.

    The single analysis path: it resolves the reference nets and pour floor from *config*,
    parses the board (raising :class:`~returnpath.parser.ParserContractError` on a
    pre-KiCad-10 schema, §3), runs every §5 check, and stamps each finding's content-hash
    ``id`` (§7.2). No waivers are applied and no report/exit policy is imposed — that is the
    caller's job — so the CLI and the plugin classify identically.
    """
    reference_nets = config.reference_nets
    min_pour_area = config.for_net().min_pour_area_mm2
    board = parse_board(board_text, reference_nets, min_pour_area_mm2=min_pour_area)
    findings = with_ids(
        check_return_path(
            board,
            reference_nets=reference_nets,
            config=config,
            net_to_netclass=board.net_classes,
        )
    )
    return board, findings


@dataclass(frozen=True)
class CheckResult:
    """A completed live-board check (spec §8) — everything an in-KiCad surface needs.

    * ``board`` — the parsed board (its planes/traces drive the overlay geometry).
    * ``findings`` — the **report set**: active findings (waived ones carried, not dropped,
      §8.1) plus stale waivers surfaced as info. This is what the report formats and the
      panel list.
    * ``raw_findings`` — the pre-waiver findings with ids, kept so the un-waive flow (#24)
      can re-derive the full set independent of the applied sidecar.
    """

    board: Board
    findings: list[Finding]
    raw_findings: list[Finding]


def check_live_board(board_text: str, board_path: str | Path) -> CheckResult:
    """Run the full check on live *board_text*, discovering config + waivers from *board_path*.

    *board_text* is the live board (``Board.get_as_string()``, unsaved edits included, §9);
    *board_path* is the board's on-disk location, used only to discover the project's
    ``return-path.toml`` / ``return-path.waivers.toml`` (walking upward, §6.2/§7.2). The
    plugin has no CLI flags, so config is the discovered file plus built-in defaults.
    """
    path = Path(board_path)
    config = build_config(path)
    board, findings = analyze_board(board_text, config=config)
    waivers = load_waivers(discover_waivers(path))
    result = apply_waivers(findings, waivers)
    report_findings = result.findings + stale_findings(result.stale)
    return CheckResult(board=board, findings=report_findings, raw_findings=findings)
