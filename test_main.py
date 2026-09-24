"""Thin test of the gRPC adapter layer -- the actual detection logic is
tested in test_detector.py against DetectionCore directly. This just
checks main.py correctly translates a gRPC request into a WindowInput
and a DetectionResult back into a gRPC response.
"""

from unittest.mock import MagicMock, patch

from detector import DetectionResult
from main import DetectionServicer


class FakeWindowRequest:
    def __init__(self, sensor_id="valve-1", pv=None, op=None, window_start_unix_ms=0):
        self.sensor_id = sensor_id
        self.pv = pv or [1.0, 2.0, 3.0]
        self.op = op or [4.0, 5.0, 6.0]
        self.window_start_unix_ms = window_start_unix_ms


def test_detect_window_translates_request_and_response():
    servicer = DetectionServicer(db_conn=MagicMock())

    fake_result = DetectionResult(
        label="yes", ellipse_index=1.5, kano_verdict=True, has_activity=True
    )
    with patch.object(servicer.core, "detect", return_value=fake_result) as mock_detect:
        response = servicer.DetectWindow(
            FakeWindowRequest(sensor_id="valve-1", pv=[1.0, 2.0], op=[3.0, 4.0], window_start_unix_ms=999),
            context=None,
        )

    called_with = mock_detect.call_args[0][0]
    assert called_with.sensor_id == "valve-1"
    assert called_with.pv == [1.0, 2.0]
    assert called_with.op == [3.0, 4.0]
    assert called_with.window_start_unix_ms == 999

    assert response.label == "yes"
    assert response.ellipse_index == 1.5
    assert response.kano_verdict is True
    assert response.has_activity is True
