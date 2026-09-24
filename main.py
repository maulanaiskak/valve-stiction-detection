"""Detection service (PRD FR-3), gRPC transport (V1). Thin adapter over
detector.py's DetectionCore -- see that module for the actual logic, and
docs/V2_PLAN.md for why this got split out (kafka_worker.py is the other
transport, sharing the same core).
"""

from __future__ import annotations

import os
from concurrent import futures

import grpc
import psycopg2

from detector import DetectionCore, WindowInput
from detectionpb import detection_pb2, detection_pb2_grpc


class DetectionServicer(detection_pb2_grpc.DetectionServicer):
    def __init__(self, db_conn):
        self.core = DetectionCore(db_conn)

    def DetectWindow(self, request, context):
        window = WindowInput(
            sensor_id=request.sensor_id,
            pv=list(request.pv),
            op=list(request.op),
            window_start_unix_ms=request.window_start_unix_ms,
        )
        result = self.core.detect(window)
        return detection_pb2.WindowResponse(
            label=result.label,
            ellipse_index=result.ellipse_index,
            kano_verdict=result.kano_verdict,
            has_activity=result.has_activity,
        )


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
    print(f"Detection service (gRPC) listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
