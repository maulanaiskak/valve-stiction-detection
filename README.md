# valve-stiction-detection

[![CI](https://github.com/maulanaiskak/valve-stiction-detection/actions/workflows/ci.yml/badge.svg)](https://github.com/maulanaiskak/valve-stiction-detection/actions)

Detection/ML service for a distributed, real-time control-valve stiction detection pipeline. Stateless predictor: given a windowed PV/OP sample, runs [valve-stiction-ml](https://github.com/maulanaiskak/valve-stiction-ml)'s classic detector (ellipse-fit + Kano pattern check) and its trained RF model, and returns both results. No database access — the caller persists.

**Part of a 5-repo system** — see [System Design (HLD)](https://github.com/maulanaiskak/valve-stiction-backend/blob/main/docs/HLD.md) and [Whitepaper](https://github.com/maulanaiskak/valve-stiction-backend/blob/main/docs/WHITEPAPER.md) for the full picture: a train/serve model-generalization failure found, fixed, and honestly bounded; a monolith split into 5 independently-deployable services; 99.6%/AUC 0.9998 live-streaming detection accuracy after the fix.

| Repo | Role |
|---|---|
| [simulator](https://github.com/maulanaiskak/valve-stiction-simulator) | Synthetic PV/OP signal generator |
| [ingestion](https://github.com/maulanaiskak/valve-stiction-ingestion) | MQTT subscribe, windowing, forwards to detection |
| **detection** (this repo) | Classic detector + trained RF model |
| [backend](https://github.com/maulanaiskak/valve-stiction-backend) | REST + WebSocket API |
| [frontend](https://github.com/maulanaiskak/valve-stiction-frontend) | React dashboard |

## Where this fits

```mermaid
flowchart LR
    SIM[Simulator] --> MQ[[Mosquitto]]
    MQ --> ING[Ingestion]
    ING -->|gRPC or Kafka| DET["Detection (this repo)"]
    DET -->|classic + RF result| ING
    ING --> DB[(TimescaleDB)]
    DB --> BE[Backend]
    BE --> FE[Frontend]
```

## What happens inside `DetectionCore.detect()`

```mermaid
flowchart TD
    A[Window: pv, op arrays] --> B{Sufficient activity?}
    B -->|No| C["label = no\nshape detectors skipped"]
    B -->|Yes, or cold start| D[z-score normalize pv, op]
    D --> E[ellipse_stiction_index]
    D --> F[kano_pattern_check]
    E --> G{Both agree?}
    F --> G
    G -->|both true| H[label = yes]
    G -->|both false| I[label = no]
    G -->|disagree| J[label = uncertain]
    A --> K["RF predict_window\nruns unconditionally"]
    K --> L[rf_label, rf_probability]
    C --> M[DetectionResult]
    H --> M
    I --> M
    J --> M
    L --> M
```

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

## Testing

```bash
pip install -r requirements.txt pytest
pytest -v
```

13 tests: activity-guard EMA behavior, cold-start, RF prediction shape, gRPC request/response translation, Kafka message parsing, and persistence.

## Files worth knowing about

- `model/model.joblib` — the trained RF artifact from valve-stiction-ml (checked in directly, ~6MB).
- `proto/detection.proto`, `db/init.sql` — copies of the shared gRPC contract and TimescaleDB schema. This service and [valve-stiction-ingestion](https://github.com/maulanaiskak/valve-stiction-ingestion) each keep their own copy (no shared/orchestrator repo) — if you change one, change the other.

## A real finding, the fix, and its honest boundary

Running live against a synthetic simulator (not held-out real data), the RF model originally predicted "stiction" with high confidence for every sensor, including ones with no stiction injected — the classic detector still got those right. Checked: feature extraction goes through the same code the model was trained with, so this wasn't a plumbing bug. It was a genuine train/serve distribution mismatch — RF was trained only on real industrial CSVs (ISDB/SACAC), and had never seen the simulator's signal shape at all. AUC on a 267-window live streaming evaluation: **0.079**, worse than random, despite scoring 0.865 on real held-out SACAC data.

Fixed in [valve-stiction-ml](https://github.com/maulanaiskak/valve-stiction-ml) via synthetic-data domain-randomization augmentation (train on a broad, physically-constrained range of similar signals, not the literal test config) plus a properly-derived decision threshold — see its `ML_PLAN.md` §15 for the full methodology, including a real label-quality bug a unit test caught along the way. Re-run against the same live streaming setup after the fix: **AUC 0.9998, 99.6% accuracy, F1 0.996** — now essentially matching the classic detector.

**Checked, not assumed, that this isn't just overfitting**: no train/validation leakage (group-based CV keyed by config, not window), and real SACAC performance is unchanged (0.865 ROC-AUC, same as before augmentation). But a genuine out-of-distribution test — signals with parameters well outside the trained ranges (`valve-stiction-ml/scripts/check_ood_generalization.py`) — scores AUC ~0.43-0.47, chance level. The model generalizes within the family of signals it was trained on, not beyond it; it did not learn a distribution-invariant concept of stiction.

**Also verified against real industrial data streamed live, not just the synthetic signal**: replaying the actual SACAC dataset through this service (not batch-scored offline) across the full 38-file corpus gives 86.3% classic-detector accuracy and 88.2%/AUC 0.920 for RF — matching the historical offline numbers. (An initial 6-file sample looked alarming; a single outlier file was dominating a too-small average — see `valve-stiction-backend/docs/STREAMING_EVALUATION.md` for the full investigation.)

Both detectors still run unconditionally and are shown side by side on the dashboard regardless (see `HLD.md`'s NFR-1) — this fix closed the gap for the signal family it was trained on, it doesn't make the RF's answer reliable outside it, so the classic detector stays the unconditional backstop.
