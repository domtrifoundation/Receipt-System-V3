"""Counters for this API's own dispatch behaviour, and the immutable snapshot of them.

Modelled directly on `core/logs/metrics.py`: the counter names are derived from
`ToolCallMetrics` itself so the two cannot drift apart, the collector is a genuinely mutable
internal structure (a plain `dict` behind a real lock, not a `FrozenDict` — `docs/PRINCIPLES.md`
§2.1.1 draws that line at intent, and a live counter is not a constant), and the lock is real
rather than relying on the GIL making `+=` atomic, because this project targets free-threaded
3.14t where that assumption does not hold (§3.3.1).

Health API polls a service for how it is actually doing; for Tool Call the interesting answers
are all about what the dispatch path *decided* — how many calls were denied before a handler
ever ran, how many handlers timed out or raised, how many privileged invocations produced an
audit record. None of that is inferable from a `ToolResult` alone once it has been handed back
to the caller.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import ToolCallMetrics

#: The counter names, derived from the contract itself. Adding a counter means adding a field
#: to `ToolCallMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(ToolCallMetrics))


class ToolCallMetricsCollector:
    """Thread-safe counters. One instance per Tool Call process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on a path whose whole job is to never be able to
        fail its caller — a typo'd counter name must not be what takes down a tool dispatch.
        """
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> ToolCallMetrics:
        with self._lock:
            counts = dict(self._counts)
        return ToolCallMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "ToolCallMetricsCollector"]
