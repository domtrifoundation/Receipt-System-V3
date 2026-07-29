"""Counters for this API's own behaviour, and the immutable snapshot of them.

`break_glass_refs_resolved` against `break_glass_refs_unresolvable` is the pair worth watching,
and it is the reason §8 asks for a regression test on that link at all: if ticket ids stopped
being findable in free text, every break-glass grant would keep working exactly as before and
the link would quietly stop resolving. Nothing would fail. The ratio here is the only thing
that would show it.

Plain `dict` behind a real lock rather than a `FrozenDict` — mutable counters, not a constant
(`docs/PRINCIPLES.md` §2.1.1) — and the lock is real rather than a GIL assumption because this
project targets free-threaded 3.14t (§3.3.1).
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import SupportTicketingMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(SupportTicketingMetrics))


class SupportTicketingMetricsCollector:
    """Thread-safe counters. One instance per Support Ticketing process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising."""
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> SupportTicketingMetrics:
        with self._lock:
            counts = dict(self._counts)
        return SupportTicketingMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "SupportTicketingMetricsCollector"]
