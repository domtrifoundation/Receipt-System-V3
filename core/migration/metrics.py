"""Counters for this API's own behaviour, and the immutable snapshot of them.

The interesting pair is `steps_applied` against `steps_already_applied`. A batch re-run after
an interruption should show mostly the latter — if it shows mostly the former, either the
first run did less than it reported or the steps' own idempotency checks are not working,
and §8's whole reason for asking about idempotency is that both are easy to get wrong and
invisible without this split.

`chain_gaps_detected` should be permanently zero. §8 wants a missing step caught by the
chain-integrity check in CI, never discovered mid-migration on a live system — so a non-zero
value here means that check did not run, or ran against a different registry than the one in
production.

Plain `dict` behind a real lock rather than a `FrozenDict`: these are mutable counters, not a
constant (`docs/PRINCIPLES.md` §2.1.1), and §4's bulk case runs migrations from a process pool,
so the lock is not a GIL assumption (§3.3.1).
"""

from __future__ import annotations

import threading
from dataclasses import fields

from .contracts import MigrationMetrics

COUNTER_NAMES: tuple[str, ...] = tuple(f.name for f in fields(MigrationMetrics))


class MigrationMetricsCollector:
    """Thread-safe counters. One instance per Migration process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {name: 0 for name in COUNTER_NAMES}

    def increment(self, name: str, amount: int = 1) -> None:
        """Unknown names are ignored rather than raising — instrumentation must never be what
        fails a migration."""
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> MigrationMetrics:
        with self._lock:
            counts = dict(self._counts)
        return MigrationMetrics(**counts)

    def reset(self) -> None:
        with self._lock:
            for name in self._counts:
                self._counts[name] = 0


__all__ = ["COUNTER_NAMES", "MigrationMetricsCollector"]
