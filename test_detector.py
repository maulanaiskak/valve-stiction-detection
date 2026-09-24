"""Tests for detector.py's core logic, transport-agnostic. See main.py's
and kafka_worker.py's own (thin) tests for transport-specific adapter
behavior.
"""

from unittest.mock import MagicMock

import numpy as np
from detector import (
    EMA_ALPHA,
    MIN_WINDOWS_BEFORE_GUARD,
    DetectionCore,
    RollingActivityReference,
    WindowInput,
)


def test_cold_start_returns_none_before_min_windows():
    ref = RollingActivityReference()
    for _ in range(MIN_WINDOWS_BEFORE_GUARD - 1):
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
    assert len(values) == MIN_WINDOWS_BEFORE_GUARD

    expected = values[0]
    for v in values[1:]:
        expected = EMA_ALPHA * v + (1 - EMA_ALPHA) * expected

    ref = RollingActivityReference()
    for v in values:
        ref.update("valve-1", op_std=v)

    assert ref.reference_for("valve-1") == expected


def make_active_window(rng, amplitude=20.0):
    """A window shaped enough like a real active one to update the EMA
    realistically -- doesn't need to be stiction-shaped, just have real
    amplitude, since only has_activity is under test here."""
    t = np.arange(100)
    op = amplitude * np.sin(t / 5) + rng.normal(0, 0.5, 100)
    pv = op + rng.normal(0, 0.5, 100)
    return pv, op


def test_detect_returns_no_and_has_activity_false_when_inactive():
    rng = np.random.default_rng(0)
    core = DetectionCore(db_conn=MagicMock())

    for _ in range(MIN_WINDOWS_BEFORE_GUARD + 2):
        pv, op = make_active_window(rng)
        core.detect(WindowInput("valve-1", list(pv), list(op), 0))

    pv_flat = rng.normal(50, 0.05, 100)
    op_flat = rng.normal(50, 0.05, 100)
    result = core.detect(WindowInput("valve-1", list(pv_flat), list(op_flat), 0))

    assert result.has_activity is False
    assert result.label == "no"


def test_detect_stays_active_for_consistent_amplitude():
    rng = np.random.default_rng(1)
    core = DetectionCore(db_conn=MagicMock())

    for _ in range(MIN_WINDOWS_BEFORE_GUARD + 2):
        pv, op = make_active_window(rng)
        core.detect(WindowInput("valve-1", list(pv), list(op), 0))

    pv, op = make_active_window(rng)
    result = core.detect(WindowInput("valve-1", list(pv), list(op), 0))

    assert result.has_activity is True


def test_detect_persists_to_db():
    rng = np.random.default_rng(2)
    db_conn = MagicMock()
    core = DetectionCore(db_conn=db_conn)

    pv, op = make_active_window(rng)
    core.detect(WindowInput("valve-1", list(pv), list(op), 12345))

    db_conn.cursor.return_value.__enter__.return_value.execute.assert_called_once()
    db_conn.commit.assert_called_once()
