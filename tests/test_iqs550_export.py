"""IQS550 sensor-config export: Active-channels bitmap packing and C header."""

from __future__ import annotations

import pytest

from captouch.export.iqs550 import (
    ACTIVE_CHANNELS_ADDR,
    IQS550ConfigError,
    active_channel_bytes,
    render_iqs550_config,
)
from captouch.geometry.trackpad import build_trackpad
from captouch.params import TRACKPAD_PRESETS, TrackpadParams


def _build(**kw):
    return build_trackpad(TrackpadParams(**kw))


def test_bitmap_is_30_bytes_15_tx_words():
    assert len(active_channel_bytes(_build(num_rows=4, num_cols=4))) == 30


def test_fully_enabled_rect_packs_low_bits_per_tx_word():
    # 3×3 rect: every node enabled → each used Tx word has Rx bits 0..2 set (0x0007),
    # stored high-byte-first, and the 12 unused Tx words are zero.
    b = active_channel_bytes(_build(num_rows=3, num_cols=3))
    assert b[0:6] == bytes([0x00, 0x07, 0x00, 0x07, 0x00, 0x07])
    assert b[6:] == bytes(24)


def test_high_byte_first_ordering():
    # 10 Rx all enabled → word 0x03FF; the high byte (0x03) must come first.
    b = active_channel_bytes(_build(num_rows=10, num_cols=2))
    assert b[0] == 0x03 and b[1] == 0xFF
    assert b[2] == 0x03 and b[3] == 0xFF


def test_bitmap_round_trips_node_enable_map_word_tx_bit_rx():
    geo = _build(num_rows=6, num_cols=6, mask_shape="circle", clip_mode="conform")
    en = geo.node_enable_map()
    b = active_channel_bytes(geo)
    for t in range(6):  # word index = Tx column
        word = (b[2 * t] << 8) | b[2 * t + 1]
        for rx in range(6):  # bit index = Rx row
            assert bool(word & (1 << rx)) == en[rx][t]


def test_conform_circle_disables_corner_node_bit():
    geo = _build(num_rows=6, num_cols=6, mask_shape="circle", clip_mode="conform")
    b = active_channel_bytes(geo)
    # node (Rx1, Tx1) is a cut corner → bit 0 of the Tx1 word is clear.
    assert ((b[0] << 8) | b[1]) & 1 == 0


def test_threshold_changes_disabled_count():
    geo = _build(num_rows=6, num_cols=6, mask_shape="circle", clip_mode="conform")
    lenient = bin(int.from_bytes(active_channel_bytes(geo, 0.4), "big")).count("1")
    strict = bin(int.from_bytes(active_channel_bytes(geo, 0.6), "big")).count("1")
    assert strict <= lenient  # a higher bar enables fewer nodes


@pytest.mark.parametrize("rows,cols", [(11, 4), (4, 16), (10, 15)])
def test_rejects_matrix_beyond_the_chip_envelope(rows, cols):
    # 11 Rx, 16 Tx, or 150-node cap overshoot (10×15=150 is OK, but 11×15 etc. fail).
    if rows <= 10 and cols <= 15 and rows * cols <= 150:
        active_channel_bytes(_build(num_rows=rows, num_cols=cols))  # fits, no raise
        return
    with pytest.raises(IQS550ConfigError):
        active_channel_bytes(_build(num_rows=rows, num_cols=cols))


def test_header_has_registers_array_map_and_caveat():
    header = render_iqs550_config(build_trackpad(TRACKPAD_PRESETS["iqs550"]))
    assert "#ifndef CT_TRACKPAD_IQS550_CONFIG_H" in header
    assert "#define IQS550_TOTAL_RX           10" in header
    assert "#define IQS550_TOTAL_TX           10" in header
    assert f"0x{ACTIVE_CHANNELS_ADDR:04X}u" in header
    assert "static const uint8_t iqs550_active_channels[30] = {" in header
    # the node map and the disabled count
    assert "Disabled nodes: 20 of 100" in header
    assert "Rx\\Tx" in header
    # the firmware-safety caveat and the identity-mapping disclosure
    assert "VERIFY the byte/bit order against AZD070" in header
    assert "identity mapping" in header
    # exactly 15 Tx word rows in the array
    assert header.count("/* Tx") == 15


def test_header_array_bytes_match_active_channel_bytes():
    import re

    geo = build_trackpad(TRACKPAD_PRESETS["iqs550"])
    header = render_iqs550_config(geo)
    hexbytes = [int(m, 16) for m in re.findall(r"0x([0-9A-F]{2}),", header)]
    assert bytes(hexbytes) == active_channel_bytes(geo)
