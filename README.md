# valve-stiction-detection

Detection/ML service for the valve stiction fault-detection pipeline. Stateless predictor: given a windowed PV/OP sample, runs [valve-stiction-ml](https://github.com/maulanaiskak/valve-stiction-ml)'s classic detector (ellipse-fit + Kano pattern check) and its trained RF model, and returns both results. No database access — the caller (ingestion, or the Kafka delivery adapter itself) persists.

## Architecture

Layered: `domain` (plain types, no I/O) → `usecase` (the actual detection logic, transport-agnostic) → `repository` (TimescaleDB persistence) → `delivery` (transport adapters). Two delivery adapters share the same `usecase.DetectionCore`:

- `delivery/grpc/server.py` — gRPC server (`proto/detection.proto`'s `Detection` service). Used by [valve-stiction-ingestion](https://github.com/maulanaiskak/valve-stiction-ingestion) in its default mode.
- `delivery/kafka/worker.py` — Kafka/Redpanda consumer, for horizontal scaling (multiple replicas in one consumer group, partitioned by `sensor_id`). Calls `repository.persist` itself, since there's no downstream consumer waiting on a response in this mode.

```
domain/types.py          WindowInput, DetectionResult -- plain data
usecase/detector.py       DetectionCore -- classic detector + RF, transport-agnostic
repository/persist.py     TimescaleDB writes (Kafka adapter only)
delivery/grpc/server.py   gRPC adapter
delivery/kafka/worker.py  Kafka adapter
```

## Run

```bash
docker build -t valve-stiction-detection .
docker run -p 50051:50051 valve-stiction-detection                                             # gRPC mode
docker run -e KAFKA_BROKERS=... valve-stiction-detection python -m delivery.kafka.worker        # Kafka mode
```

| Env var | Used by | Default |
|---|---|---|
| `DETECTION_SERVICE_PORT` | gRPC | `50051` |
| `KAFKA_BROKERS`, `KAFKA_TOPIC`, `KAFKA_GROUP_ID` | Kafka | `localhost:9092`, `valve-windows`, `detection-group` |
| `DATABASE_URL` | Kafka mode only (persists its own results) | `postgresql://postgres:postgres@localhost:5432/valve_stiction` |

## Files worth knowing about

- `model/model.joblib` — the trained RF artifact from valve-stiction-ml (checked in directly, ~6MB).
- `proto/detection.proto`, `db/init.sql` — copies of the shared gRPC contract and TimescaleDB schema. This service and [valve-stiction-ingestion](https://github.com/maulanaiskak/valve-stiction-ingestion) each keep their own copy (no shared/orchestrator repo) — if you change one, change the other.

## A real finding, and the fix

Running live against a synthetic simulator (not held-out real data), the RF model originally predicted "stiction" with high confidence for every sensor, including ones with no stiction injected — the classic detector still got those right. Checked: feature extraction goes through the same code the model was trained with, so this wasn't a plumbing bug. It was a genuine train/serve distribution mismatch — RF was trained only on real industrial CSVs (ISDB/SACAC), and had never seen the simulator's signal shape at all. AUC on a 267-window live streaming evaluation: **0.079**, worse than random, despite scoring 0.865 on real held-out SACAC data.

Fixed in [valve-stiction-ml](https://github.com/maulanaiskak/valve-stiction-ml) via synthetic-data domain-randomization augmentation (train on a broad, physically-constrained range of similar signals, not the literal test config) plus a properly-derived decision threshold — see its `ML_PLAN.md` §15 for the full methodology, including a real label-quality bug a unit test caught along the way. Re-run against the same 255-window live streaming setup after the fix: **AUC 0.9998, 99.6% accuracy, F1 0.996** — now essentially matching the classic detector. Both detectors still run unconditionally and are shown side by side on the dashboard regardless (see `HLD.md`'s NFR-1) — this fix closed the gap for this signal family, it doesn't guarantee the RF generalizes to every future signal, so the classic detector stays the unconditional backstop.
