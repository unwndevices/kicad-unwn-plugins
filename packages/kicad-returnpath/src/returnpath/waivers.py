"""Waiver sidecar — the system of record for accepted findings (spec §7.2).

A project checks in a ``return-path.waivers.toml`` next to (or above) its board; this
module discovers it, loads it, and applies it to a run's findings:

* **Keying (§7.2):** every finding gets a content **hash** of
  ``(check, class, net, layer, reference_layer, quantized-location)`` with the location
  snapped to a **0.5 mm grid** (:func:`finding_id`). A material change — the defect moves
  more than a grid cell, the net is renamed, the reference plane changes — alters the hash,
  so the waiver **lapses → re-review**. Matching is pure hash equality (O(1)); the
  grid-boundary seam fails *safe* (lapse). ``severity`` / ``span_mm`` / ``message`` are
  stored for the human echo but **not** hashed.
* **Applying (§7.2 / §8.1):** a finding whose hash matches an active (non-expired) waiver
  is marked ``waived=True`` and **carried, never dropped**. A waiver matching no current
  finding is **stale** — surfaced as an ``info`` finding, never auto-deleted (only
  ``--prune-waivers`` removes it). An expired waiver stops suppressing and is likewise
  surfaced as ``info``.
* **Provenance (§7.2):** a written entry auto-stamps ``author`` (git ``user.name``) +
  ``date`` alongside the ``reason``; ``--waive`` appends, ``--prune-waivers`` rewrites.

The sidecar is discovered exactly like ``return-path.toml`` (walk upward from the board;
``--waivers PATH`` overrides; ``--no-waivers`` ignores it) so the two configs live side by
side.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .config import tomllib  # reuse the version-guarded tomllib/tomli import
from .detector import Finding

WAIVERS_FILENAME = "return-path.waivers.toml"

# The §7.2 location grid: the finding hash quantizes x/y to this pitch (in mm), so a defect
# that moves less than one cell keeps its waiver and a larger move lapses it.
GRID_MM = 0.5

# Field separator for the hashed key — a control char that cannot appear in a net/layer
# name, so two distinct tuples never collide by concatenation.
_SEP = "\x1f"


class WaiverError(Exception):
    """The waiver sidecar violates its schema (→ CLI exit 2)."""


@dataclass(frozen=True)
class Waiver:
    """One checked-in waiver entry — the hash ``id`` plus its descriptive echo (§7.2)."""

    id: str
    check: str = ""
    cls: str = ""
    net: str = ""
    location: tuple[float, float] | None = None
    span_mm: float | None = None
    severity: str = ""
    message: str = ""
    reason: str = ""
    author: str = ""
    date: str = ""
    expires: str | None = None


@dataclass(frozen=True)
class WaiverResult:
    """The outcome of applying waivers to a run's findings (spec §7.2 / §8.1)."""

    findings: list[Finding]  # every finding, waived ones marked (never dropped)
    stale: list[Waiver]  # waivers matching no current finding (or expired)


