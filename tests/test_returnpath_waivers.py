"""Severity model + waiver sidecar tests (issue #21).

Covers the five acceptance criteria for the §7 severity/waiver surface:

1. the three §7.3 suppression tiers are distinct — class ``ignore`` (board-wide), a
   per-finding waiver (one instance), and net exclusion (the whole net);
2. the waiver hash is stable across cosmetic re-runs but lapses when the defect moves more
   than the 0.5 mm grid, the net is renamed, or the reference layer changes;
3. ``--waive HASH --reason`` appends an entry with an auto-stamped author + date;
4. waived findings are carried as ``waived: true`` (never dropped); stale waivers are
   surfaced as ``info`` and only removed by ``--prune-waivers``;
5. ``--fail-on`` counts unwaived findings only — waiving the last error greens the build.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from returnpath.cli import main
from returnpath.detector import Finding, check_return_path
from returnpath.parser import parse_board
from returnpath.waivers import (
    Waiver,
    apply_waivers,
    dump_waivers,
    finding_id,
    load_waivers,
    stale_findings,
    waiver_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"
REF_NETS = ("GND",)


def _finding(**kw) -> Finding:
    base = dict(
        check="split-crossing",
        net="SIG_FAST",
        cls="split-crossing",
        severity="error",
        layer="B.Cu",
        reference_layer="In2.Cu",
        x=30.0,
        y=20.0,
        span_mm=1.0,
        message="…",
    )
    base.update(kw)
    return Finding(**base)  # type: ignore[arg-type]


def _split_error() -> Finding:
    board = parse_board(SPLIT_BOARD.read_text(), REF_NETS)
    findings = check_return_path(board, reference_nets=REF_NETS)
    errors = [replace(f, id=finding_id(f)) for f in findings if f.severity == "error"]
    assert errors, "the split board should carry an error finding"
    return errors[0]


# --------------------------------------------------------------------------- #
# hash identity & lapse-on-change (§7.2) — AC2
# --------------------------------------------------------------------------- #
def test_hash_stable_across_cosmetic_reruns():
    a = _finding(x=30.02, y=20.03, span_mm=1.0, message="one wording")
    # same defect, sub-grid jitter + a different span/message (not hashed) → same id.
    b = _finding(x=30.07, y=19.98, span_mm=2.5, message="reworded", severity="warning")
    assert finding_id(a) == finding_id(b)


def test_hash_lapses_when_defect_moves_past_grid():
    a = _finding(x=30.0, y=20.0)
    b = _finding(x=31.0, y=20.0)  # +1 mm ⇒ two 0.5 mm cells away
    assert finding_id(a) != finding_id(b)


def test_hash_lapses_on_net_rename_and_reference_change():
    base = _finding()
    assert finding_id(base) != finding_id(_finding(net="DDR_CLK"))
    assert finding_id(base) != finding_id(_finding(reference_layer="In1.Cu"))
    assert finding_id(base) != finding_id(_finding(cls="edge-overhang", check="edge-overhang"))


# --------------------------------------------------------------------------- #
# applying waivers (§7.2 / §8.1) — AC4
# --------------------------------------------------------------------------- #
def test_matching_waiver_marks_finding_waived_not_dropped():
    f = _finding()
    fid = finding_id(f)
    result = apply_waivers([f], [Waiver(id=fid, reason="by design")])
    assert len(result.findings) == 1  # carried, never dropped
    assert result.findings[0].waived is True
    assert result.findings[0].waiver_reason == "by design"
    assert result.stale == []


def test_unmatched_waiver_is_stale_info_not_deleted():
    f = _finding()
    result = apply_waivers([f], [Waiver(id="deadbeef", net="OLD", check="split-crossing")])
    assert result.findings[0].waived is False  # the real finding stays active
    assert [w.id for w in result.stale] == ["deadbeef"]
    infos = stale_findings(result.stale)
    assert infos[0].severity == "info"
    assert infos[0].cls == "stale-waiver"


def test_expired_waiver_stops_suppressing_and_is_flagged():
    f = _finding()
    fid = finding_id(f)
    waiver = Waiver(id=fid, reason="temporary", expires="2020-01-01")
    result = apply_waivers([f], [waiver], today="2026-07-09")
    assert result.findings[0].waived is False  # lapsed → active again
    assert [w.id for w in result.stale] == [fid]
    assert "expired" in stale_findings(result.stale, today="2026-07-09")[0].message


# --------------------------------------------------------------------------- #
# round-trip load / dump (§7.2) — feeds --prune-waivers
# --------------------------------------------------------------------------- #
def test_waiver_round_trips_through_toml():
    w = waiver_for(_finding(), "crosses a documented moat", author="Jane Dev", today="2026-07-09")
    text = dump_waivers([w])
    (back,) = load_waivers_from_text(text)
    assert back.id == w.id
    assert back.net == "SIG_FAST"
    assert back.reason == "crosses a documented moat"
    assert back.author == "Jane Dev"
    assert back.date == "2026-07-09"


def load_waivers_from_text(text: str) -> list[Waiver]:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
        fh.write(text)
        path = Path(fh.name)
    return load_waivers(path)


def test_load_rejects_entry_without_id(tmp_path):
    path = tmp_path / "return-path.waivers.toml"
    path.write_text('version = 1\n[[waiver]]\nnet = "X"\n')
    with pytest.raises(Exception, match="id"):
        load_waivers(path)


# --------------------------------------------------------------------------- #
# CLI end-to-end — AC1, AC3, AC4, AC5
# --------------------------------------------------------------------------- #
def test_waive_suppresses_only_that_instance_and_greens_the_build(tmp_path, capsys):
    # SPLIT_BOARD's SIG_FAST split-crossing is the sole error → exit 1 by default (AC5).
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    assert main(["check", str(board)]) == 1

    fid = _split_error().id
    (tmp_path / "return-path.waivers.toml").write_text(
        f'version = 1\n[[waiver]]\nid = "{fid}"\nreason = "reviewed"\n'
    )
    # AC4/AC5: the waived finding is carried (waived) but the build greens.
    assert main(["check", str(board)]) == 0
    out = capsys.readouterr().out
    assert "Waived (1)" in out
    assert fid in out


def test_no_waivers_flag_ignores_the_sidecar(tmp_path, capsys):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    fid = _split_error().id
    (tmp_path / "return-path.waivers.toml").write_text(
        f'version = 1\n[[waiver]]\nid = "{fid}"\nreason = "reviewed"\n'
    )
    # --no-waivers ⇒ the waiver is ignored, the error is live again → exit 1.
    assert main(["check", str(board), "--no-waivers"]) == 1


def test_waive_flag_appends_stamped_entry(tmp_path, capsys):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    fid = _split_error().id
    # AC3: --waive appends an entry with auto-stamped author + date; exit 0 (now waived).
    assert main(["check", str(board), "--waive", fid, "--reason", "crosses moat by design"]) == 0

    sidecar = tmp_path / "return-path.waivers.toml"
    assert sidecar.is_file()
    (entry,) = load_waivers(sidecar)
    assert entry.id == fid
    assert entry.reason == "crosses moat by design"
    assert entry.author  # git user.name auto-stamp
    assert entry.date  # ISO date auto-stamp


def test_waive_creates_new_explicit_sidecar(tmp_path, capsys):
    # --waive to a not-yet-existing explicit --waivers path creates it (no "not found" error).
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    fid = _split_error().id
    sidecar = tmp_path / "custom" / "wv.toml"
    sidecar.parent.mkdir()
    assert (
        main(["check", str(board), "--waivers", str(sidecar), "--waive", fid, "--reason", "ok"])
        == 0
    )
    (entry,) = load_waivers(sidecar)
    assert entry.id == fid


def test_waive_requires_reason(tmp_path, capsys):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    assert main(["check", str(board), "--waive", "abcd1234"]) == 2
    assert "reason" in capsys.readouterr().out


def test_prune_removes_stale_but_keeps_active(tmp_path, capsys):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    fid = _split_error().id
    sidecar = tmp_path / "return-path.waivers.toml"
    sidecar.write_text(
        f"version = 1\n"
        f'[[waiver]]\nid = "{fid}"\nreason = "active"\n'
        f'[[waiver]]\nid = "deadbeef"\nnet = "GHOST"\nreason = "stale"\n'
    )
    # AC4: stale reported as info and NOT deleted without --prune-waivers.
    assert main(["check", str(board)]) == 0
    assert "deadbeef" in capsys.readouterr().out
    assert len(load_waivers(sidecar)) == 2

    # --prune-waivers drops the stale entry, keeps the matching one.
    assert main(["check", str(board), "--prune-waivers"]) == 0
    remaining = load_waivers(sidecar)
    assert [w.id for w in remaining] == [fid]


def test_three_suppression_tiers_are_distinct(tmp_path, capsys):
    # AC1: exclusion (whole net), class ignore (board-wide), and per-finding waiver each
    # green the build, but by different mechanisms — verify all three independently.
    board = tmp_path / "board.kicad_pcb"
    board.write_text(SPLIT_BOARD.read_text())
    fid = _split_error().id

    assert main(["check", str(board), "--exclude", "SIG_FAST"]) == 0  # net exclusion
    assert main(["check", str(board), "--set", "severity.split_crossing=ignore"]) == 0  # ignore

    (tmp_path / "return-path.waivers.toml").write_text(
        f'version = 1\n[[waiver]]\nid = "{fid}"\nreason = "reviewed"\n'
    )
    out_before = _run_capture(["check", str(board)], capsys)
    assert "Waived (1)" in out_before  # per-finding waiver carries the finding…
    # …whereas exclusion/ignore emit nothing for it at all.
    out_excluded = _run_capture(
        ["check", str(board), "--no-waivers", "--exclude", "SIG_FAST"], capsys
    )
    assert "split-crossing" not in out_excluded


def _run_capture(argv: list[str], capsys) -> str:
    main(argv)
    return capsys.readouterr().out
