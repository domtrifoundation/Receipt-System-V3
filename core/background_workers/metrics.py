"""Counters for this API's own behaviour, and the immutable snapshot of them.

The interesting facts about a scheduler are all about what it *declined* to do. A dispatch
that ran is visible in the job's own effects; a dispatch skipped because the scope was busy,
or because a job auto-disabled three days ago, leaves no trace anywhere else. `skipped_not_idle`
versus `skipped_disabled` is the pair worth watching: the first climbing means the system is
simply busy, the second climbing at all means something needs a human.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1). It matters
more here than in most packages — the scheduler dispatches to a thread pool and a process
pool, so these counters are genuinely touched from several threads at once rather than
theoretically.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import BackgroundWorkersMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(BackgroundWorkersMetrics))


class BackgroundWorkersMetricsCollector:
    """Thread-safe counters. One instance per Background Workers process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        Instrumentation on a dispatch path whose whole job is to survive anything a registered
        job does — a typo'd counter name must not be what takes down the scheduler that every
        other job depends on.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> BackgroundWorkersMetrics:
        with self._lock:
            counts = dict(self._counts)
        return BackgroundWorkersMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "BackgroundWorkersMetricsCollector"]