# --------------------------------------------------------------------------- #
# finding identity (§7.2)
# --------------------------------------------------------------------------- #
def finding_id(f: Finding) -> str:
    """The content hash keying a finding for waiver matching (§7.2).

    Hashes ``(check, class, net, layer, reference_layer)`` plus the location snapped to the
    :data:`GRID_MM` grid (as integer cell counts, so float noise never shifts the key). A
    material change to any of these lapses the waiver; ``severity`` / ``span`` / ``message``
    are deliberately excluded so a cosmetic re-run is stable.
    """
    gx = round(f.x / GRID_MM)
    gy = round(f.y / GRID_MM)
    key = _SEP.join([f.check, f.cls, f.net, f.layer, f.reference_layer, str(gx), str(gy)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def with_ids(findings: list[Finding]) -> list[Finding]:
    """Stamp each finding with its content-hash :attr:`~Finding.id` (§7.2)."""
    return [replace(f, id=finding_id(f)) for f in findings]


# --------------------------------------------------------------------------- #
# applying waivers (§7.2 / §8.1)
# --------------------------------------------------------------------------- #
def apply_waivers(
    findings: list[Finding], waivers: list[Waiver], *, today: str | None = None
) -> WaiverResult:
    """Mark waived findings and collect stale/expired waivers (§7.2 / §8.1).

    Every finding is stamped with its hash id and carried; one whose id matches an **active**
    (non-expired) waiver is additionally marked ``waived=True`` with the waiver's reason. A
    waiver whose id matches no current finding is **stale**; an **expired** waiver stops
    suppressing — both are returned in :attr:`WaiverResult.stale` and surfaced as ``info``.
    """
    today = today or date.today().isoformat()
    stamped = with_ids(findings)
    present_ids = {f.id for f in stamped}

    active: dict[str, Waiver] = {}
    stale: list[Waiver] = []
    for w in waivers:
        expired = w.expires is not None and w.expires < today
        if expired or w.id not in present_ids:
            stale.append(w)
        else:
            # A duplicate id keeps the first entry (append order is checked-in order).
            active.setdefault(w.id, w)

    out = [
        replace(f, waived=True, waiver_reason=active[f.id].reason) if f.id in active else f
        for f in stamped
    ]
    return WaiverResult(findings=out, stale=stale)


def stale_findings(stale: list[Waiver], *, today: str | None = None) -> list[Finding]:
    """Render stale/expired waivers as ``info`` findings so they are never silent (§7.2)."""
    today = today or date.today().isoformat()
    out: list[Finding] = []
    for w in stale:
        x, y = w.location if w.location is not None else (0.0, 0.0)
        expired = w.expires is not None and w.expires < today
        if expired:
            msg = (
                f"waiver {w.id} for {w.net or '?'} ({w.check or '?'}) expired on {w.expires} "
                f"— the finding is active again; renew or remove the waiver"
            )
        else:
            msg = (
                f"waiver {w.id} for {w.net or '?'} ({w.check or '?'}) matches no current "
                f"finding — stale (re-review, or drop it with --prune-waivers)"
            )
        out.append(
            Finding(
                check="stale-waiver",
                net=w.net,
                cls="stale-waiver",
                severity="info",
                layer="",
                reference_layer="",
                x=x,
                y=y,
                span_mm=0.0,
                message=msg,
                id=w.id,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# discovery & loading (§7.2, mirrors config discovery)
# --------------------------------------------------------------------------- #
def discover_waivers(board_path: Path, explicit: Path | None = None) -> Path | None:
    """Locate the effective ``return-path.waivers.toml`` (§7.2).

    ``--waivers PATH`` wins (and must exist); else the nearest sidecar searching from the
    board's directory upward; else ``None`` (no waivers).
    """
    if explicit is not None:
        if not explicit.is_file():
            raise WaiverError(f"waivers file not found: {explicit}")
        return explicit
    start = board_path.resolve().parent
    for directory in (start, *start.parents):
        candidate = directory / WAIVERS_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_waivers(path: Path | None) -> list[Waiver]:
    """Load + validate the waiver sidecar at *path* (``None`` ⇒ no waivers)."""
    if path is None:
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise WaiverError(f"{path.name}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise WaiverError(f"cannot read {path}: {exc}") from exc
    _check_version(raw.get("version"))
    entries = raw.get("waiver", [])
    if not isinstance(entries, list):
        raise WaiverError("[[waiver]] must be an array of tables")
    return [_waiver_from_table(e, i) for i, e in enumerate(entries)]


def _check_version(value: object) -> None:
    if value is not None and value != 1:
        raise WaiverError(f"unsupported waivers version {value!r} (expected 1)")


def _waiver_from_table(entry: object, index: int) -> Waiver:
    if not isinstance(entry, dict):
        raise WaiverError(f"[[waiver]] #{index + 1} must be a table")
    wid = entry.get("id")
    if not isinstance(wid, str) or not wid:
        raise WaiverError(f"[[waiver]] #{index + 1} is missing a string 'id'")
    loc = entry.get("location")
    location: tuple[float, float] | None = None
    if isinstance(loc, dict) and "x" in loc and "y" in loc:
        location = (float(loc["x"]), float(loc["y"]))
    span = entry.get("span_mm")
    return Waiver(
        id=wid,
        check=str(entry.get("check", "")),
        cls=str(entry.get("class", "")),
        net=str(entry.get("net", "")),
        location=location,
        span_mm=float(span) if isinstance(span, (int, float)) else None,
        severity=str(entry.get("severity", "")),
        message=str(entry.get("message", "")),
        reason=str(entry.get("reason", "")),
        author=str(entry.get("author", "")),
        date=str(entry.get("date", "")),
        expires=str(entry["expires"]) if entry.get("expires") is not None else None,
    )


# --------------------------------------------------------------------------- #
# writing the sidecar — append (--waive) and rewrite (--prune-waivers)
# --------------------------------------------------------------------------- #
def waiver_for(finding: Finding, reason: str, *, author: str, today: str) -> Waiver:
    """Build a full waiver entry echoing *finding*, auto-stamped with author + date (§7.2)."""
    return Waiver(
        id=finding.id or finding_id(finding),
        check=finding.check,
        cls=finding.cls,
        net=finding.net,
        location=(finding.x, finding.y),
        span_mm=finding.span_mm,
        severity=finding.severity,
        message=finding.message,
        reason=reason,
        author=author,
        date=today,
    )


def waiver_from_hash(hash_id: str, reason: str, *, author: str, today: str) -> Waiver:
    """A minimal waiver for a hash with no matching finding this run (§7.2)."""
    return Waiver(id=hash_id, reason=reason, author=author, date=today)


def append_waiver(path: Path, waiver: Waiver) -> None:
    """Append *waiver* to the sidecar at *path*, preserving existing content (§7.2, §10)."""
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if not _has_version_line(text):
            text = "version = 1\n\n" + text
        prefix = text if text.endswith("\n") else text + "\n"
        prefix += "\n"
    else:
        prefix = "version = 1\n\n"
    path.write_text(prefix + _format_block(waiver), encoding="utf-8")


def dump_waivers(waivers: list[Waiver]) -> str:
    """Serialise *waivers* to the full sidecar text — used by ``--prune-waivers`` (§10)."""
    out = ["version = 1", ""]
    for w in waivers:
        out.append(_format_block(w).rstrip("\n"))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _format_block(w: Waiver) -> str:
    lines = ["[[waiver]]", f'id = "{w.id}"']
    if w.check:
        lines.append(f"check = {_toml_str(w.check)}")
    if w.cls:
        lines.append(f"class = {_toml_str(w.cls)}")
    if w.net:
        lines.append(f"net = {_toml_str(w.net)}")
    if w.location is not None:
        lines.append(f"location = {{ x = {w.location[0]:.3f}, y = {w.location[1]:.3f} }}")
    if w.span_mm is not None:
        lines.append(f"span_mm = {w.span_mm:.3f}")
    if w.severity:
        lines.append(f"severity = {_toml_str(w.severity)}")
    if w.message:
        lines.append(f"message = {_toml_str(w.message)}")
    if w.reason:
        lines.append(f"reason = {_toml_str(w.reason)}")
    if w.author:
        lines.append(f"author = {_toml_str(w.author)}")
    if w.date:
        lines.append(f"date = {_toml_str(w.date)}")
    if w.expires:
        lines.append(f"expires = {_toml_str(w.expires)}")
    return "\n".join(lines) + "\n"


def _has_version_line(text: str) -> bool:
    """Whether *text* already declares a top-level ``version`` key (any line, not just the
    first) — appending a second would make the duplicate key a TOML parse error."""
    return any(line.lstrip().startswith("version") and "=" in line for line in text.splitlines())


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# --------------------------------------------------------------------------- #
# provenance stamps (§7.2)
# --------------------------------------------------------------------------- #
def git_author() -> str:
    """The git ``user.name`` for the ``author`` stamp; empty string when unavailable (§7.2)."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def today_stamp() -> str:
    """Today's date as an ISO ``YYYY-MM-DD`` string for the ``date`` stamp (§7.2)."""
    return date.today().isoformat()
