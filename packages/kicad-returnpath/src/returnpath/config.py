"""Layered TOML configuration model (spec §6, §10).

A project checks in a ``return-path.toml`` next to (or above) its board; this module
discovers it, validates it, and resolves the **effective** thresholds/severities for a
given net under the §6.2 precedence::

    tool defaults → [defaults] → [netclass.<NAME>] → [net."<NAME>"] → CLI overrides

and computes the §6.1 victim net set::

    victims  = all_signal_nets − reference_nets − exclude(net|netclass) + include(net)

The concrete schema (§6.3) is:

    version = 1
    [defaults]
    reference_nets = ["GND", "+3V3", "+5V"]   # net selection (§6.1)
    include = []                               # force-check these nets
    exclude = []                               # skip these nets or netclasses
    min_pour_area_mm2 = 1.0                     # thresholds (§5.2)
    …                                          # edge_clearance_mm omitted ⇒ the formula
    [defaults.severity]                        # one of error|warning|info|ignore
    split_crossing = "error"
    …
    [netclass.HighSpeed]                       # override layers — same keys
    edge_clearance_mm = 0.30
    [net."DDR_CLK"]
    severity.reference_change = "warning"

Anything outside this schema (an unknown key, a non-numeric threshold, a bogus severity
level) raises :class:`ConfigError`, which the CLI turns into a usage error (exit 2) rather
than a silent default (§10 AC).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the <3.11 backport
    import tomli as tomllib

CONFIG_FILENAME = "return-path.toml"

# --------------------------------------------------------------------------- #
# schema constants (§5.2 / §6.3)
# --------------------------------------------------------------------------- #
# Threshold defaults; ``edge_clearance_mm`` is ``None`` ⇒ the max(3H, 90 mil, 1×W)
# formula (§5.2), a scalar overrides it with a flat floor.
THRESHOLD_DEFAULTS: dict[str, float | None] = {
    "min_pour_area_mm2": 1.0,
    "min_crossing_span_mm": 0.1,
    "sliver_ignore_area_mm2": 0.0065,
    "return_via_distance_mm": 2.0,
    "sampling_tolerance_mm": 0.05,
    "edge_clearance_mm": None,
}
THRESHOLD_KEYS = frozenset(THRESHOLD_DEFAULTS)

# §7.1 severity vocabulary + the per-class defaults (§4.4 / §6.3).
SEVERITY_LEVELS = frozenset({"error", "warning", "info", "ignore"})
SEVERITY_DEFAULTS: dict[str, str] = {
    "split_crossing": "error",
    "missing_return_via": "error",
    "edge_clearance": "warning",
    "edge_overhang": "warning",
    "reference_change": "info",
}
SEVERITY_KEYS = frozenset(SEVERITY_DEFAULTS)

# Map a detector finding class to its §6.3 severity config key. ``no-reference`` shares
# the ``edge_overhang`` knob — both are the §4.4 "unreferenced over-run" warning.
CLS_TO_SEVERITY_KEY: dict[str, str] = {
    "split-crossing": "split_crossing",
    "reference-change": "reference_change",
    "edge-overhang": "edge_overhang",
    "no-reference": "edge_overhang",
    "edge-clearance": "edge_clearance",
    "missing-return-via": "missing_return_via",
}

# Default reference nets (§4.2 / §6.3): GND + the common power rails.
DEFAULT_REFERENCE_NETS: tuple[str, ...] = ("GND", "+3V3", "+5V")


class ConfigError(Exception):
    """The config file / CLI override violates the §6.3 schema (→ CLI exit 2)."""


@dataclass(frozen=True)
class ResolvedNetConfig:
    """The effective thresholds + severities for one net, after precedence resolution."""

    min_pour_area_mm2: float
    min_crossing_span_mm: float
    sliver_ignore_area_mm2: float
    return_via_distance_mm: float
    sampling_tolerance_mm: float
    edge_clearance_mm: float | None
    severity: Mapping[str, str]

    def severity_for(self, cls: str) -> str:
        """The severity level for a detector finding *cls* (``split-crossing`` → …)."""
        return self.severity[CLS_TO_SEVERITY_KEY[cls]]


@dataclass(frozen=True)
class _Layer:
    """A single override layer — the (partial) thresholds + severities it sets."""

    thresholds: Mapping[str, float | None] = field(default_factory=dict)
    severity: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    """The resolved, validated configuration — net selection + the override layers."""

    reference_nets: tuple[str, ...] = DEFAULT_REFERENCE_NETS
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    defaults: _Layer = field(default_factory=_Layer)
    netclasses: Mapping[str, _Layer] = field(default_factory=dict)
    nets: Mapping[str, _Layer] = field(default_factory=dict)
    cli: _Layer = field(default_factory=_Layer)

    @staticmethod
    def from_toml(data: Mapping[str, object]) -> Config:
        """Validate a parsed-TOML mapping into a :class:`Config` (§6.3)."""
        return _config_from_toml(data)

    # ----------------------------------------------------------------- #
    # resolution (§6.2)
    # ----------------------------------------------------------------- #
    def for_net(self, net: str | None = None, netclass: str | None = None) -> ResolvedNetConfig:
        """Resolve the effective config for *net* (of *netclass*) under §6.2 precedence.

        ``for_net()`` with no net yields the pure tool-defaults-plus-``[defaults]`` view —
        used for board-wide knobs (``min_pour_area_mm2``, the geometric tolerance).
        """
        thresholds: dict[str, float | None] = dict(THRESHOLD_DEFAULTS)
        severity: dict[str, str] = dict(SEVERITY_DEFAULTS)

        layers = [self.defaults]
        if netclass is not None and netclass in self.netclasses:
            layers.append(self.netclasses[netclass])
        if net is not None and net in self.nets:
            layers.append(self.nets[net])
        layers.append(self.cli)
        for layer in layers:
            thresholds.update(layer.thresholds)
            severity.update(layer.severity)

        return ResolvedNetConfig(
            min_pour_area_mm2=_as_float(thresholds["min_pour_area_mm2"]),
            min_crossing_span_mm=_as_float(thresholds["min_crossing_span_mm"]),
            sliver_ignore_area_mm2=_as_float(thresholds["sliver_ignore_area_mm2"]),
            return_via_distance_mm=_as_float(thresholds["return_via_distance_mm"]),
            sampling_tolerance_mm=_as_float(thresholds["sampling_tolerance_mm"]),
            edge_clearance_mm=thresholds["edge_clearance_mm"],
            severity=severity,
        )

    # ----------------------------------------------------------------- #
    # net selection (§6.1)
    # ----------------------------------------------------------------- #
    def victims(
        self,
        signal_nets: set[str],
        net_to_netclass: Mapping[str, str] | None = None,
    ) -> set[str]:
        """The nets to check: ``signal − reference − exclude(net|netclass) + include`` (§6.1)."""
        net_to_netclass = net_to_netclass or {}
        reference = set(self.reference_nets)
        exclude = set(self.exclude)

        victims = set(signal_nets) - reference
        for net in list(victims):
            netclass = net_to_netclass.get(net)
            if net in exclude or (netclass is not None and netclass in exclude):
                victims.discard(net)
        # Force-in wins over exclusion, but only for nets that actually exist on the board.
        victims |= {net for net in self.include if net in signal_nets}
        return victims

    # ----------------------------------------------------------------- #
    # one-off CLI overrides (§10)
    # ----------------------------------------------------------------- #
    def with_overrides(
        self,
        *,
        reference_nets: tuple[str, ...] | None = None,
        include: tuple[str, ...] | None = None,
        exclude: tuple[str, ...] | None = None,
        sets: list[str] | None = None,
    ) -> Config:
        """Return a copy with the CLI flags applied — they win over the file (§6.2)."""
        cli = _parse_set_overrides(sets) if sets else self.cli
        return replace(
            self,
            reference_nets=self.reference_nets if reference_nets is None else reference_nets,
            include=self.include if include is None else include,
            exclude=self.exclude if exclude is None else exclude,
            cli=cli,
        )


# --------------------------------------------------------------------------- #
# discovery & loading (§6.2)
# --------------------------------------------------------------------------- #
def discover_config(board_path: Path, explicit: Path | None = None) -> Path | None:
    """Locate the effective ``return-path.toml`` (§6.2).

    ``--config PATH`` wins (and must exist); else the nearest ``return-path.toml`` searching
    from the board's directory upward to the filesystem root; else ``None`` (defaults).
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        return explicit
    start = board_path.resolve().parent
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None) -> Config:
    """Load + validate the config at *path* (``None`` ⇒ built-in defaults)."""
    if path is None:
        return Config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    return Config.from_toml(raw)


