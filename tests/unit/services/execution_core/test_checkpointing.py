"""Per-stage checkpointing and run-level idempotency (§6, §4, and §13's first hook).

§6 is "the one genuinely novel technique" this API's decision record identified, and every test
here is written to fail the way V2 failed: V2 retried a whole receipt from scratch on any
failure, throwing away completed expensive steps — especially LLM inference — every time.

The two asymmetries in `run_stage` are covered here too, because they read like inconsistency
and would otherwise be "cleaned up" into bugs: a checkpoint write failure is fatal, a Historian
outage is not.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.execution_core.checkpointing import already_written, completed_stages, run_stage
from services.execution_core.contracts import (
    ReceiptStage,
    STAGE_SEQUENCE,
    StageCheckpoint,
    StageOutcome,
    TERMINAL_STAGE,
)
from services.execution_core.errors import CheckpointWriteFailed
from services.execution_core.pipeline import Pipeline, ReceiptWork

from ._doubles import (
    FakeAttemptCounter,
    FakeCheckpointStore,
    RecordingFlagger,
    RecordingNarrator,
    make_run,
    run,
    stages_for,
)


# --------------------------------------------------------------------------------------------
# §13 hook 1 — checkpoint-resume
# --------------------------------------------------------------------------------------------



def test_a_retry_after_a_crash_resumes_at_the_failed_stage_and_never_re_runs_ocr():
    """§13's checkpoint-resume hook, and §6's entire value proposition.

    V2 retried a whole receipt from scratch on any failure, throwing away completed expensive
    steps — especially LLM inference — every time. This simulates a crash after `OCRD` and
    before `MATCHED`, then retries: OCR and every stage before it must not run again, because
    re-running OCR corroboration and Inference generation is precisely the waste §6 exists to
    eliminate.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    flagger = RecordingFlagger()
    first_pass: list[ReceiptStage] = []

    pipeline = Pipeline(store=store, counter=counter, flagger=flagger)
    crashed = run(
        pipeline.process_receipt(
            make_run(),
            ReceiptWork(
                receipt_id="r-1",
                stages=stages_for(first_pass, fail=ReceiptStage.MATCHED),
                content_hash="hash-1",
            ),
        )
    )
    assert crashed.outcome is StageOutcome.FAILED
    assert ReceiptStage.OCRD in first_pass

    second_pass: list[ReceiptStage] = []
    resumed = run(
        pipeline.process_receipt(
            make_run(),
            ReceiptWork(
                receipt_id="r-1", stages=stages_for(second_pass), content_hash="hash-1"
            ),
        )
    )

    assert resumed.outcome is StageOutcome.COMPLETED
    assert resumed.reached_stage is TERMINAL_STAGE
    assert ReceiptStage.OCRD not in second_pass, "OCR was re-run — §6's whole point is lost"
    assert ReceiptStage.PREPROCESSED not in second_pass
    assert second_pass[0] is ReceiptStage.MATCHED, "resume must start at the failed stage"


