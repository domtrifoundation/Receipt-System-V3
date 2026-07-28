"""Counters for this API's own behaviour, and the immutable snapshot of them.

The interesting answers about Geo/Address are all about what the corroboration layer chose to
do — how often the cache saved a real provider call, how often a provider was skipped as
unavailable versus called and failed, how often providers genuinely disagreed or an OCR-read
vendor name did not match what a resolved address's own reverse lookup reported. None of that
is inferable from a `GeoResult` alone, which by definition only describes the answer that won.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `GeoMetrics`, a frozen contract — a caller can never be holding a
view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import GeoMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `GeoMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(GeoMetrics))


class GeoMetricsCollector:
    """Thread-safe counters. One instance per Geo/Address process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a path whose whole job is to never be able to
        fail its caller — a typo'd counter name must not be what turns a degraded provider
        into a failed geocode run.
        """
        if name not in self._counts or amount == 0:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> GeoMetrics:
        with self._lock:
            counts = dict(self._counts)
        return GeoMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "GeoMetricsCollector"]
