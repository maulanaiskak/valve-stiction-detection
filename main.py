"""Detection service (PRD FR-3): gRPC server wrapping valve_stiction_ml's
classic detector directly -- not a reimplementation or a copy, the same
module valve-stiction-ml trains against. See docs/V1_PLAN.md.
"""

from __future__ import annotations

import os
import threading
from concurrent import futures

import grpc
import numpy as np
import psycopg2
from valve_stiction_ml.classic import (
    ellipse_stiction_index,
    has_sufficient_activity,
    kano_pattern_check,
)

from detectionpb import detection_pb2, detection_pb2_grpc

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


class DetectionServicer(detection_pb2_grpc.DetectionServicer):
    def __init__(self, db_conn):
        self.db_conn = db_conn
        self.activity_ref = RollingActivityReference()

    def DetectWindow(self, request, context):
        pv = np.array(request.pv, dtype=float)
        op = np.array(request.op, dtype=float)

        reference_std = self.activity_ref.reference_for(request.sensor_id)
        is_active = (
            True
            if reference_std is None
            else has_sufficient_activity(op, reference_std, MIN_RELATIVE_ACTIVITY)
        )
        self.activity_ref.update(request.sensor_id, float(op.std()))

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

        self._persist(request, label, ellipse_idx, kano)

        return detection_pb2.WindowResponse(
            label=label,
            ellipse_index=ellipse_idx,
            kano_verdict=kano,
            has_activity=is_active,
        )

    def _persist(self, request, label, ellipse_idx, kano) -> None:
        with self.db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO window_results
                    (sensor_id, window_start, label, ellipse_index, kano_verdict, pv, op)
                VALUES (%s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s)
                """,
                (
                    request.sensor_id,
                    request.window_start_unix_ms,
                    label,
                    ellipse_idx,
                    kano,
                    list(request.pv),
                    list(request.op),
                ),
            )
        self.db_conn.commit()


def connect_db():
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/valve_stiction",
    )
    return psycopg2.connect(dsn)


def serve() -> None:
    port = os.environ.get("DETECTION_SERVICE_PORT", "50051")
    conn = connect_db()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    detection_pb2_grpc.add_DetectionServicer_to_server(DetectionServicer(conn), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Detection service listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
