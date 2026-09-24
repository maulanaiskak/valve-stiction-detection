"""Tests for kafka_worker.py's message parsing. The JSON shape here must
match ingestion/main.go's WindowMessage struct field-for-field -- these
tests fix that contract from the Python side; there's no shared schema
enforcing it (see docs/V2_PLAN.md on why JSON was chosen over a second
protobuf path).
"""

import json

import pytest
from kafka_worker import parse_window_message


def test_parses_a_valid_window_message():
    # exact field names Go's json.Marshal(WindowMessage{...}) produces
    raw = json.dumps(
        {
            "sensor_id": "valve-1",
            "pv": [1.0, 2.0, 3.0],
            "op": [4.0, 5.0, 6.0],
            "window_start_unix_ms": 1700000000000,
        }
    ).encode()

    window = parse_window_message(raw)

    assert window.sensor_id == "valve-1"
    assert window.pv == [1.0, 2.0, 3.0]
    assert window.op == [4.0, 5.0, 6.0]
    assert window.window_start_unix_ms == 1700000000000


def test_raises_on_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        parse_window_message(b"not json")


def test_raises_on_missing_field():
    raw = json.dumps({"sensor_id": "valve-1", "pv": [1.0], "op": [2.0]}).encode()  # no window_start_unix_ms

    with pytest.raises(KeyError):
        parse_window_message(raw)
