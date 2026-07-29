"""Counters for this API's own behaviour, and the immutable snapshot of them.

The pair worth watching is `polls_attempted` against `polls_unreachable`. This package's whole
value is that it notices things, so the failure that actually costs something is not a loud
error — it is a poller that has been quietly unreachable for a month while everything looked
fine. A ratio drifting toward unreachable is the only signal that would show.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1), and a
polling pass runs its pollers concurrently by design (§5).
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import TelemetreesMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(TelemetreesMetrics))


class TelemetreesMetricsCollector:
    """Thread-safe counters. One instance per Telemetrees process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        Instrumentation on a polling path whose entire posture is to survive an unreachable
        upstream — a typo'd counter name must not be what stops the monitoring.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> TelemetreesMetrics:
        with self._lock:
            counts = dict(self._counts)
        return TelemetreesMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "TelemetreesMetricsCollector"]
