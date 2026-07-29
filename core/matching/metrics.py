"""Counters for this API's own behaviour, and the immutable snapshot of them.

The interesting answers about Matching are all about what the two-way match and the
corroboration-context gate actually did — how often the forward pass ran versus the reverse
gazetteer scan, how many candidates were scored versus how many actually made it into a ranked
result, how often a candidate set arrived empty, how often the `BELOW_THRESHOLD`/`NEVER`
policies actually excluded Matching's own candidates from Inference's context. None of that is
inferable from a `MatchResult`/`MatchContext` alone, which by definition only describes the
answer for one call.

The counters are a genuinely mutable internal structure, so they are a plain `dict` behind a
lock, not a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1 draws that line at intent, and this is
not a constant). The lock is real rather than relying on the GIL making `+=` atomic: this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1) — and
`rapidfuzz`'s own scoring calls release the GIL during the compute itself (deep-dive §6),
so a bulk matching sweep across many receipts genuinely runs these counters from more than
one thread at once in practice, not just in theory.

The snapshot handed out is `MatchMetrics`, a frozen contract — a caller can never be holding a
view that mutates under it mid-read.
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import MatchMetrics

#: The counter names, derived from the contract itself so the two cannot drift apart. Adding
#: a counter means adding a field to `MatchMetrics` and nothing else.
COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(MatchMetrics))


class MatchMetricsCollector:
    """Thread-safe counters. One instance per Matching process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising.

        A metrics call is instrumentation on the matching hot path, whose whole job is to stay
        minimal and never be able to fail its caller — a typo'd counter name must not be what
        turns a legitimate empty-candidate answer into a failed match call.
        """
        if name not in self._counts or amount == 0:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> MatchMetrics:
        with self._lock:
            counts = dict(self._counts)
        return MatchMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "MatchMetricsCollector"]
