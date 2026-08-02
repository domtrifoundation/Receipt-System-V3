"""Bounded retry and escalation (§7, and §13's fourth hook).

Two of these tests exist because §7's own sketch contradicts §7's own stated motivation: the
sketch calls `create_flag` unconditionally whenever the cap check trips, which recreates the
motivating bug ("one bad scan produced 57 identical warnings in a single session") with flags
instead of warnings. `retry_policy.py` latches the escalation instead, and these tests are what
hold that correction in place.
"""

from __future__ import annotations


from core.execution_core.contracts import ReceiptStage, StageOutcome
from core.execution_core.retry_policy import PROCESSING_FAILED_FLAG, attempt_stage

from ._doubles import (
    FakeAttemptCounter,
    FakeCheckpointStore,
    RecordingFlagger,
    run,
    stages_for,
)


# --------------------------------------------------------------------------------------------
# §13 hook 4 — escalation
# --------------------------------------------------------------------------------------------



def test_a_stage_that_fails_its_cap_escalates_to_a_review_flag_and_stops_retrying():
    """§13's escalation hook (§7).

    V2 moved a repeatedly-failing receipt into a physical `failed/` folder, which does not fit
    the folderless content-addressable blob model at all. V3 escalates to a Review/Flagging flag
    so a human resolves it. The second half of the guarantee matters as much as the first: after
    escalation the stage callable must never run again, or the "bounded" in bounded retry means
    nothing.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    flagger = RecordingFlagger()
    invocations: list[int] = []

    async def _always_fails():
        invocations.append(1)
        raise RuntimeError("bad scan")

    for _ in range(3):
        result = run(
            attempt_stage(
                store=store,
                counter=counter,
                flagger=flagger,
                run_id="run-1",
                receipt_id="r-1",
                stage=ReceiptStage.OCRD,
                fn=_always_fails,
                max_attempts=3,
            )
        )
        assert result.outcome is StageOutcome.FAILED

    escalated = run(
        attempt_stage(
            store=store,
            counter=counter,
            flagger=flagger,
            run_id="run-1",
            receipt_id="r-1",
            stage=ReceiptStage.OCRD,
            fn=_always_fails,
            max_attempts=3,
        )
    )

    assert escalated.outcome is StageOutcome.ESCALATED
    assert len(invocations) == 3, "the stage ran again after escalating"
    assert flagger.flags[0][1] == PROCESSING_FAILED_FLAG


def test_escalation_creates_exactly_one_flag_no_matter_how_often_the_receipt_is_swept():
    """§7's own motivating bug is "one bad scan produced 57 identical warnings in a session".

    §7's sketch calls `create_flag` unconditionally every time the cap check trips, which
    recreates that exact bug with flags instead of warnings — a receipt swept fifty times
    produces fifty identical flags in a staff review queue. The escalation is therefore latched.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    flagger = RecordingFlagger()

    async def _always_fails():
        raise RuntimeError("bad scan")

    for _ in range(20):
        run(
            attempt_stage(
                store=store,
                counter=counter,
                flagger=flagger,
                run_id="run-1",
                receipt_id="r-1",
                stage=ReceiptStage.OCRD,
                fn=_always_fails,
                max_attempts=2,
            )
        )

    assert len(flagger.flags) == 1, f"{len(flagger.flags)} identical flags — §7's bug is back"


def test_an_escalated_stage_is_distinguishable_from_a_stage_whose_output_was_none():
    """§7's sketch returns `None` on escalation, and the two cases demand opposite handling.

    A caller that reads them the same way either retries a receipt that has already given up or
    abandons one that merely produced nothing. `docs/PRINCIPLES.md` §4.1 — the outcome is data.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()

    async def _returns_none():
        return None

    produced_none = run(
        attempt_stage(
            store=store,
            counter=counter,
            flagger=RecordingFlagger(),
            run_id="run-1",
            receipt_id="r-1",
            stage=ReceiptStage.GEOD,
            fn=_returns_none,
        )
    )

    assert produced_none.value is None
    assert produced_none.outcome is StageOutcome.COMPLETED
    assert produced_none.ok is True


def test_the_attempt_counter_is_not_incremented_by_a_successful_or_resumed_pass():
    """Counting entries rather than failures would escalate a receipt that never failed.

    Three interrupted-but-successful passes over the same receipt would trip a cap of three and
    flag a perfectly good receipt for human review — noise in the exact queue §7 exists to keep
    meaningful.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    calls: list[ReceiptStage] = []
    fn = stages_for(calls)[ReceiptStage.OCRD]

    for _ in range(5):
        run(
            attempt_stage(
                store=store,
                counter=counter,
                flagger=RecordingFlagger(),
                run_id="run-1",
                receipt_id="r-1",
                stage=ReceiptStage.OCRD,
                fn=fn,
                max_attempts=3,
            )
        )

    assert run(counter.get_attempt_count("r-1", ReceiptStage.OCRD)) == 0


def test_the_escalation_flag_carries_the_stage_and_attempt_count_as_a_frozen_mapping():
    """A flag saying only "processing failed" sends a human to look at nothing in particular.

    `docs/PRINCIPLES.md` §2.1: the details are a `FrozenDict`, so the flag Review/Flagging
    stores cannot be mutated by whichever consumer reads it next — and any `isinstance` check
    against it must test `collections.abc.Mapping`, because the 3.15 builtin is not a `dict`
    subclass.
    """
    import collections.abc

    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    flagger = RecordingFlagger()
    counter.counts[("r-1", ReceiptStage.INFERRED)] = 3

    async def _noop():
        return None

    run(
        attempt_stage(
            store=store,
            counter=counter,
            flagger=flagger,
            run_id="run-9",
            receipt_id="r-1",
            stage=ReceiptStage.INFERRED,
            fn=_noop,
            max_attempts=3,
        )
    )

    _, _, details = flagger.flags[0]
    assert isinstance(details, collections.abc.Mapping)
    assert details["stage"] == ReceiptStage.INFERRED.value
    assert details["attempts"] == 3
    assert details["run_id"] == "run-9"