def build_config(
    board_path: Path,
    *,
    explicit: Path | None = None,
    reference_nets: tuple[str, ...] | None = None,
    include: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] | None = None,
    sets: list[str] | None = None,
) -> Config:
    """Discover, load, validate, then apply the one-off CLI overrides — the CLI entry."""
    config = load_config(discover_config(board_path, explicit))
    return config.with_overrides(
        reference_nets=reference_nets, include=include, exclude=exclude, sets=sets
    )


# --------------------------------------------------------------------------- #
# TOML → Config (§6.3 schema validation)
# --------------------------------------------------------------------------- #
def _config_from_toml(data: Mapping[str, object]) -> Config:
    _reject_unknown(data, {"version", "defaults", "netclass", "net"}, "top level")
    _check_version(data.get("version"))

    defaults_raw = _as_table(data.get("defaults", {}), "[defaults]")
    reference_nets = _string_list(defaults_raw.get("reference_nets"), "reference_nets")
    include = _string_list(defaults_raw.get("include"), "include")
    exclude = _string_list(defaults_raw.get("exclude"), "exclude")
    defaults = _layer_from_table(
        {k: v for k, v in defaults_raw.items() if k not in _SELECTION_KEYS},
        "[defaults]",
    )

    netclasses = {
        name: _layer_from_table(_as_table(body, f"[netclass.{name}]"), f"[netclass.{name}]")
        for name, body in _as_table(data.get("netclass", {}), "[netclass]").items()
    }
    nets = {
        name: _layer_from_table(_as_table(body, f'[net."{name}"]'), f'[net."{name}"]')
        for name, body in _as_table(data.get("net", {}), "[net]").items()
    }

    return Config(
        reference_nets=reference_nets if reference_nets is not None else DEFAULT_REFERENCE_NETS,
        include=include or (),
        exclude=exclude or (),
        defaults=defaults,
        netclasses=netclasses,
        nets=nets,
    )


