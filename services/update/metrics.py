"""Counters for this API's own behaviour, and the immutable snapshot of them — same shape
as `core/preprocessing/metrics.py`/`core/health/metrics.py` (`docs/PRINCIPLES.md` §2.1.1's
own established pattern this session): a thread-safe plain `dict` behind a real lock, not
relying on the GIL, handing out a frozen snapshot a caller can never observe mutating
mid-read.
"""

from __future__ import annotations

import threading

from dataclasses import dataclass

COUNTER_NAMES: tuple[str, ...] = (
    "clones_succeeded",
    "clones_failed",
    "clones_fell_back_to_main",
    "keymaster_tokens_used",
    "releases_garbage_collected",
)


@dataclass(frozen=True)
class UpdateMetrics:
    clones_succeeded: int = 0
    clones_failed: int = 0
    clones_fell_back_to_main: int = 0
    keymaster_tokens_used: int = 0
    releases_garbage_collected: int = 0


class UpdateMetricsCollector:
    """Thread-safe counters. One instance per Update API process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if name in self._counts:
                self._counts[name] += amount

    def snapshot(self) -> UpdateMetrics:
        with self._lock:
            return UpdateMetrics(**self._counts)


__all__ = ["COUNTER_NAMES", "UpdateMetrics", "UpdateMetricsCollector"]
