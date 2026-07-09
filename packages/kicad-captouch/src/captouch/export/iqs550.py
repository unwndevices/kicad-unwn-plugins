"""Emit an Azoteq IQS550 (IQS5xx-B000) sensor-configuration C header.

An inscribed circular (or any conform-clipped) diamond trackpad scans a
rectangular ``Total Rx × Total Tx`` matrix on the IQS550, but the rim nodes the
boundary cuts away must be **individually disabled** so the chip does not tune or
report them (datasheet §5.1.2 *Individual Channel Disabling*). This exporter
turns :meth:`TrackpadGeometry.node_enable_map` into the chip's on-wire
representation:

* the **Active channels** register block (``0x067B–0x0698``, 30 bytes) — 15 Tx
  words stored **high byte first**, where (datasheet §8.10.5) *the bits always
  link to Rxs and the registers to Txs*: word ``t`` is Tx ``t``, bit ``r`` is Rx
  ``r``, and ``bit = 1`` enables / ``bit = 0`` disables that node. Words and bits
  beyond the actual ``R×C`` matrix are ``0`` (unimplemented → disabled, as §5.1.2
  requires);
* the **Total Rx / Total Tx** size registers (``0x063D`` / ``0x063E``, §5.1.1).

The output is a firmware-ready C header (``uint8_t`` array + ``#define``\\s) with
the node map drawn in a comment. Two honesty notes are baked into the header and
worth repeating: the byte/bit order should be confirmed against **AZD070** (the
Programming & Data-Streaming Guide) before flashing, and the bitmap assumes the
**identity Rx/Tx mapping** (board rows → Rx0..Rx9 top-to-bottom, cols → Tx0..Tx14
left-to-right). A custom Rx/Tx *mapping* (``0x063F`` / ``0x0649``) permutes the
bits — this tool does not know the pad-to-pin routing, so it leaves mapping alone.

Depends only on the geometry model — no KiCad S-expression or Qt imports.
"""

from __future__ import annotations

import re

from .. import __version__
from ..geometry import TrackpadGeometry
from ..params import DEVICES, DISABLE_AREA_FRACTION

__all__ = [
    "IQS550ConfigError",
    "active_channel_bytes",
    "render_iqs550_config",
    "ACTIVE_CHANNELS_ADDR",
    "TOTAL_RX_ADDR",
    "TOTAL_TX_ADDR",
]

#: IQS5xx-B000 register addresses (datasheet memory map, p34–35).
TOTAL_RX_ADDR = 0x063D
TOTAL_TX_ADDR = 0x063E
ACTIVE_CHANNELS_ADDR = 0x067B

#: The Active-channels block is a fixed 15 Tx words / 30 bytes regardless of the
#: configured Total Tx (datasheet §8.10.5).
_TX_WORDS = 15
_ACTIVE_CHANNELS_BYTES = 2 * _TX_WORDS

#: The device whose register layout this exporter targets.
_IQS550 = DEVICES["iqs550"]


class IQS550ConfigError(ValueError):
    """Raised when a trackpad matrix cannot map onto the IQS550 register layout."""


def _check_fits(geo: TrackpadGeometry) -> tuple[int, int]:
    """Return ``(num_rows, num_cols)`` after checking the matrix fits the IQS550."""
    r, c = geo.params.num_rows, geo.params.num_cols
    if r > _IQS550.max_rx or c > _IQS550.max_tx or geo.params.num_nodes > _IQS550.max_nodes:
        raise IQS550ConfigError(
            f"a {r}×{c} matrix ({geo.params.num_nodes} nodes) does not fit the "
            f"{_IQS550.channels_note()} — reduce num_rows/num_cols or set "
            f"device='iqs550' to catch this at build time"
        )
    return r, c


def active_channel_bytes(geo: TrackpadGeometry, threshold: float = DISABLE_AREA_FRACTION) -> bytes:
    """The 30-byte IQS550 *Active channels* register block for *geo*.

    Word ``t`` (Tx column *t*, high byte first) has bit ``r`` set when node
    ``(Rx r+1, Tx t+1)`` keeps at least *threshold* of its electrode area, per
    :meth:`TrackpadGeometry.node_enable_map`. Words/bits outside the ``R×C``
    matrix are ``0`` (disabled). See the module docstring for the §8.10.5 layout.
    """
    r, c = _check_fits(geo)
    enabled = geo.node_enable_map(threshold)  # [rx_row][tx_col]
    out = bytearray()
    for t in range(_TX_WORDS):
        word = 0
        if t < c:
            for rx in range(r):  # rx < r <= max_rx (10) → always inside a 16-bit word
                if enabled[rx][t]:
                    word |= 1 << rx
        out.append((word >> 8) & 0xFF)  # high byte first (§8.10.5)
        out.append(word & 0xFF)
    return bytes(out)


def _guard_macro(name: str) -> str:
    """A C include-guard identifier derived from the footprint *name*."""
    ident = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").upper() or "IQS550"
    return f"{ident}_CONFIG_H"


