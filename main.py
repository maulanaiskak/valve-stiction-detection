"""Detection/ML service (PRD FR-3), gRPC transport (V1). Thin adapter over
detector.py's DetectionCore -- see that module for the actual logic. Stateless
predictor: no DB access (see docs/V3_PLAN.md) -- the Go ingestion service
persists the result after this call returns.
"""

from __future__ import annotations

import os
from concurrent import futures

import grpc

from detector import DetectionCore, WindowInput
from detectionpb import detection_pb2, detection_pb2_grpc


class DetectionServicer(detection_pb2_grpc.DetectionServicer):
    def __init__(self, core: DetectionCore):
        self.core = core

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
            rf_label=result.rf_label,
            rf_probability=result.rf_probability,
        )


def serve() -> None:
    port = os.environ.get("DETECTION_SERVICE_PORT", "50051")
    core = DetectionCore()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    detection_pb2_grpc.add_DetectionServicer_to_server(DetectionServicer(core), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Detection/ML service (gRPC) listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
