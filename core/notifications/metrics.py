"""Counters for this API's own behaviour, and the immutable snapshot of them.

Mirrors `core/logs/metrics.py` and `core/audit/metrics.py` exactly, for the same reason: what
is genuinely worth exposing to Health/Telemetrees is what the write and dispatch paths *chose*
to do — how many channel sends were skipped for a disabled preference versus an unconfigured
provider, how many retries were spent, how many failures were bad enough to escalate to staff —
none of which is recoverable from the stored notifications themselves.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent). The lock is
real rather than relying on the GIL making `+=` atomic — this project targets free-threaded
3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `NotificationsMetrics`, a frozen contract — a caller can never be
holding a view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import NotificationsMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart — adding
#: a counter means adding a field to `NotificationsMetrics` and nothing else, the identical
#: pattern `core/logs/metrics.py::COUNTER_NAMES` uses.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(NotificationsMetrics))


class NotificationsMetricsCollector:
    """Thread-safe counters. One instance shared across `InboxStore` and `dispatch.Notifier`
    for a given process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising — a typo'd counter name must not be
        able to fail the write or dispatch path it is only instrumenting."""
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> NotificationsMetrics:
        with self._lock:
            counts = dict(self._counts)
        return NotificationsMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "NotificationsMetricsCollector"]
