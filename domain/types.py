"""Domain types: plain data, no I/O and no framework/transport awareness.
Shared by every layer above (usecase, repository, delivery)."""

from __future__ import annotations

from dataclasses import dataclass


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
