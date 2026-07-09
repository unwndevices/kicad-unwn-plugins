"""Layered TOML configuration model tests (issue #19).

Covers the five acceptance criteria for the §6/§10 config surface:

1. discovery finds the nearest ``return-path.toml`` upward from the board; ``--config``
   overrides; absence falls back to built-in defaults;
2. most-specific-wins precedence resolves ``[net."X"]`` over ``[netclass.Y]`` over
   ``[defaults]`` over the tool defaults;
3. net selection honours the ``victims`` formula — exclude by net *or* netclass, include
   force-in;
4. ``--set KEY=VALUE`` and the ``--reference-nets`` / ``--include`` / ``--exclude`` flags
   override file values for one run;
5. an invalid config key/value is a usage error (exit 2), not a silent default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from returnpath.cli import main
from returnpath.config import (
    DEFAULT_REFERENCE_NETS,
    Config,
    ConfigError,
    build_config,
    discover_config,
    load_config,
)
from returnpath.parser import parse_board

FIXTURES = Path(__file__).parent / "fixtures" / "returnpath"
SPLIT_BOARD = FIXTURES / "split_board.kicad_pcb"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# discovery (§6.2) — AC1
# --------------------------------------------------------------------------- #
def test_discovery_finds_nearest_upward(tmp_path):
    _write(tmp_path / "return-path.toml", "version = 1\n")
    board = tmp_path / "hw" / "board.kicad_pcb"
    board.parent.mkdir()
    board.touch()
    assert discover_config(board) == tmp_path / "return-path.toml"


def test_discovery_prefers_closest(tmp_path):
    _write(tmp_path / "return-path.toml", "version = 1\n")
    sub = tmp_path / "hw"
    sub.mkdir()
    near = _write(sub / "return-path.toml", "version = 1\n")
    board = sub / "board.kicad_pcb"
    board.touch()
    assert discover_config(board) == near


def test_explicit_config_wins_and_must_exist(tmp_path):
    explicit = _write(tmp_path / "custom.toml", "version = 1\n")
    board = tmp_path / "board.kicad_pcb"
    board.touch()
    assert discover_config(board, explicit) == explicit
    with pytest.raises(ConfigError):
        discover_config(board, tmp_path / "missing.toml")


def test_absence_falls_back_to_defaults(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.touch()
    assert discover_config(board) is None
    config = load_config(None)
    assert config.reference_nets == DEFAULT_REFERENCE_NETS


# --------------------------------------------------------------------------- #
# precedence (§6.2) — AC2
# --------------------------------------------------------------------------- #
def _layered_config() -> Config:
    return Config.from_toml(
        {
            "defaults": {"edge_clearance_mm": 0.5, "min_crossing_span_mm": 0.1},
            "netclass": {"HighSpeed": {"edge_clearance_mm": 0.3}},
            "net": {
                "DDR_CLK": {
                    "edge_clearance_mm": 0.2,
                    "severity": {"reference_change": "warning"},
                }
            },
        }
    )


def test_most_specific_threshold_wins():
    config = _layered_config()
    # net > netclass > defaults > tool default
    assert config.for_net("DDR_CLK", "HighSpeed").edge_clearance_mm == 0.2
    assert config.for_net("OTHER", "HighSpeed").edge_clearance_mm == 0.3
    assert config.for_net("OTHER", "Default").edge_clearance_mm == 0.5
    # a threshold not set anywhere falls through to the tool default (§5.2).
    assert config.for_net("OTHER").return_via_distance_mm == 2.0


def test_severity_precedence_and_default():
    config = _layered_config()
    assert config.for_net("DDR_CLK").severity_for("reference-change") == "warning"
    # a net without an override keeps the §4.4 default (reference-change → info).
    assert config.for_net("OTHER").severity_for("reference-change") == "info"


# --------------------------------------------------------------------------- #
# net selection / victims (§6.1) — AC3
# --------------------------------------------------------------------------- #
def test_victims_excludes_reference_nets():
    config = Config(reference_nets=("GND",))
    assert config.victims({"GND", "SIG_A", "SIG_B"}) == {"SIG_A", "SIG_B"}


def test_victims_excludes_by_net_and_netclass():
    config = Config(reference_nets=("GND",), exclude=("SIG_A", "HighSpeed"))
    signal = {"GND", "SIG_A", "SIG_B", "SIG_C"}
    net_to_netclass = {"SIG_B": "HighSpeed"}
    # SIG_A excluded by name, SIG_B excluded by its netclass; SIG_C survives.
    assert config.victims(signal, net_to_netclass) == {"SIG_C"}


def test_victims_include_forces_back_in():
    config = Config(reference_nets=("GND",), exclude=("SIG_A",), include=("SIG_A", "GHOST"))
    signal = {"GND", "SIG_A", "SIG_B"}
    # include re-adds the excluded SIG_A; GHOST isn't on the board so it's ignored.
    assert config.victims(signal) == {"SIG_A", "SIG_B"}


# --------------------------------------------------------------------------- #
# CLI overrides (§10) — AC4
# --------------------------------------------------------------------------- #
def test_set_override_wins_over_file(tmp_path):
    _write(tmp_path / "return-path.toml", "[defaults]\nmin_crossing_span_mm = 0.5\n")
    board = tmp_path / "board.kicad_pcb"
    board.touch()
    config = build_config(
        board, sets=["min_crossing_span_mm=0.9", "severity.split_crossing=warning"]
    )
    assert config.for_net().min_crossing_span_mm == 0.9
    assert config.for_net().severity_for("split-crossing") == "warning"


def test_flags_override_selection(tmp_path):
    _write(
        tmp_path / "return-path.toml",
        '[defaults]\nreference_nets = ["GND"]\nexclude = ["SIG_A"]\n',
    )
    board = tmp_path / "board.kicad_pcb"
    board.touch()
    config = build_config(
        board,
        reference_nets=("GND", "+3V3"),
        exclude=("SIG_B",),
        include=("SIG_C",),
    )
    assert config.reference_nets == ("GND", "+3V3")
    assert config.exclude == ("SIG_B",)  # replaced, not merged
    assert config.include == ("SIG_C",)


def test_cli_set_severity_downgrades_the_build(capsys):
    # SPLIT_BOARD's SIG_FAST is a split-crossing (error) → exit 1 by default…
    assert main(["check", str(SPLIT_BOARD)]) == 1
    # …demote the class to a warning for this run and the build greens (fail-on error).
    assert main(["check", str(SPLIT_BOARD), "--set", "severity.split_crossing=warning"]) == 0


def test_cli_exclude_flag_drops_the_finding(capsys):
    # Excluding SIG_FAST removes the only error → exit 0.
    assert main(["check", str(SPLIT_BOARD), "--exclude", "SIG_FAST"]) == 0


def test_config_file_severity_ignore_emits_nothing(tmp_path, capsys):
    board = _write(tmp_path / "board.kicad_pcb", SPLIT_BOARD.read_text())
    _write(
        tmp_path / "return-path.toml",
        '[defaults.severity]\nsplit_crossing = "ignore"\nedge_overhang = "ignore"\n',
    )
    assert main(["check", str(board)]) == 0
    out = capsys.readouterr().out
    assert "split-crossing" not in out  # the ignored class emits nothing anywhere (§7.1)


# --------------------------------------------------------------------------- #
# validation (§6.3) — AC5
# --------------------------------------------------------------------------- #
def test_unknown_key_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        Config.from_toml({"defaults": {"min_crosing_span_mm": 0.1}})


def test_unknown_top_level_section_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        Config.from_toml({"widgets": {}})


def test_bad_severity_level_rejected():
    with pytest.raises(ConfigError, match="error|warning|info|ignore"):
        Config.from_toml({"defaults": {"severity": {"split_crossing": "fatal"}}})


def test_unknown_severity_class_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        Config.from_toml({"defaults": {"severity": {"split_crosing": "error"}}})


def test_non_numeric_threshold_rejected():
    with pytest.raises(ConfigError, match="number"):
        Config.from_toml({"defaults": {"min_crossing_span_mm": "wide"}})


def test_bad_set_syntax_rejected():
    with pytest.raises(ConfigError):
        Config().with_overrides(sets=["min_crossing_span_mm"])  # no '='
    with pytest.raises(ConfigError, match="unknown key"):
        Config().with_overrides(sets=["bogus_key=1"])
    with pytest.raises(ConfigError, match="number"):
        Config().with_overrides(sets=["min_crossing_span_mm=wide"])


def test_cli_exit_2_on_invalid_config(tmp_path, capsys):
    _write(tmp_path / "return-path.toml", "[defaults]\nbogus = 1\n")
    board = _write(tmp_path / "board.kicad_pcb", SPLIT_BOARD.read_text())
    assert main(["check", str(board)]) == 2
    assert "unknown key" in capsys.readouterr().out


def test_cli_exit_2_on_missing_explicit_config(capsys):
    assert main(["check", str(SPLIT_BOARD), "--config", "/no/such.toml"]) == 2
    assert "not found" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# netclass membership parsing (§6.1) — feeds exclude-by-netclass end to end
# --------------------------------------------------------------------------- #
def test_parse_net_classes_from_board():
    board = parse_board(_board_with_netclass(), ("GND",))
    assert board.net_classes == {"SIG": "HighSpeed"}


def test_cli_exclude_by_netclass(tmp_path, capsys):
    board = _write(tmp_path / "board.kicad_pcb", _board_with_netclass())
    # SIG (netclass HighSpeed) splits the GND plane → error by default.
    assert main(["check", str(board), "--reference-nets", "GND"]) == 1
    # Excluding the netclass by name drops SIG's finding → clean.
    assert main(["check", str(board), "--reference-nets", "GND", "--exclude", "HighSpeed"]) == 0


def _board_with_netclass() -> str:
    """A minimal board whose SIG net belongs to the HighSpeed netclass and splits a plane."""
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        '\t(generator "returnpath-fixture")\n'
        '\t(net 0 "")\n'
        '\t(net 1 "GND")\n'
        '\t(net 2 "SIG")\n'
        '\t(net_class "HighSpeed" "fast nets"\n'
        '\t\t(add_net "SIG")\n'
        "\t)\n"
        "\t(segment\n"
        "\t\t(start 30 10)\n"
        "\t\t(end 30 30)\n"
        "\t\t(width 0.25)\n"
        '\t\t(layer "B.Cu")\n'
        '\t\t(net "SIG")\n'
        "\t)\n"
        "\t(zone\n"
        '\t\t(net "GND")\n'
        '\t\t(layers "In2.Cu")\n'
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts (xy 2 2) (xy 58 2) (xy 58 18) (xy 2 18))\n"
        "\t\t)\n"
        "\t\t(filled_polygon\n"
        '\t\t\t(layer "In2.Cu")\n'
        "\t\t\t(pts (xy 2 22) (xy 58 22) (xy 58 38) (xy 2 38))\n"
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )
