"""Per-stage latency bookkeeping for the pipeline and `bench/latency.py` (CLAUDE.md §9.1)."""

from __future__ import annotations

import statistics
from collections import deque

# Pipeline stages in order. "queue" is the wait between the camera handing a frame over
# and the pipeline picking it up; "end_to_end" runs from the camera read returning to
# the OS event being sent. Sensor-to-driver camera latency is not visible to software.
STAGES = (
    "capture",
    "queue",
    "convert",
    "inference",
    "features",
    "engine",
    "dispatch",
    "end_to_end",
)


def percentile(ordered: list[float], q: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty list (q in 0..1)."""
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarize(values_ms: list[float]) -> dict[str, float | int | None]:
    """n, p50, p95, and max of a list of millisecond timings."""
    if not values_ms:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values_ms)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(percentile(ordered, 0.95), 2),
        "max": round(ordered[-1], 2),
    }


class StageStats:
    """Ring buffer of recent timings per stage. Owned by one thread (the pipeline)."""

    def __init__(self, maxlen: int = 1800) -> None:
        self._data: dict[str, deque[float]] = {s: deque(maxlen=maxlen) for s in STAGES}

    def add(self, stage: str, ms: float) -> None:
        self._data[stage].append(ms)

    def summary(self) -> dict[str, dict[str, float | int | None]]:
        return {stage: summarize(list(values)) for stage, values in self._data.items()}
