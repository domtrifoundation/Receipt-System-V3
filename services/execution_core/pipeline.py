"""Stage sequencing and per-receipt orchestration (§1's sequence, §4, §8).

This is the loop V2 got wrong in three separate ways, each fixed structurally rather than by
being more careful:

* **V2's `daemon_loop` instantiated the menu system, keyboard listener and dashboard inside the
  same loop that ran the pipeline** (§1). Nothing in this file knows what a UI is. Interface
  reaches Execution Core only through `service.py`'s gRPC surface, which makes that coupling
  impossible to reintroduce rather than merely discouraged.
* **V2 retried a whole receipt from scratch on any failure** (§6). Every stage here goes through
  `attempt_stage` → `run_stage`, so a retry resumes at the first incomplete stage.
* **V2's stop request took minutes to take effect** — a 156-receipt EXTREME-mode run kept going
  after the user asked it to stop (§8). Cancellation is checked at the top of *every receipt*,
  so a stop lands within one receipt's processing time rather than one batch's.

That last check is deliberately not configurable. §12 lists `cancellation_check_interval:
per_receipt` and states it is "not configurable to anything coarser — this is a hard requirement,
not a tunable", so `ExecutionConfig` has no field for it and this loop has no branch on it.

**No pipeline stage's logic lives here.** §1's boundary is explicit: Execution Core calls
Ingestion, Preprocessing, OCR, Matching, Geo, Inference and Persistence through their own gRPC
contracts and never reimplements a fragment of what any of them do. Concretely, that is why
stages arrive here as a mapping of `ReceiptStage` to a zero-argument awaitable — the caller
closes over each API's own request shape, and this file stays ignorant of all seven.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .checkpointing import already_written
from .contracts import (
    AttemptCounter,
    CheckpointStore,
    ExecutionConfig,
    HistorianNarrator,
    ReceiptOutcome,
    ReceiptStage,
    ReviewFlagger,
    Run,
    RunOutcome,
    STAGE_SEQUENCE,
    StageCallable,
    StageOutcome,
    TERMINAL_STAGE,
)
from .metrics import ExecutionMetricsCollector
from .retry_policy import attempt_stage
from .state_machine import is_cancelled
from .watchdog_hooks import WatchdogHooks


@dataclass(frozen=True)
class ReceiptWork:
    """One receipt and the stage callables that will process it.

    `stages` is a `Mapping` rather than a `dict` in the annotation because a caller may hand us
    a `FrozenDict`, and the 3.15 builtin is not a `dict` subclass (`docs/PRINCIPLES.md` §2.1) —
    an `isinstance(x, dict)` check anywhere on this path would silently take the wrong branch.

    A stage absent from the mapping is skipped rather than failed. Not laxity: §4.4's degrade-
    gracefully rule applied to the pipeline means a receipt with no address to geocode does not
    fail its run over a `GEOD` stage that had nothing to do.
    """

    receipt_id: str
    stages: Mapping[ReceiptStage, StageCallable]
    content_hash: str = ""


class Pipeline:
    """Per-receipt orchestration across §1's stage sequence.

    Holds no run state of its own. Runs are the scheduler's and the state machine's; this class
    is the thing that walks one receipt through stages and one run through receipts, which is
    what lets both be tested without standing up either of the other two.
    """

    def __init__(
        self,
        *,
        store: CheckpointStore,
        counter: AttemptCounter,
        flagger: ReviewFlagger,
        config: ExecutionConfig | None = None,
        narrator: HistorianNarrator | None = None,
        watchdog: WatchdogHooks | None = None,
        metrics: ExecutionMetricsCollector | None = None,
    ) -> None:
        self._store = store
        self._counter = counter
        self._flagger = flagger
        self._config = config or ExecutionConfig()
        self._narrator = narrator
        self._watchdog = watchdog or WatchdogHooks()
        self._metrics = metrics or ExecutionMetricsCollector()

    @property
    def metrics(self) -> ExecutionMetricsCollector:
        return self._metrics

    @property
    def config(self) -> ExecutionConfig:
        return self._config

    async def process_receipt(self, run: Run, work: ReceiptWork) -> ReceiptOutcome:
        """Walk one receipt through §1's stage sequence.

        Returns early and truthfully in three cases: the content is already fully written (§4),
        a stage escalated (§7), or a stage failed. None of them raise — a run's outcome is data
        all the way out (`docs/PRINCIPLES.md` §4.1).
        """
        if await already_written(self._store, work.content_hash):
            self._metrics.record_duplicate_skipped()
            return ReceiptOutcome(
                receipt_id=work.receipt_id,
                run_id=run.run_id,
                reached_stage=TERMINAL_STAGE,
                outcome=StageOutcome.COMPLETED,
                skipped_as_duplicate=True,
            )

        reached: ReceiptStage | None = None
        for stage in STAGE_SEQUENCE:
            fn = work.stages.get(stage)
            if fn is None:
                continue

            attempt = await attempt_stage(
                store=self._store,
                counter=self._counter,
                flagger=self._flagger,
                run_id=run.run_id,
                receipt_id=work.receipt_id,
                stage=stage,
                fn=fn,
                max_attempts=self._config.retry.max_attempts_per_stage,
                narrator=self._narrator,
                content_hash=work.content_hash,
            )
            self._metrics.record_stage(stage, attempt.outcome)

            if not attempt.ok:
                return ReceiptOutcome(
                    receipt_id=work.receipt_id,
                    run_id=run.run_id,
                    reached_stage=reached,
                    outcome=attempt.outcome,
                    error=attempt.error,
                )
            reached = stage

        return ReceiptOutcome(
            receipt_id=work.receipt_id,
            run_id=run.run_id,
            reached_stage=reached,
            outcome=StageOutcome.COMPLETED,
        )

    async def process_run(
        self,
        run: Run,
        work_items: tuple[ReceiptWork, ...],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RunOutcome:
        """Walk a whole run's receipts, checking cancellation before each one (§8).

        The cancellation check is at the **top of the receipt loop**, before any stage callable
        is invoked. §8's fix is precisely this placement: checking only between runs is what let
        V2's 156-receipt run keep going for minutes after a stop request. Receipts not started
        when the stop lands are reported as cancelled rather than silently dropped — a caller
        needs to know which receipts still need processing, and an outcome list that simply ends
        early cannot tell it.

        **`cancelled` is a callable, and it has to be.** `Run` is a frozen dataclass and
        `state_machine.transition` returns a *new* one, so the object handed to this method can
        never change state while the loop is running — re-reading `run.state` each iteration
        would read the same snapshot every time and the per-receipt check would be decorative.
        The callable is the live signal: `service.py` closes it over the run registry, so a
        `CancelRun` RPC arriving mid-batch is visible to the very next iteration. The default
        preserves the honest degenerate case — a run already `SHUTTING_DOWN` when it was handed
        over processes nothing.
        """
        is_cancelled_now = cancelled if cancelled is not None else (lambda: is_cancelled(run))
        self._watchdog.kick()
        outcomes: list[ReceiptOutcome] = []
        cancelled_after = 0

        for index, work in enumerate(work_items):
            self._watchdog.kick()

            if is_cancelled_now():
                cancelled_after = index
                self._metrics.record_run_cancelled()
                outcomes.extend(
                    ReceiptOutcome(
                        receipt_id=remaining.receipt_id,
                        run_id=run.run_id,
                        reached_stage=None,
                        outcome=StageOutcome.CANCELLED,
                        error="run cancelled before this receipt started",
                    )
                    for remaining in work_items[index:]
                )
                return RunOutcome(
                    run_id=run.run_id,
                    state=run.state,
                    receipts=tuple(outcomes),
                    cancelled_after=cancelled_after,
                )

            outcomes.append(await self.process_receipt(run, work))

        self._metrics.record_run_completed()
        return RunOutcome(
            run_id=run.run_id,
            state=run.state,
            receipts=tuple(outcomes),
            cancelled_after=len(work_items),
        )


__all__ = ["Pipeline", "ReceiptWork"]
