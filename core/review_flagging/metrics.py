"""Counters for this API's own behaviour, and the immutable snapshot of them.

This is the "dismissal vs. resolution distinction" made countable (`v3-deepdive-25-review-
flagging-api.md` §7's own testing hook): `flags_resolved` and `flags_dismissed` are two
separate counters precisely so nothing downstream can collapse them into one "flags closed"
number and quietly lose the distinction the deep-dive calls out as easy to blur.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic — this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `FlagMetrics`, a frozen contract — a caller can never be holding a
view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import FlagMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `FlagMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(FlagMetrics))


class FlagMetricsCollector:
    """Thread-safe counters. One instance per Review/Flagging process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a path whose whole job is to never be able to
        fail its caller — a typo'd counter name must not be what refuses a flag resolution.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> FlagMetrics:
        with self._lock:
            counts = dict(self._counts)
        return FlagMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "FlagMetricsCollector"]
