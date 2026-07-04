"""Touch-controller device profiles and their channel-count enforcement."""

from __future__ import annotations

import pytest

from captouch.params import (
    DEVICES,
    DeviceProfile,
    TrackpadError,
    TrackpadParams,
    device_profile,
    validate_device_matrix,
    validate_trackpad,
)


def test_iqs550_profile_matches_the_datasheet():
    prof = DEVICES["iqs550"]
    assert isinstance(prof, DeviceProfile)
    # Rx mapping = 10 bytes, Tx mapping = 15 bytes, 150 channels (datasheet §5.1.3 / p1).
    assert (prof.max_rx, prof.max_tx, prof.max_nodes) == (10, 15, 150)
    assert "IQS550" in prof.name
    assert "10 Rx" in prof.channels_note() and "15 Tx" in prof.channels_note()


def test_device_profile_lookup_raises_on_unknown():
    assert device_profile("iqs550", TrackpadError) is DEVICES["iqs550"]
    with pytest.raises(TrackpadError, match="unknown device"):
        device_profile("nope", TrackpadError)


def test_generic_matrix_has_no_cap():
    # No device → the device layer never fires, however large the matrix.
    validate_device_matrix(None, 40, 60, 2400, TrackpadError)
    validate_trackpad(TrackpadParams(num_rows=40, num_cols=60))


def test_iqs550_accepts_matrix_at_the_caps():
    validate_device_matrix("iqs550", 10, 15, 150, TrackpadError)
    validate_trackpad(TrackpadParams(num_rows=10, num_cols=15, device="iqs550"))


def test_iqs550_rejects_too_many_rx_rows():
    with pytest.raises(TrackpadError, match=r"num_rows 11 exceeds .*10 Rx"):
        validate_trackpad(TrackpadParams(num_rows=11, num_cols=10, device="iqs550"))


def test_iqs550_rejects_too_many_tx_cols():
    with pytest.raises(TrackpadError, match=r"num_cols 16 exceeds .*15 Tx"):
        validate_trackpad(TrackpadParams(num_rows=8, num_cols=16, device="iqs550"))


def test_iqs550_rejects_over_node_budget_within_axis_caps():
    # 10 Rx × 15 Tx would be 150 nodes exactly; anything above 150 is caught by the
    # node budget even when neither axis alone exceeds its cap. (Both axes at their
    # cap already hit 150, so use the exact-cap case for the boundary and a synthetic
    # over-budget call for the node rule.)
    with pytest.raises(TrackpadError, match=r"200 nodes exceeds"):
        validate_device_matrix("iqs550", 10, 15, 200, TrackpadError)


def test_unknown_device_on_params_is_rejected():
    with pytest.raises(TrackpadError, match="unknown device"):
        validate_trackpad(TrackpadParams(num_rows=4, num_cols=4, device="bogus"))


def test_device_round_trips_through_serialization():
    from captouch.params import params_from_json, params_to_json

    p = TrackpadParams(num_rows=8, num_cols=8, device="iqs550")
    assert params_from_json(params_to_json(p)).device == "iqs550"
