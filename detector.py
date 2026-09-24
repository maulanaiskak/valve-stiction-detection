"""Core detection logic (PRD FR-3), shared by both transports:
main.py (gRPC server, V1) and kafka_worker.py (Redpanda consumer, V2).
Wraps valve_stiction_ml's classic detector and trained RF model directly --
not a reimplementation or a copy, the same modules/artifact valve-stiction-ml
trains and produces. See docs/V1_PLAN.md, docs/V2_PLAN.md, docs/V3_PLAN.md.

DetectionCore is a pure predictor: WindowInput in, DetectionResult out, no
DB access. Persistence is each transport's own concern (V3_PLAN.md) -- the
gRPC transport hands the result back to the Go caller, which persists it;
the Kafka transport has no downstream consumer to do that, so
kafka_worker.py persists it directly after calling detect().
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from valve_stiction_ml.classic import (
    ellipse_stiction_index,
    has_sufficient_activity,
    kano_pattern_check,
)
from valve_stiction_ml.inference import load_artifact, predict_window

# Matches valve-stiction-ml/configs/default.yaml's classic_detector.ellipse_stiction_threshold
# -- tuned on ISDB only, see that repo's ML_PLAN.md §7 for how and why.
ELLIPSE_THRESHOLD = 0.3762
MIN_RELATIVE_ACTIVITY = 0.15  # matches valve-stiction-ml's default

# has_sufficient_activity was designed around a whole source file's OP std as
# the reference (valve-stiction-ml classic.py's module docstring) -- a
# real-time service never has "the whole file", only a stream of windows.
# This approximates it with a per-sensor exponential moving average of each
# window's OP std, updated on every call. Cold-start: skip the guard (treat
# as active, the old always-True behavior) until a sensor has contributed
# enough windows for the EMA to mean anything.
EMA_ALPHA = 0.2
MIN_WINDOWS_BEFORE_GUARD = 5

DEFAULT_RF_MODEL_PATH = Path(__file__).parent / "model" / "model.joblib"


class RollingActivityReference:
    def __init__(self):
        self._lock = threading.Lock()
        self._ema_std: dict[str, float] = {}
        self._count: dict[str, int] = {}

    def reference_for(self, sensor_id: str) -> float | None:
        """Current reference, or None if this sensor hasn't seen enough
        windows yet to trust the EMA (cold start)."""
        with self._lock:
            if self._count.get(sensor_id, 0) < MIN_WINDOWS_BEFORE_GUARD:
                return None
            return self._ema_std.get(sensor_id)

    def update(self, sensor_id: str, op_std: float) -> None:
        with self._lock:
            prev = self._ema_std.get(sensor_id)
            self._ema_std[sensor_id] = (
                op_std if prev is None else EMA_ALPHA * op_std + (1 - EMA_ALPHA) * prev
            )
            self._count[sensor_id] = self._count.get(sensor_id, 0) + 1


def zscore(x: np.ndarray) -> np.ndarray:
    std = x.std()
    return (x - x.mean()) / std if std > 0 else x - x.mean()


def derive_label(ellipse_verdict: bool, kano_verdict: bool) -> str:
    if ellipse_verdict and kano_verdict:
        return "yes"
    if not ellipse_verdict and not kano_verdict:
        return "no"
    return "uncertain"


@dataclass(frozen=True)
class WindowInput:
    sensor_id: str
    pv: list[float]
    op: list[float]
    window_start_unix_ms: int


@dataclass(frozen=True)
class DetectionResult:
    label: str
    ellipse_index: float
    kano_verdict: bool
    has_activity: bool
    rf_label: str
    rf_probability: float


class DetectionCore:
    """Transport-agnostic: takes a WindowInput, returns a DetectionResult.
    Both main.py and kafka_worker.py just adapt their transport's message
    shape into a WindowInput and call detect() -- persistence is up to
    each transport, see module docstring."""

    def __init__(self, rf_model_path: Path = DEFAULT_RF_MODEL_PATH):
        self.activity_ref = RollingActivityReference()
        self.rf_artifact = load_artifact(rf_model_path)

    def detect(self, window: WindowInput) -> DetectionResult:
        pv = np.array(window.pv, dtype=float)
        op = np.array(window.op, dtype=float)

        reference_std = self.activity_ref.reference_for(window.sensor_id)
        is_active = (
            True
            if reference_std is None
            else has_sufficient_activity(op, reference_std, MIN_RELATIVE_ACTIVITY)
        )
        self.activity_ref.update(window.sensor_id, float(op.std()))

        if not is_active:
            # Matches training: insufficient activity -> "no" directly,
            # skip the shape detectors entirely (valve-stiction-ml
            # classic.py's label_window).
            label, ellipse_idx, kano = "no", 0.0, False
        else:
            pv_z, op_z = zscore(pv), zscore(op)
            ellipse_idx = ellipse_stiction_index(pv_z, op_z)
            kano = kano_pattern_check(pv_z, op_z)
            label = derive_label(ellipse_idx >= ELLIPSE_THRESHOLD, kano)

        # RF runs independently of the activity guard -- it was trained on
        # raw windows (valve-stiction-ml's feature extraction has no such
        # guard), so gating it here would score it on a different input
        # distribution than it was validated on.
        rf_pred = predict_window(self.rf_artifact, pv, op)

        return DetectionResult(
            label=label,
            ellipse_index=ellipse_idx,
            kano_verdict=kano,
            has_activity=is_active,
            rf_label=rf_pred["label"],
            rf_probability=rf_pred["probability"],
        )
