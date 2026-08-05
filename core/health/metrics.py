"""Counters for this API's own behaviour, and the immutable snapshot of them.

Health polls everyone else; the interesting answers about Health itself are all about the
ledger and the two detectors — how many reservations were granted versus rejected, how many
lapsed on their TTL rather than being released cleanly (§5.2's failure mode, made countable),
how often a soft degradation was actually caught. None of that is inferable from the status
snapshots Health hands out, which by definition describe other services.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `HealthMetrics`, a frozen contract — a caller can never be holding
a view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import HealthMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `HealthMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(HealthMetrics))


class HealthMetricsCollector:
    """Thread-safe counters. One instance per Health process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on the reservation hot path (§7), whose whole job
        is to stay minimal and never be able to fail its caller — a typo'd counter name must
        not be what refuses a GPU session its VRAM.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> HealthMetrics:
        with self._lock:
            counts = dict(self._counts)
        return HealthMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "HealthMetricsCollector"]