def test_a_resumed_stage_is_reported_as_resumed_and_not_as_completed():
    """A resume that reports itself as a fresh completion is unobservable in production.

    §6's mechanism is only verifiable if `RESUMED` and `COMPLETED` stay distinct: a fleet where
    crashes happen and the resumed counter stays at zero has checkpointing that is not actually
    resuming anything, and nothing else in the system would reveal that.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []
    fns = stages_for(calls)

    first = run(
        run_stage(
            store=store,
            run_id="run-1",
            receipt_id="r-1",
            stage=ReceiptStage.OCRD,
            fn=fns[ReceiptStage.OCRD],
        )
    )
    second = run(
        run_stage(
            store=store,
            run_id="run-1",
            receipt_id="r-1",
            stage=ReceiptStage.OCRD,
            fn=fns[ReceiptStage.OCRD],
        )
    )

    assert first == ("ocrd-output", False)
    assert second == ("ocrd-output", True)
    assert calls == [ReceiptStage.OCRD], "the stage callable ran twice despite a checkpoint"


def test_a_checkpoint_that_cannot_be_written_fails_the_attempt_rather_than_being_swallowed():
    """An uncheckpointed success is indistinguishable from a failure on the next pass.

    Swallowing the write failure would let the run believe expensive work was durable when it
    was not, and every subsequent attempt would silently redo it — reintroducing the V2 waste
    §6 exists to remove, but invisibly. `docs/PRINCIPLES.md` §4.4's degrade-gracefully rule does
    not extend here: this is the state that must not be quietly wrong.
    """
    store = FakeCheckpointStore(fail_writes_for={ReceiptStage.OCRD})
    calls: list[ReceiptStage] = []

    with pytest.raises(CheckpointWriteFailed):
        run(
            run_stage(
                store=store,
                run_id="run-1",
                receipt_id="r-1",
                stage=ReceiptStage.OCRD,
                fn=stages_for(calls)[ReceiptStage.OCRD],
            )
        )


def test_a_historian_outage_does_not_fail_the_stage_it_was_narrating():
    """The inverse asymmetry, and it must go the other way (`docs/PRINCIPLES.md` §4.4).

    A missing narrative line is a gap in a human-readable record. Failing a paid-for OCR run
    over an unreachable logging dependency turns one degraded component into an outage, which
    is the failure mode §4.4 exists to forbid.
    """
    store = FakeCheckpointStore()
    calls: list[ReceiptStage] = []

    value, resumed = run(
        run_stage(
            store=store,
            run_id="run-1",
            receipt_id="r-1",
            stage=ReceiptStage.OCRD,
            fn=stages_for(calls)[ReceiptStage.OCRD],
            narrator=RecordingNarrator(raises=True),
        )
    )

    assert (value, resumed) == ("ocrd-output", False)
    assert store.writes, "the checkpoint must still be durable"


def test_a_resumed_stage_does_not_emit_a_second_narrative_entry():
    """Historian's record must not claim a receipt was OCR'd twice because a process crashed.

    §6 makes `run_stage` the narrative emission chokepoint so coverage is structural. That only
    produces a true account if a resume — which did no work — emits nothing.
    """
    store = FakeCheckpointStore()
    narrator = RecordingNarrator()
    calls: list[ReceiptStage] = []
    fn = stages_for(calls)[ReceiptStage.INFERRED]

    for _ in range(3):
        run(
            run_stage(
                store=store,
                run_id="run-1",
                receipt_id="r-1",
                stage=ReceiptStage.INFERRED,
                fn=fn,
                narrator=narrator,
            )
        )

    assert len(narrator.emissions) == 1


def test_completed_stages_reports_a_hole_rather_than_stopping_at_the_first_miss():
    """A checkpoint set with a gap in it is a real state, not an impossible one.

    A stage's write can fail while a later one succeeds on an earlier attempt. Treating the
    first missing checkpoint as the resume point would silently skip every completed stage
    after the hole and report work as done that was never recorded.
    """
    store = FakeCheckpointStore()
    for stage in (ReceiptStage.INGESTED, ReceiptStage.OCRD):
        run(
            store.write_checkpoint(
                StageCheckpoint(
                    receipt_id="r-1",
                    run_id="run-1",
                    stage=stage,
                    completed_at=datetime.now(timezone.utc),
                )
            )
        )

    found = run(completed_stages(store, "r-1", STAGE_SEQUENCE))
    assert found == (ReceiptStage.INGESTED, ReceiptStage.OCRD)

# --------------------------------------------------------------------------------------------
# §4 — run-level idempotency, keyed on content and never on mtime
# --------------------------------------------------------------------------------------------



def test_content_already_written_is_skipped_entirely_rather_than_reprocessed():
    """§4's run-level idempotency: the same bytes must not be processed twice.

    V2's own `_file_fingerprint()` validated the reasoning the hard way — cloud sync
    (Drive/OneDrive/Dropbox) touches mtime on bytes that did not change, so an mtime-keyed check
    reprocesses receipts that are already fully in the database. Reprocessing costs an OCR and
    an inference pass per false positive.
    """
    store = FakeCheckpointStore()
    counter = FakeAttemptCounter()
    pipeline = Pipeline(store=store, counter=counter, flagger=RecordingFlagger())

    first: list[ReceiptStage] = []
    run(
        pipeline.process_receipt(
            make_run(),
            ReceiptWork(receipt_id="r-1", stages=stages_for(first), content_hash="same-bytes"),
        )
    )

    second: list[ReceiptStage] = []
    outcome = run(
        pipeline.process_receipt(
            make_run(),
            ReceiptWork(receipt_id="r-2", stages=stages_for(second), content_hash="same-bytes"),
        )
    )

    assert outcome.skipped_as_duplicate is True
    assert outcome.written is True
    assert second == [], "a duplicate ran the pipeline anyway"
    assert pipeline.metrics.snapshot().duplicates_skipped == 1


def test_the_same_bytes_under_a_new_receipt_id_are_still_recognised_as_already_written():
    """§4 asks a question about content, not about a receipt id.

    A file re-uploaded under a new name gets a new receipt id and the same bytes. Keying the
    check on receipt id would miss exactly the case a content hash exists to catch.
    """
    store = FakeCheckpointStore()
    run(
        store.write_checkpoint(
            StageCheckpoint(
                receipt_id="original",
                run_id="run-0",
                stage=TERMINAL_STAGE,
                completed_at=datetime.now(timezone.utc),
                content_hash="abc123",
            )
        )
    )
    assert run(already_written(store, "abc123")) is True


def test_an_empty_content_hash_is_never_treated_as_a_match():
    """An unanswerable question must not answer itself as "yes".

    A receipt whose hash has not been computed yet would otherwise match the first stored
    checkpoint with an empty hash and be skipped entirely — silently dropping a real receipt
    that nobody has processed.
    """
    store = FakeCheckpointStore()
    assert run(already_written(store, "")) is False
