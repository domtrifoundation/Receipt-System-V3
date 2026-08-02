"""Per-receipt orchestration: cancellation, sequencing, and the watchdog (§1, §8, §9, §13's third hook).

§8's fix is the one with a number attached to it — V2's 156-receipt EXTREME-mode run kept going
for minutes after a stop request, because the stop signal was checked between runs rather than
between receipts. Every cancellation test here is written to fail if that check moves back out
of the receipt loop.
"""

from __future__ import annotations


from common.frozen_dict import FrozenDict
from services.execution_core.contracts import (
    ExecutionConfig,
    ReceiptStage,
    RetryConfig,
    RunState,
    STAGE_SEQUENCE,
    StageOutcome,
)
from services.execution_core.pipeline import Pipeline, ReceiptWork
from services.execution_core.retry_policy import PROCESSING_FAILED_FLAG
from services.execution_core.watchdog_hooks import ConfigReloader, SERVICE_NAME, WatchdogHooks

from ._doubles import (
    FakeAttemptCounter,
    FakeCheckpointStore,
    RecordingFlagger,
    RecordingKicker,
    make_run,
    run,
    stages_for,
)


# --------------------------------------------------------------------------------------------
# §13 hook 3 — per-receipt cancellation
# --------------------------------------------------------------------------------------------



def test_a_cancelled_run_stops_within_one_receipt_rather_than_finishing_the_batch():
    """§13's per-receipt cancellation hook — the concrete fix for V2's 156-receipt bug.

    V2 checked its stop signal between runs, so a 156-receipt EXTREME-mode run kept going for
    minutes after the user asked it to stop. §8 requires the check at the top of *every*
    receipt. Here the cancellation lands after the second receipt: the third must not start a
    single stage.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    pipeline = Pipeline(store=store, counter=counter, flagger=RecordingFlagger())
    run_obj = make_run()

    processed: list[str] = []
    cancelled_flag = {"value": False}

    def make_work(receipt_id: str) -> ReceiptWork:
        async def _stage():
            processed.append(receipt_id)
            if len(processed) == 2:
                cancelled_flag["value"] = True
            return f"{receipt_id}-ok"

        return ReceiptWork(receipt_id=receipt_id, stages={ReceiptStage.OCRD: _stage})

    work_items = tuple(make_work(f"r-{i}") for i in range(5))
    outcome = run(
        pipeline.process_run(run_obj, work_items, cancelled=lambda: cancelled_flag["value"])
    )

    assert processed == ["r-0", "r-1"], "processing continued past the stop request"
    assert outcome.cancelled_after == 2
    cancelled = [r for r in outcome.receipts if r.outcome is StageOutcome.CANCELLED]
    assert [r.receipt_id for r in cancelled] == ["r-2", "r-3", "r-4"]


def test_receipts_never_started_are_reported_as_cancelled_rather_than_omitted():
    """A caller has to know which receipts still need processing.

    An outcome list that simply ends early is indistinguishable from a run that had fewer
    receipts than it did, so the un-started ones would silently never be retried.
    """
    store = FakeCheckpointStore()
    pipeline = Pipeline(
        store=store, counter=FakeAttemptCounter(), flagger=RecordingFlagger()
    )
    work_items = tuple(
        ReceiptWork(receipt_id=f"r-{i}", stages={}) for i in range(4)
    )

    outcome = run(pipeline.process_run(make_run(), work_items, cancelled=lambda: True))

    assert len(outcome.receipts) == 4
    assert all(r.outcome is StageOutcome.CANCELLED for r in outcome.receipts)


def test_a_run_already_shutting_down_processes_nothing_at_all():
    """The degenerate case the default cancellation signal has to get right.

    `process_run` defaults to reading the run's own state when no live signal is supplied. A run
    handed over already `SHUTTING_DOWN` must start no receipt — otherwise a stop that landed
    just before dispatch is ignored entirely.
    """
    processed: list[str] = []

    async def _stage():
        processed.append("ran")
        return "x"

    pipeline = Pipeline(
        store=FakeCheckpointStore(),
        counter=FakeAttemptCounter(),
        flagger=RecordingFlagger(),
    )
    outcome = run(
        pipeline.process_run(
            make_run(state=RunState.SHUTTING_DOWN),
            (ReceiptWork(receipt_id="r-1", stages={ReceiptStage.OCRD: _stage}),),
        )
    )

    assert processed == []
    assert outcome.receipts[0].outcome is StageOutcome.CANCELLED


def test_cancellation_is_not_a_configurable_interval():
    """§12: `cancellation_check_interval` is "not configurable to anything coarser — this is a
    hard requirement, not a tunable".

    The only way to make that true is to give it no knob at all. A field defaulted to
    "per_receipt" would be a knob someone could turn, and turning it is how V2's bug comes back.
    """
    config = ExecutionConfig()
    assert not hasattr(config, "cancellation_check_interval")
    assert "cancellation_check_interval" not in {f for f in config.__dataclass_fields__}

# --------------------------------------------------------------------------------------------
# §1 — stage sequencing and the boundary
# --------------------------------------------------------------------------------------------



def test_stages_run_in_the_exact_order_the_deep_dive_specifies():
    """§1's sequence: Ingestion → Preprocessing → OCR → Matching → Geo → Inference → write.

    The order is not arbitrary — Matching consumes OCR's text, Inference consumes Matching's
    vendor context. Running Inference before Matching would feed it a context that does not
    exist yet, producing an extraction with no vendor corroboration at all.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []
    pipeline = Pipeline(
        store=store, counter=FakeAttemptCounter(), flagger=RecordingFlagger()
    )

    run(
        pipeline.process_receipt(
            make_run(), ReceiptWork(receipt_id="r-1", stages=stages_for(calls))
        )
    )

    assert calls == list(STAGE_SEQUENCE)


