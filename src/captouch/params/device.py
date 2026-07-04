"""Touch-controller device profiles: the per-chip limits a sensor matrix must
satisfy to be driven by a specific capacitive-touch controller.

The generator is **device-agnostic by default** (``TrackpadParams.device is
None`` → no channel cap, only the AZD068 *layout* rules apply). Selecting a
device profile layers the *chip's* hard limits on top. The Azoteq **IQS550**
(IQS5xx-B000) scans at most a **10 Rx × 15 Tx** matrix (150 nodes): the Rx/Tx
*mapping* registers are 10 and 15 bytes wide (datasheet §5.1.3, ``0x063F–0x0648``
/ ``0x0649–0x0657``), and the datasheet is explicit that Rx and Tx **cannot be
interchanged** — which is exactly the fixed ``Rx = rows`` / ``Tx = cols``
topology this tool emits, so the caps map straight onto ``num_rows`` / ``num_cols``.

This module is pure data — **no KiCad, geometry, or Qt imports**, and it does not
import the widget params (it is imported *by* :mod:`captouch.params.trackpad`),
so it takes an ``error_cls`` to raise rather than importing ``TrackpadError``,
mirroring :func:`captouch.params._validate.require_finite`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DeviceProfile",
    "DEVICES",
    "device_profile",
    "validate_device_matrix",
]


@dataclass(frozen=True)
class DeviceProfile:
    """The channel-count envelope a controller imposes on a sensor matrix.

    Attributes
    ----------
    key:
        CLI / preset token (e.g. ``"iqs550"``).
    name:
        Human-readable controller label.
    max_rx:
        Largest number of **Rx (sense)** lines the chip scans — the tool's
        ``num_rows`` (Rx = rows).
    max_tx:
        Largest number of **Tx (drive)** lines — the tool's ``num_cols``
        (Tx = cols).
    max_nodes:
        Largest number of simultaneously-scanned crossings (``Rx · Tx``); may be
        below ``max_rx · max_tx`` for some parts (it equals it for the IQS550).
    """

    key: str
    name: str
    max_rx: int
    max_tx: int
    max_nodes: int

    def channels_note(self) -> str:
        """One-line summary of the envelope, e.g. for CLI/GUI status text."""
        return f"{self.name}: max {self.max_rx} Rx × {self.max_tx} Tx ({self.max_nodes} nodes)"


#: Supported controllers, keyed by :attr:`DeviceProfile.key`.
DEVICES: dict[str, DeviceProfile] = {
    "iqs550": DeviceProfile(
        key="iqs550",
        name="Azoteq IQS550 (IQS5xx-B000)",
        max_rx=10,  # Rx mapping register 0x063F–0x0648 is 10 bytes (datasheet §5.1.3)
        max_tx=15,  # Tx mapping register 0x0649–0x0657 is 15 bytes (§5.1.3)
        max_nodes=150,  # 10 × 15 (datasheet p1 "150 channels")
    ),
}


def device_profile(key: str, error_cls: type[Exception]) -> DeviceProfile:
    """Look up the :class:`DeviceProfile` for *key*, raising *error_cls* if unknown."""
    try:
        return DEVICES[key]
    except KeyError:
        raise error_cls(
            f"unknown device {key!r}; known devices: {sorted(DEVICES)}"
        ) from None


def validate_device_matrix(
    device: str | None,
    num_rows: int,
    num_cols: int,
    num_nodes: int,
    error_cls: type[Exception],
) -> None:
    """Enforce *device*'s channel caps on an ``num_rows × num_cols`` matrix.

    A ``None`` *device* is the generic (device-agnostic) path and imposes no cap.
    Otherwise the matrix must fit the profile's ``max_rx`` (rows / Rx),
    ``max_tx`` (cols / Tx), and ``max_nodes``; the first breach raises *error_cls*
    with a message naming the chip and its limit.
    """
    if device is None:
        return
    prof = device_profile(device, error_cls)
    if num_rows > prof.max_rx:
        raise error_cls(
            f"num_rows {num_rows} exceeds the {prof.name} maximum of {prof.max_rx} Rx "
            f"(sense) lines — the tool maps rows to Rx, and the chip's Rx mapping is "
            f"{prof.max_rx} channels wide (datasheet §5.1.3)"
        )
    if num_cols > prof.max_tx:
        raise error_cls(
            f"num_cols {num_cols} exceeds the {prof.name} maximum of {prof.max_tx} Tx "
            f"(drive) lines — the tool maps cols to Tx, and the chip's Tx mapping is "
            f"{prof.max_tx} channels wide (datasheet §5.1.3)"
        )
    if num_nodes > prof.max_nodes:
        raise error_cls(
            f"{num_rows}×{num_cols} = {num_nodes} nodes exceeds the {prof.name} "
            f"maximum of {prof.max_nodes} scanned channels"
        )
