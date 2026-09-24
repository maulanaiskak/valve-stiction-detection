"""TimescaleDB persistence for detection results. Only kafka_worker.py (V2)
uses this directly -- the gRPC transport (V1) hands its result back to the
Go caller, which persists it itself (see docs/V3_PLAN.md and detector.py's
module docstring for why DetectionCore itself stays pure).
"""

from __future__ import annotations

from detector import DetectionResult, WindowInput


def persist(db_conn, window: WindowInput, result: DetectionResult) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO window_results
                (sensor_id, window_start, label, ellipse_index, kano_verdict,
                 rf_label, rf_probability, pv, op)
            VALUES (%s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                window.sensor_id,
                window.window_start_unix_ms,
                result.label,
                result.ellipse_index,
                result.kano_verdict,
                result.rf_label,
                result.rf_probability,
                list(window.pv),
                list(window.op),
            ),
        )
    db_conn.commit()
