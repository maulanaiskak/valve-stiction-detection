"""Detection service (PRD FR-9), Kafka/Redpanda transport (V2). Thin
adapter over detector.py's DetectionCore -- see that module for the actual
logic, and docs/V2_PLAN.md for the shared-core rationale.

FR-9's "horizontally scalable, multiple instances in one consumer group"
requirement isn't implemented here at all -- it's Kafka/Redpanda's own
partition-assignment doing the work. Running N copies of this process with
the same GROUP_ID is what satisfies FR-9; this file just has to not assume
anything about which partitions (i.e. which sensors) it'll be handed.
"""

from __future__ import annotations

import json
import os

import psycopg2
from confluent_kafka import Consumer

from detector import DetectionCore, WindowInput
from persist import persist


def parse_window_message(raw: bytes) -> WindowInput:
    """Pulled out of the consume loop so it's testable without a live
    broker -- a malformed message should be a clear, isolated failure
    mode, not something only exercised end-to-end."""
    payload = json.loads(raw)
    return WindowInput(
        sensor_id=payload["sensor_id"],
        pv=payload["pv"],
        op=payload["op"],
        window_start_unix_ms=payload["window_start_unix_ms"],
    )


def connect_db():
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/valve_stiction",
    )
    return psycopg2.connect(dsn)


def consume() -> None:
    brokers = os.environ.get("KAFKA_BROKERS", "localhost:9092")
    topic = os.environ.get("KAFKA_TOPIC", "valve-windows")
    group_id = os.environ.get("KAFKA_GROUP_ID", "detection-group")

    core = DetectionCore()
    db_conn = connect_db()
    consumer = Consumer(
        {
            "bootstrap.servers": brokers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])
    print(f"Detection worker (Kafka) consuming topic={topic!r} group={group_id!r} on {brokers}")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"consumer error: {msg.error()}")
                continue

            try:
                window = parse_window_message(msg.value())
            except (json.JSONDecodeError, KeyError) as e:
                print(f"failed to parse window message: {e}")
                continue

            result = core.detect(window)
            persist(db_conn, window, result)
            print(
                f"[{window.sensor_id}] (partition {msg.partition()}) "
                f"label={result.label} ellipse_index={result.ellipse_index:.3f} "
                f"kano={result.kano_verdict} has_activity={result.has_activity} "
                f"rf_label={result.rf_label} rf_probability={result.rf_probability:.3f}"
            )
    finally:
        consumer.close()


if __name__ == "__main__":
    consume()