def test_a_stage_with_nothing_to_do_is_skipped_rather_than_failing_the_receipt():
    """`docs/PRINCIPLES.md` §4.4 applied to the pipeline.

    A receipt with no address to geocode has nothing for the `GEOD` stage to do. Failing the
    run over it would make a perfectly good receipt unprocessable because one optional stage had
    no input — the same shape as a missing OCR engine failing a run instead of being unavailable.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []
    stages = stages_for(calls)
    del stages[ReceiptStage.GEOD]

    pipeline = Pipeline(
        store=store, counter=FakeAttemptCounter(), flagger=RecordingFlagger()
    )
    outcome = run(
        pipeline.process_receipt(make_run(), ReceiptWork(receipt_id="r-1", stages=stages))
    )

    assert outcome.outcome is StageOutcome.COMPLETED
    assert outcome.written is True
    assert ReceiptStage.GEOD not in calls


def test_a_pipeline_accepts_a_frozen_mapping_of_stages_without_an_isinstance_dict_check():
    """`docs/PRINCIPLES.md` §2.1: the 3.15 builtin `frozendict` is not a `dict` subclass.

    Any `isinstance(x, dict)` on this path would silently take the wrong branch and report a
    receipt as having no stages at all — it would process nothing and report success.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []
    frozen_stages = FrozenDict(stages_for(calls))

    pipeline = Pipeline(
        store=store, counter=FakeAttemptCounter(), flagger=RecordingFlagger()
    )
    outcome = run(
        pipeline.process_receipt(
            make_run(), ReceiptWork(receipt_id="r-1", stages=frozen_stages)
        )
    )

    assert outcome.written is True
    assert calls == list(STAGE_SEQUENCE)


