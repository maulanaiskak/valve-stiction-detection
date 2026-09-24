"""Detection service (PRD FR-3): gRPC server wrapping valve_stiction_ml's
classic detector directly -- not a reimplementation or a copy, the same
module valve-stiction-ml trains against. See docs/V1_PLAN.md.
"""

from __future__ import annotations

import os
from concurrent import futures

import grpc
import numpy as np
import psycopg2
from valve_stiction_ml.classic import ellipse_stiction_index, kano_pattern_check

from detectionpb import detection_pb2, detection_pb2_grpc

# Matches valve-stiction-ml/configs/default.yaml's classic_detector.ellipse_stiction_threshold
# -- tuned on ISDB only, see that repo's ML_PLAN.md §7 for how and why.
ELLIPSE_THRESHOLD = 0.3762


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

    def DetectWindow(self, request, context):
        pv = np.array(request.pv, dtype=float)
        op = np.array(request.op, dtype=float)

        # Real-time scoring sees one window at a time, not the full source
        # file has_sufficient_activity was designed around (see
        # valve-stiction-ml classic.py's module docstring) -- deferred here,
        # tracked in docs/V1_PLAN.md as a follow-up, not silently ignored.
        pv_z, op_z = zscore(pv), zscore(op)
        ellipse_idx = ellipse_stiction_index(pv_z, op_z)
        kano = kano_pattern_check(pv_z, op_z)
        label = derive_label(ellipse_idx >= ELLIPSE_THRESHOLD, kano)

        self._persist(request, label, ellipse_idx, kano)

        return detection_pb2.WindowResponse(
            label=label,
            ellipse_index=ellipse_idx,
            kano_verdict=kano,
            has_activity=True,
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
