"""Counters for this API's own behaviour, and the immutable snapshot of them.

`webhooks_rejected_signature` is the one worth an alert rather than a dashboard. §5 describes
the unverified-webhook endpoint as "a real, exploitable surface (anyone who discovers the URL
could fake a 'payment succeeded' event)" — so a non-trivial count here is not noise, it is
someone probing. It is kept separate from `webhooks_rejected_duplicate` for exactly that
reason: duplicates are every payment provider's normal retry behaviour and mean nothing,
while signature failures mean something specific.

`charges_blocked_by_hold` should be small and non-zero. Zero across a long window suggests
Account Guardian's deletion flow is not reaching this API at all, which would mean users who
asked to be deleted are still being charged (§4).

Plain `dict` behind a real lock rather than a `FrozenDict` — mutable counters, not a constant
(`docs/PRINCIPLES.md` §2.1.1) — and the lock is real rather than a GIL assumption because this
project targets free-threaded 3.14t (§3.3.1).
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import BillingMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(BillingMetrics))


class BillingMetricsCollector:
    """Thread-safe counters. One instance per Billing process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising."""
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> BillingMetrics:
        with self._lock:
            counts = dict(self._counts)
        return BillingMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "BillingMetricsCollector"]
