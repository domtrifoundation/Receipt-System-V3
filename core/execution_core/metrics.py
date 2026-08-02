"""Execution Core's counters (§10.3, §11).

§10.3 identifies the one genuinely valuable profiling target for this API: **run-level latency
breakdown** — how much of a run's wall clock is spent in each pipeline stage, across many
concurrent runs. Explicitly *not* a `py-spy`/GIL-contention question, because §10.2 establishes
this API has no compute-bound pure-Python hot path to contend over; it coordinates other APIs'
work rather than doing its own.

So the counters here are per-stage-per-outcome rather than one global tally. A single
`stages_completed` number cannot answer "which stage is where the time and the failures are",
which is the only question §10.3 says is worth asking of this API.

`resumed` is counted separately from `completed` on purpose. It is the observable that proves
§6 is doing its job in production: a fleet where crashes happen and `resumed` stays at zero has
checkpointing that is not actually resuming anything, and nothing else would reveal that.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from common.frozen_dict import FrozenDict

from .contracts import ReceiptStage, StageOutcome


@dataclass(frozen=True)
class ExecutionMetrics:
    """A point-in-time snapshot. Frozen, and its maps are `FrozenDict` (§2.1, §2.1.1) — a
    snapshot a caller can edit is not a snapshot."""

    stage_outcomes: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    duplicates_skipped: int = 0
    runs_completed: int = 0
    runs_cancelled: int = 0

    def count(self, stage: ReceiptStage, outcome: StageOutcome) -> int:
        """How many times `stage` ended in `outcome`. Zero for a pair never seen."""
        return int(self.stage_outcomes.get((stage.value, outcome.value), 0))


class ExecutionMetricsCollector:
    """Mutable counters behind a lock.

    A real `threading.Lock` rather than relying on the GIL to make `+=` atomic
    (`docs/PRINCIPLES.md` §3.3.1). Under free-threading it is not, and this collector is reached
    from whatever thread a run's coordination happens on — the same reasoning every registry and
    collector in this repo already applies.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage_outcomes: dict[tuple[str, str], int] = {}
        self._duplicates_skipped = 0
        self._runs_completed = 0
        self._runs_cancelled = 0

    def record_stage(self, stage: ReceiptStage, outcome: StageOutcome) -> None:
        key = (stage.value, outcome.value)
        with self._lock:
            self._stage_outcomes[key] = self._stage_outcomes.get(key, 0) + 1

    def record_duplicate_skipped(self) -> None:
        """§4's run-level idempotency firing. Counted because a fleet where this is always zero
        either has no duplicates or has a content-hash check that never matches, and those need
        telling apart."""
        with self._lock:
            self._duplicates_skipped += 1

    def record_run_completed(self) -> None:
        with self._lock:
            self._runs_completed += 1

    def record_run_cancelled(self) -> None:
        with self._lock:
            self._runs_cancelled += 1

    def snapshot(self) -> ExecutionMetrics:
        with self._lock:
            return ExecutionMetrics(
                stage_outcomes=FrozenDict(dict(self._stage_outcomes)),
                duplicates_skipped=self._duplicates_skipped,
                runs_completed=self._runs_completed,
                runs_cancelled=self._runs_cancelled,
            )


__all__ = ["ExecutionMetrics", "ExecutionMetricsCollector"]