def test_a_failed_stage_reports_the_last_stage_that_actually_completed():
    """"How far did this receipt get" is the question a retry and a human both need answered.

    Reporting the failed stage as reached would make a resume start one stage too late and skip
    real work; reporting nothing would make it start from the beginning, which is the V2
    behaviour §6 replaced.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []
    pipeline = Pipeline(
        store=store, counter=FakeAttemptCounter(), flagger=RecordingFlagger()
    )

    outcome = run(
        pipeline.process_receipt(
            make_run(),
            ReceiptWork(
                receipt_id="r-1", stages=stages_for(calls, fail=ReceiptStage.INFERRED)
            ),
        )
    )

    assert outcome.outcome is StageOutcome.FAILED
    assert outcome.reached_stage is ReceiptStage.GEOD
    assert outcome.written is False


def test_the_configured_retry_cap_is_the_one_the_pipeline_actually_applies():
    """A config value the pipeline reads once and ignores is worse than no config value.

    §12's `max_attempts_per_stage` has to reach `attempt_stage`, or an owner who lowered it to
    stop a flood of retries would watch the flood continue.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    flagger = RecordingFlagger()
    invocations: list[int] = []

    async def _always_fails():
        invocations.append(1)
        raise RuntimeError("nope")

    pipeline = Pipeline(
        store=store,
        counter=counter,
        flagger=flagger,
        config=ExecutionConfig(retry=RetryConfig(max_attempts_per_stage=1)),
    )
    work = ReceiptWork(receipt_id="r-1", stages={ReceiptStage.OCRD: _always_fails})

    run(pipeline.process_receipt(make_run(), work))
    run(pipeline.process_receipt(make_run(), work))

    assert len(invocations) == 1
    assert flagger.flags and flagger.flags[0][1] == PROCESSING_FAILED_FLAG

# --------------------------------------------------------------------------------------------
# §9 — watchdog kicks and config hot-reload
# --------------------------------------------------------------------------------------------



def test_the_watchdog_is_kicked_inside_the_receipt_loop_and_not_only_around_the_run():
    """§9: kicks happen "at start of each cycle and throughout any idle wait".

    A process that kicks only between runs looks perfectly healthy while wedged forever inside
    one — which is precisely the hang Watchdog exists to catch. Counting kicks against receipts
    is the only way to test "inside" rather than merely "at all".
    """
    kicker = RecordingKicker()
    hooks = WatchdogHooks(kicker=kicker, instance_id="exec-1")
    pipeline = Pipeline(
        store=FakeCheckpointStore(),
        counter=FakeAttemptCounter(),
        flagger=RecordingFlagger(),
        watchdog=hooks,
    )
    work_items = tuple(ReceiptWork(receipt_id=f"r-{i}", stages={}) for i in range(4))

    run(pipeline.process_run(make_run(), work_items))

    assert hooks.kick_count > len(work_items), "kicks did not happen per receipt"
    assert all(service == SERVICE_NAME for service, _ in kicker.kicks)


def test_an_unreachable_watchdog_does_not_fail_the_run_it_was_monitoring():
    """`docs/PRINCIPLES.md` §4.4. Failing a run because the health reporter is down turns one
    degraded component into an outage — the inverse of what monitoring is for."""
    kicker = RecordingKicker(raises=True)
    hooks = WatchdogHooks(kicker=kicker)
    pipeline = Pipeline(
        store=FakeCheckpointStore(),
        counter=FakeAttemptCounter(),
        flagger=RecordingFlagger(),
        watchdog=hooks,
    )

    outcome = run(
        pipeline.process_run(make_run(), (ReceiptWork(receipt_id="r-1", stages={}),))
    )

    assert outcome.receipts[0].outcome is StageOutcome.COMPLETED
    assert hooks.failed_kicks > 0
    assert hooks.kick_count == 0


def test_a_config_change_applies_to_the_next_run_and_never_mid_run():
    """§9: config changes apply to the *next* run without a service restart.

    A run whose concurrency or retry cap changed halfway through would have two different sets
    of semantics inside one batch, and no way to explain afterwards which receipts got which.
    """
    reloader = ConfigReloader()
    original = reloader.active

    reloader.stage(ExecutionConfig(retry=RetryConfig(max_attempts_per_stage=9)))
    assert reloader.active is original, "a staged config leaked into the in-flight run"

    applied = reloader.apply_for_next_run()
    assert applied.retry.max_attempts_per_stage == 9
    assert reloader.reload_count == 1


def test_the_reload_counter_only_ticks_when_a_config_actually_changed_hands():
    """§9 wants a support session to confirm "this run picked up the change made five minutes
    ago" as a fact rather than an assumption.

    A counter that ticked on every run would instead answer "how many runs have there been",
    which nobody asked and which makes the real question unanswerable.
    """
    reloader = ConfigReloader()
    for _ in range(5):
        reloader.apply_for_next_run()
    assert reloader.reload_count == 0

    reloader.stage(ExecutionConfig())
    reloader.apply_for_next_run()
    reloader.apply_for_next_run()
    assert reloader.reload_count == 1
