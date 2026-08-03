"""Counters for this API's own behaviour, and the immutable snapshot of them.

Same shape as `core/preprocessing/metrics.py` and `core/health/metrics.py`, deliberately:
a thread-safe plain `dict` behind a real lock (not relying on the GIL making `+=` atomic —
this project targets free-threaded 3.14t, where that assumption does not hold, §3.3.1),
handing out a frozen `OcrMetrics` snapshot a caller can never observe mutating mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import OcrMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(OcrMetrics))


class OcrMetricsCollector:
    """Thread-safe counters. One instance per OCR API process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising — instrumentation is never
        allowed to crash the operation it observes."""
        with self._lock:
            if name in self._counts:
                self._counts[name] += amount

    def snapshot(self) -> OcrMetrics:
        with self._lock:
            return OcrMetrics(**self._counts)
