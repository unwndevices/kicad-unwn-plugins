"""JSON, SVG overlay, and HTML report-format tests (issue #22).

Covers the five acceptance criteria for the §8 report surface:

1. JSON is a list of canonical finding records; waived entries carry ``waived: true`` +
   ``reason`` (never silently dropped);
2. the SVG overlay renders copper islands, traces, and numbered severity-coloured
   crosshairs, with waived findings visibly muted;
3. the HTML report is self-contained (overlay + list inline) and opens standalone;
4. ``--format`` accepts multiple formats, ``--out-dir`` writes all of them, ``--output``
   writes one;
5. every format consumes the same finding record — no format-specific data divergence.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from returnpath.cli import main
from returnpath.detector import Finding, check_return_path
from returnpath.parser import parse_board
from returnpath.report import (
    finding_record,
    format_html_report,
    format_json_report,
    format_svg_report,
    render_report,
)
from returnpath.waivers import finding_id

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"
REF_NETS = ("GND",)


@pytest.fixture
def board():
    return parse_board(SPLIT_BOARD.read_text(), REF_NETS)


@pytest.fixture
def findings(board):
    fs = check_return_path(board, reference_nets=REF_NETS)
    return [replace(f, id=finding_id(f)) for f in fs]


def _waive_one(findings: list[Finding]) -> list[Finding]:
    """Mark the first error waived (as the CLI's apply_waivers would), leaving the rest."""
    out: list[Finding] = []
    waived_one = False
    for f in findings:
        if not waived_one and f.severity == "error":
            out.append(replace(f, waived=True, waiver_reason="reviewed — acceptable"))
            waived_one = True
        else:
            out.append(f)
    assert waived_one, "the split board should carry an error to waive"
    return out


# --------------------------------------------------------------------------- #
# JSON (§8.2) — AC1
# --------------------------------------------------------------------------- #
def test_json_is_a_list_of_canonical_records(findings):
    payload = json.loads(format_json_report("split_board.kicad_pcb", findings))
    assert isinstance(payload, list)
    assert len(payload) == len(findings)
    rec = payload[0]
    # the canonical record fields (§8.1) are all present.
    for key in (
        "check",
        "net",
        "class",
        "severity",
        "layer",
        "reference_layer",
        "location",
        "span_mm",
        "message",
    ):
        assert key in rec, key
    assert set(rec["location"]) == {"x", "y"}


def test_json_waived_entry_carries_flag_and_reason(findings):
    payload = json.loads(format_json_report("b", _waive_one(findings)))
    waived = [r for r in payload if r.get("waived")]
    assert len(waived) == 1
    assert waived[0]["waived"] is True
    assert waived[0]["reason"] == "reviewed — acceptable"
    # unwaived records don't carry the waiver keys.
    assert all("reason" not in r for r in payload if not r.get("waived"))


def test_json_never_drops_waived(findings):
    waived = _waive_one(findings)
    payload = json.loads(format_json_report("b", waived))
    assert len(payload) == len(waived)  # waived still present, not dropped


# --------------------------------------------------------------------------- #
# SVG overlay (§8.2) — AC2
# --------------------------------------------------------------------------- #
def test_svg_renders_islands_traces_and_numbered_crosshairs(board, findings):
    svg = format_svg_report("split_board.kicad_pcb", findings, board)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "<path" in svg  # copper islands
    assert "<polyline" in svg  # traces
    assert "<circle" in svg  # crosshair rings
    # each finding is numbered 1..N.
    for n in range(1, len(findings) + 1):
        assert f">{n}</text>" in svg


def test_svg_severity_colours_and_waived_muted(board, findings):
    # unwaived: the error finding is drawn severity-red.
    assert "#d23b3b" in format_svg_report("b", findings, board)
    # waived: the finding is muted grey and drawn hollow/dashed.
    svg = format_svg_report("b", _waive_one(findings), board)
    assert "#9aa0a6" in svg
    assert "stroke-dasharray" in svg


def test_svg_viewbox_covers_geometry(board, findings):
    svg = format_svg_report("b", findings, board)
    assert 'viewBox="' in svg
    assert "mm" in svg  # dimensions carried in board millimetres


def test_svg_is_well_formed_xml(board, findings):
    # rasterizability (§8.2) rests on the SVG being valid XML.
    ET.fromstring(format_svg_report("b", _waive_one(findings), board))


# --------------------------------------------------------------------------- #
# HTML (§8.2) — AC3
# --------------------------------------------------------------------------- #
def test_html_is_self_contained(board, findings):
    html = format_html_report("split_board.kicad_pcb", findings, board)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<svg" in html  # overlay embedded inline
    assert "<table" in html  # finding list inline
    # no external asset references.
    assert "src=" not in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")


def test_html_escapes_and_sections_waived(board, findings):
    html = format_html_report("b", _waive_one(findings), board)
    assert 'class="waived"' in html
    assert "reviewed — acceptable" in html


# --------------------------------------------------------------------------- #
# shared record — no divergence (§8.1) — AC5
# --------------------------------------------------------------------------- #
def test_all_formats_consume_the_same_record(board, findings):
    rec = finding_record(findings[0])
    text = render_report("text", "b", findings, board)
    js = render_report("json", "b", findings, board)
    html = render_report("html", "b", findings, board)
    # net + message from the one record show up across formats.
    for out in (text, js, html):
        assert rec["net"] in out
    assert rec["message"] in text
    assert json.loads(js)[0] == finding_record(_ordered_first(findings))


def _ordered_first(findings: list[Finding]) -> Finding:
    from returnpath.report import _ordered

    return _ordered(findings)[0]


# --------------------------------------------------------------------------- #
# CLI plumbing (§10) — AC4
# --------------------------------------------------------------------------- #
def test_cli_default_format_is_text(capsys):
    assert main(["check", str(SPLIT_BOARD)]) == 1
    out = capsys.readouterr().out
    assert "return-path check:" in out


def test_cli_json_to_stdout(capsys):
    main(["check", str(SPLIT_BOARD), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and payload


def test_cli_output_writes_single_format(tmp_path, capsys):
    dest = tmp_path / "report.json"
    main(["check", str(SPLIT_BOARD), "--format", "json", "--output", str(dest)])
    assert dest.is_file()
    assert isinstance(json.loads(dest.read_text()), list)


def test_cli_out_dir_writes_all_formats(tmp_path, capsys):
    out = tmp_path / "reports"
    rc = main(["check", str(SPLIT_BOARD), "--format", "text,json,svg,html", "--out-dir", str(out)])
    assert rc == 1  # exit code unaffected by output routing
    written = {p.suffix for p in out.iterdir()}
    assert written == {".txt", ".json", ".svg", ".html"}


def test_cli_format_repeatable_and_comma_separated(tmp_path):
    out = tmp_path / "r"
    main(
        [
            "check",
            str(SPLIT_BOARD),
            "--format",
            "json",
            "--format",
            "svg,html",
            "--out-dir",
            str(out),
        ]
    )
    assert {p.suffix for p in out.iterdir()} == {".json", ".svg", ".html"}


def test_cli_unknown_format_is_usage_error(capsys):
    assert main(["check", str(SPLIT_BOARD), "--format", "pdf"]) == 2
    assert "unknown format" in capsys.readouterr().out


def test_cli_multiple_formats_to_stdout_is_error(capsys):
    assert main(["check", str(SPLIT_BOARD), "--format", "json,svg"]) == 2
    assert "--out-dir" in capsys.readouterr().out
