"""Reconciliation's counters (§5).

Per-check-per-outcome rather than one global tally, for the reason §4.12 gives about ATP and
which generalises to the whole inventory: `INCONCLUSIVE` is real information, and a collector
that only counted hits would make a check that has silently stopped being able to run look
exactly like a check that is finding nothing wrong. Those need telling apart — the first is a
broken check, the second is a clean corpus.

`propagations_resumed` is the observable that proves §8's atomicity resolution is actually
wired: a fleet where crashes happen and this counter stays at zero has propagation that restarts
batches rather than resuming them, and nothing else in the system would reveal it.

A real `threading.Lock` rather than relying on the GIL making `+=` atomic
(`docs/PRINCIPLES.md` §3.3.1). §3 dispatches bulk propagation through Background Workers'
`CPU_PROCESS` class, so this collector is genuinely reached from more than one worker.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from common.frozen_dict import FrozenDict

from .contracts import CheckOutcome


@dataclass(frozen=True)
class ReconciliationMetrics:
    """A point-in-time snapshot. Frozen, and its map is a `FrozenDict` (§2.1, §2.1.1) — a
    snapshot a caller can edit is not a snapshot."""

    check_outcomes: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    propagations_applied: int = 0
    propagations_resumed: int = 0
    propagations_conflicted: int = 0

    def count(self, check_name: str, outcome: CheckOutcome) -> int:
        """How many times `check_name` concluded `outcome`. Zero for a pair never seen."""
        return int(self.check_outcomes.get((check_name, outcome.value), 0))


class ReconciliationMetricsCollector:
    """Mutable counters behind a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._check_outcomes: dict[tuple[str, str], int] = {}
        self._applied = 0
        self._resumed = 0
        self._conflicted = 0

    def record_check(self, check_name: str, outcome: CheckOutcome) -> None:
        key = (check_name, outcome.value)
        with self._lock:
            self._check_outcomes[key] = self._check_outcomes.get(key, 0) + 1

    def record_propagation_applied(self) -> None:
        with self._lock:
            self._applied += 1

    def record_propagation_resumed(self) -> None:
        """§8's resume actually happening. See this module's docstring."""
        with self._lock:
            self._resumed += 1

    def record_propagation_conflict(self) -> None:
        """A correction left unapplied because it disagreed with current state (§4.3)."""
        with self._lock:
            self._conflicted += 1

    def snapshot(self) -> ReconciliationMetrics:
        with self._lock:
            return ReconciliationMetrics(
                check_outcomes=FrozenDict(dict(self._check_outcomes)),
                propagations_applied=self._applied,
                propagations_resumed=self._resumed,
                propagations_conflicted=self._conflicted,
            )


__all__ = ["ReconciliationMetrics", "ReconciliationMetricsCollector"]