def _node_map_comment(enabled: list[list[bool]], r: int, c: int) -> list[str]:
    """The ``#``/``.`` node grid, as C-comment body lines (no leading ``*``)."""
    tx_header = " ".join(f"{t + 1:>2}" for t in range(c))
    corner = "Rx\\Tx"  # kept out of the f-string: no backslashes allowed there on py3.10
    lines = [f"  {corner:>5}  {tx_header}"]
    for rx in range(r):
        cells = " ".join(" #" if enabled[rx][t] else " ." for t in range(c))
        lines.append(f"  {f'Rx{rx + 1}':>5}  {cells}")
    return lines


def render_iqs550_config(geo: TrackpadGeometry, threshold: float = DISABLE_AREA_FRACTION) -> str:
    """Render the firmware-ready IQS550 configuration C header for *geo*.

    Contains the Total Rx/Tx values, the Active-channels ``uint8_t[30]`` array,
    and the enabled/disabled node map drawn in a comment, plus the register
    addresses as ``#define``\\s. Raises :class:`IQS550ConfigError` if the matrix
    exceeds the chip's channel envelope. *threshold* is the disable cut-off
    (default AZD068 §6's 50 %).
    """
    r, c = _check_fits(geo)
    enabled = geo.node_enable_map(threshold)
    data = active_channel_bytes(geo, threshold)
    n_disabled = sum(not e for row in enabled for e in row)
    name = geo.params.name
    guard = _guard_macro(name)
    p = geo.params

    shape = f"{p.mask_shape} mask / {p.clip_mode} clip" if p.mask_shape != "rect" else "rectangular"
    lines: list[str] = []
    lines.append("/*")
    lines.append(f" * {name} — Azoteq IQS550 (IQS5xx-B000) sensor configuration")
    lines.append(f" * Generated by kicad-captouch {__version__}. Do not edit by hand.")
    lines.append(" *")
    lines.append(f" * Sensor: {r} Rx × {c} Tx diamond matrix ({p.num_nodes} nodes), {shape}.")
    lines.append(
        f" * Disabled nodes: {n_disabled} of {p.num_nodes} "
        f"(electrode area cut below {threshold * 100:.0f}% — AZD068 §6 rule of thumb)."
    )
    lines.append(" *")
    lines.append(" * Node map ('#' enabled, '.' disabled; rows = Rx top→bottom, cols = Tx L→R):")
    lines.append(" *")
    lines.extend(f" *{line}" for line in _node_map_comment(enabled, r, c))
    lines.append(" *")
    lines.append(" * Write these to the device after power-up (before AUTO_ATI), per AZD070. The")
    lines.append(" * Rx/Tx MAPPING registers (0x063F / 0x0649) are left at their defaults; this")
    lines.append(" * bitmap assumes the identity mapping (rows→Rx0.., cols→Tx0..). If you route")
    lines.append(" * the pads to different chip pins, permute the bits to match.")
    lines.append(" *")
    lines.append(" * !! VERIFY the byte/bit order against AZD070 before flashing: register/word")
    lines.append(" *    → Tx, bit → Rx, high byte first, Active-channels bit=1 enabled/0")
    lines.append(" *    disabled (datasheet §8.10.5).")
    lines.append(" */")
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append(
        f"#define IQS550_TOTAL_RX           {r}      /* reg 0x{TOTAL_RX_ADDR:04X} (§5.1.1) */"
    )
    lines.append(
        f"#define IQS550_TOTAL_TX           {c}      /* reg 0x{TOTAL_TX_ADDR:04X} (§5.1.1) */"
    )
    lines.append(f"#define IQS550_TOTAL_RX_ADDR      0x{TOTAL_RX_ADDR:04X}u")
    lines.append(f"#define IQS550_TOTAL_TX_ADDR      0x{TOTAL_TX_ADDR:04X}u")
    lines.append(
        f"#define IQS550_ACTIVE_CHANNELS_ADDR 0x{ACTIVE_CHANNELS_ADDR:04X}u"
        f"  /* {_ACTIVE_CHANNELS_BYTES} bytes (§5.1.2 / §8.10.5) */"
    )
    lines.append("")
    lines.append("/* Active channels: 15 Tx words, high byte first; bit r = Rx r, 1 = enabled. */")
    lines.append(f"static const uint8_t iqs550_active_channels[{_ACTIVE_CHANNELS_BYTES}] = {{")
    for t in range(_TX_WORDS):
        hi, lo = data[2 * t], data[2 * t + 1]
        if t < c:
            bits = "".join("#" if enabled[rx][t] else "." for rx in range(r))
            note = f"Tx{t + 1:<2} Rx[1..{r}]={bits}"
        else:
            note = f"Tx{t + 1:<2} (unused)"
        lines.append(f"    0x{hi:02X}, 0x{lo:02X},  /* {note} */")
    lines.append("};")
    lines.append("")
    lines.append(f"#endif /* {guard} */")
    return "\n".join(lines) + "\n"
