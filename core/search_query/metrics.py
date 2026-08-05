"""Counters for this API's own behaviour, and the immutable snapshot of them.

The interesting facts about Search/Query are all about the permission gate and the FTS5
accelerator — how many cross-user or cross-group reads were denied, how often the index
could not be used and structured filters ran alone. None of that is inferable from a result
set itself, which by definition does not describe what was denied or degraded.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

The snapshot handed out is `SearchQueryMetrics`, a frozen contract — a caller can never be
holding a view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import SearchQueryMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `SearchQueryMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(SearchQueryMetrics))


class SearchQueryMetricsCollector:
    """Thread-safe counters. One instance per Search/Query process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a read path; a typo'd counter name must not be
        what fails a search.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> SearchQueryMetrics:
        with self._lock:
            counts = dict(self._counts)
        return SearchQueryMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "SearchQueryMetricsCollector"]