_SELECTION_KEYS = frozenset({"reference_nets", "include", "exclude"})


def _layer_from_table(table: Mapping[str, object], where: str) -> _Layer:
    """Validate one override table into a :class:`_Layer` (thresholds + severity)."""
    _reject_unknown(table, THRESHOLD_KEYS | {"severity"}, where)
    thresholds = {
        key: _as_number(table[key], f"{where} {key}") for key in table if key in THRESHOLD_KEYS
    }
    severity = _severity_table(table.get("severity"), where)
    return _Layer(thresholds=thresholds, severity=severity)


def _severity_table(value: object, where: str) -> dict[str, str]:
    if value is None:
        return {}
    table = _as_table(value, f"{where} severity")
    _reject_unknown(table, SEVERITY_KEYS, f"{where} [severity]")
    return {key: _as_severity(table[key], f"{where} severity.{key}") for key in table}


# --------------------------------------------------------------------------- #
# --set KEY=VALUE overrides (§10)
# --------------------------------------------------------------------------- #
def _parse_set_overrides(sets: list[str]) -> _Layer:
    """Parse repeated ``--set KEY=VALUE`` into a top-precedence :class:`_Layer`.

    ``KEY`` is a threshold key (``min_crossing_span_mm=0.2``) or ``severity.<class>``
    (``severity.split_crossing=warning``); anything else is a usage error.
    """
    thresholds: dict[str, float | None] = {}
    severity: dict[str, str] = {}
    for item in sets:
        if "=" not in item:
            raise ConfigError(f"--set expects KEY=VALUE, got {item!r}")
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if key.startswith("severity."):
            cls = key[len("severity.") :]
            if cls not in SEVERITY_KEYS:
                raise ConfigError(f"--set: unknown severity class {cls!r}")
            severity[cls] = _as_severity(value, f"--set {key}")
        elif key in THRESHOLD_KEYS:
            thresholds[key] = _parse_number(value, f"--set {key}")
        else:
            raise ConfigError(f"--set: unknown key {key!r}")
    return _Layer(thresholds=thresholds, severity=severity)


# --------------------------------------------------------------------------- #
# validation helpers
# --------------------------------------------------------------------------- #
def _reject_unknown(
    table: Mapping[str, object], allowed: frozenset[str] | set[str], where: str
) -> None:
    unknown = [key for key in table if key not in allowed]
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(sorted(unknown))}")


def _check_version(value: object) -> None:
    if value is not None and value != 1:
        raise ConfigError(f"unsupported config version {value!r} (expected 1)")


def _as_table(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where} must be a table")
    return value


def _string_list(value: object, where: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _as_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number, got {value!r}")
    return float(value)


def _parse_number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise ConfigError(f"{where} must be a number, got {text!r}") from exc


def _as_float(value: float | None) -> float:
    # Only the non-``edge_clearance_mm`` thresholds flow here; all carry a numeric default.
    assert value is not None
    return value


def _as_severity(value: object, where: str) -> str:
    if value not in SEVERITY_LEVELS:
        raise ConfigError(f"{where} must be one of error|warning|info|ignore, got {value!r}")
    assert isinstance(value, str)
    return value
