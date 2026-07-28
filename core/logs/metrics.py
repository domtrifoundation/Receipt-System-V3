"""Counters for this API's own behaviour, and the immutable snapshot of them.

Health API polls a service for how it is actually doing; for Logs the interesting answers are
all about what the write path chose to do — how many routine entries a verbosity tier
dropped, how many tracebacks were captured, how often a query had to fall back to scanning
JSONL because the index was not usable. None of that is inferable from the log files
themselves, which by definition do not contain what was dropped.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `LogsMetrics`, a frozen contract — a caller can never be holding a
view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import LogsMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `LogsMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(LogsMetrics))


class LogsMetricsCollector:
    """Thread-safe counters. One instance per Logs process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a path whose whole job is to never be able to
        fail its caller — a typo'd counter name must not be what takes down a log write.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> LogsMetrics:
        with self._lock:
            counts = dict(self._counts)
        return LogsMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "LogsMetricsCollector"]
