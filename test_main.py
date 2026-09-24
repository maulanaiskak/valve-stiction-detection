"""Tests for the real-time approximation of has_sufficient_activity's
reference std. See main.py's module-level comment for why this exists:
the training-time version used a whole source file's OP std as reference,
which a streaming service never has.
"""

from unittest.mock import MagicMock

import numpy as np
from main import EMA_ALPHA, MIN_WINDOWS_BEFORE_GUARD, DetectionServicer, RollingActivityReference


def test_cold_start_returns_none_before_min_windows():
    ref = RollingActivityReference()
    for i in range(MIN_WINDOWS_BEFORE_GUARD - 1):
        assert ref.reference_for("valve-1") is None
        ref.update("valve-1", op_std=5.0)


def test_reference_available_after_min_windows():
    ref = RollingActivityReference()
    for _ in range(MIN_WINDOWS_BEFORE_GUARD):
        ref.update("valve-1", op_std=5.0)
    assert ref.reference_for("valve-1") is not None


def test_ema_converges_toward_recent_values():
    ref = RollingActivityReference()
    for _ in range(MIN_WINDOWS_BEFORE_GUARD):
        ref.update("valve-1", op_std=5.0)
    first_ref = ref.reference_for("valve-1")

    # a sustained shift to a much larger std should pull the EMA up over time
    for _ in range(50):
        ref.update("valve-1", op_std=20.0)
    later_ref = ref.reference_for("valve-1")

    assert later_ref > first_ref
    assert later_ref < 20.0  # EMA, not an instant jump


def test_sensors_are_tracked_independently():
    ref = RollingActivityReference()
    for _ in range(MIN_WINDOWS_BEFORE_GUARD):
        ref.update("valve-1", op_std=5.0)
        ref.update("valve-2", op_std=50.0)

    assert ref.reference_for("valve-1") < ref.reference_for("valve-2")


def test_ema_matches_the_documented_recurrence():
    values = [10.0, 20.0, 15.0, 30.0, 25.0]
    assert len(values) == MIN_WINDOWS_BEFORE_GUARD  # exercise exactly the cold-start boundary

    expected = values[0]
    for v in values[1:]:
        expected = EMA_ALPHA * v + (1 - EMA_ALPHA) * expected

    ref = RollingActivityReference()
    for v in values:
        ref.update("valve-1", op_std=v)

    assert ref.reference_for("valve-1") == expected


class FakeWindowRequest:
    def __init__(self, sensor_id: str, pv, op, window_start_unix_ms: int = 0):
        self.sensor_id = sensor_id
        self.pv = list(pv)
        self.op = list(op)
        self.window_start_unix_ms = window_start_unix_ms


def make_active_window(rng, amplitude=20.0):
    """A window shaped enough like a real active one to update the EMA
    realistically -- doesn't need to be stiction-shaped, just have real
    amplitude, since only has_activity is under test here."""
    t = np.arange(100)
    op = amplitude * np.sin(t / 5) + rng.normal(0, 0.5, 100)
    pv = op + rng.normal(0, 0.5, 100)
    return pv, op


def test_detect_window_returns_no_and_has_activity_false_when_inactive():
    rng = np.random.default_rng(0)
    servicer = DetectionServicer(db_conn=MagicMock())

    # seed past MIN_WINDOWS_BEFORE_GUARD with normal-amplitude windows so the
    # EMA reference is established (cold start over)
    for _ in range(MIN_WINDOWS_BEFORE_GUARD + 2):
        pv, op = make_active_window(rng)
        servicer.DetectWindow(FakeWindowRequest("valve-1", pv, op), context=None)

    # now a window where OP barely moves at all relative to that history
    pv_flat = rng.normal(50, 0.05, 100)
    op_flat = rng.normal(50, 0.05, 100)
    response = servicer.DetectWindow(FakeWindowRequest("valve-1", pv_flat, op_flat), context=None)

    assert response.has_activity is False
    assert response.label == "no"


def test_detect_window_stays_active_for_consistent_amplitude():
    rng = np.random.default_rng(1)
    servicer = DetectionServicer(db_conn=MagicMock())

    for _ in range(MIN_WINDOWS_BEFORE_GUARD + 2):
        pv, op = make_active_window(rng)
        servicer.DetectWindow(FakeWindowRequest("valve-1", pv, op), context=None)

    pv, op = make_active_window(rng)
    response = servicer.DetectWindow(FakeWindowRequest("valve-1", pv, op), context=None)

    assert response.has_activity is True
