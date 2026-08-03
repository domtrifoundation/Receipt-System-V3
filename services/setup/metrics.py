"""Counters for this API's own behaviour, and the immutable snapshot of them.

Setup runs once (or rarely, on explicit re-invocation), so there is no ongoing hot path to
watch — the value of these counters is almost entirely diagnostic, surfaced through Health API's
own status layer when a first-run or an update-time provisioning pass genuinely goes wrong. "How
many services failed to provision on this clone" and "how many wizard steps did the owner
actually skip" are questions this module exists to make answerable after the fact, since a
one-time flow that failed silently has no other record of what happened.

Same shape as `core/health/metrics.py`, deliberately: a thread-safe plain `dict` behind a real
lock (not relying on the GIL making `+=` atomic — this project targets free-threaded 3.14t,
where that assumption does not hold, §3.3.1), handing out a frozen `SetupMetrics` snapshot a
caller can never observe mutating mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import SetupMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding a
#: counter means adding a field to `SetupMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(SetupMetrics))


class SetupMetricsCollector:
    """Thread-safe counters. One instance per Setup process — and Setup is a one-shot or
    rarely-invoked process, so in practice usually one instance per run, not a long-lived
    singleton the way Health's own collector is."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation, never a correctness dependency — a stray counter name
        from a future refactor should not be able to crash the operation it is merely observing.
        """
        with self._lock:
            if name in self._counts:
                self._counts[name] += amount

    def snapshot(self) -> SetupMetrics:
        with self._lock:
            return SetupMetrics(**self._counts)
