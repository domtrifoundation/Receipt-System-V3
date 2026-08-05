"""Counters for this API's own behaviour, and the immutable snapshot of them.

Same shape as `core/ocr/metrics.py` and `core/preprocessing/metrics.py`, deliberately: a
thread-safe plain `dict` behind a real lock, handing out a frozen `InferenceMetrics`
snapshot a caller can never observe mutating mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import InferenceMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(InferenceMetrics))


class InferenceMetricsCollector:
    """Thread-safe counters. One instance per Inference API process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if name in self._counts:
                self._counts[name] += amount

    def snapshot(self) -> InferenceMetrics:
        with self._lock:
            return InferenceMetrics(**self._counts)
