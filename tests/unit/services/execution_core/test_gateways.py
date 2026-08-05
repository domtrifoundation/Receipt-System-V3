"""`InMemoryCheckpointStore`/`InMemoryAttemptCounter` — real within one process's
lifetime (`gateways.py`'s own docstring states plainly why they aren't yet Persistence-
backed). Pure logic, no network."""

from __future__ import annotations

import asyncio

from services.execution_core.contracts import ReceiptStage, StageCheckpoint, utcnow
from services.execution_core.gateways import InMemoryAttemptCounter, InMemoryCheckpointStore


def run(coro):
    return asyncio.run(coro)


def test_checkpoint_store_returns_none_for_an_unknown_receipt_stage():
    store = InMemoryCheckpointStore()

    assert run(store.get_checkpoint("r1", ReceiptStage.OCRD)) is None


def test_checkpoint_store_round_trips_a_written_checkpoint():
    store = InMemoryCheckpointStore()
    checkpoint = StageCheckpoint(receipt_id="r1", run_id="run1", stage=ReceiptStage.OCRD, completed_at=utcnow(), stage_output_ref="merged text")

    run(store.write_checkpoint(checkpoint))

    assert run(store.get_checkpoint("r1", ReceiptStage.OCRD)) == checkpoint


def test_checkpoint_store_finds_a_written_checkpoint_by_content_hash():
    store = InMemoryCheckpointStore()
    checkpoint = StageCheckpoint(
        receipt_id="r1", run_id="run1", stage=ReceiptStage.WRITTEN, completed_at=utcnow(),
        stage_output_ref="persisted-id", content_hash="hash123",
    )

    run(store.write_checkpoint(checkpoint))

    assert run(store.find_written_by_content_hash("hash123")) == checkpoint


def test_checkpoint_store_never_reports_a_non_written_stage_as_already_written():
    store = InMemoryCheckpointStore()
    checkpoint = StageCheckpoint(
        receipt_id="r1", run_id="run1", stage=ReceiptStage.OCRD, completed_at=utcnow(),
        stage_output_ref="merged text", content_hash="hash123",
    )

    run(store.write_checkpoint(checkpoint))

    assert run(store.find_written_by_content_hash("hash123")) is None


def test_attempt_counter_starts_at_zero():
    counter = InMemoryAttemptCounter()

    assert run(counter.get_attempt_count("r1", ReceiptStage.OCRD)) == 0


def test_attempt_counter_increments_and_reads_back():
    counter = InMemoryAttemptCounter()

    run(counter.increment_attempt_count("r1", ReceiptStage.OCRD))
    run(counter.increment_attempt_count("r1", ReceiptStage.OCRD))

    assert run(counter.get_attempt_count("r1", ReceiptStage.OCRD)) == 2


def test_attempt_counter_tracks_receipt_and_stage_independently():
    counter = InMemoryAttemptCounter()

    run(counter.increment_attempt_count("r1", ReceiptStage.OCRD))

    assert run(counter.get_attempt_count("r1", ReceiptStage.MATCHED)) == 0
    assert run(counter.get_attempt_count("r2", ReceiptStage.OCRD)) == 0


def test_attempt_counter_escalation_latch_starts_false():
    counter = InMemoryAttemptCounter()

    assert run(counter.already_escalated("r1", ReceiptStage.OCRD)) is False


def test_attempt_counter_mark_escalated_latches():
    counter = InMemoryAttemptCounter()

    run(counter.mark_escalated("r1", ReceiptStage.OCRD))

    assert run(counter.already_escalated("r1", ReceiptStage.OCRD)) is True
    assert run(counter.already_escalated("r1", ReceiptStage.MATCHED)) is False
