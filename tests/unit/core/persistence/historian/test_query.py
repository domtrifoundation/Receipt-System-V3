"""Interleaved history, and the rescan-continuity hook named in §13 of Historian's own doc."""

from __future__ import annotations

from core.persistence.db.receipts import ReceiptRepository
from core.persistence.historian.contracts import (
    HistorianEvent,
    NarrativeEvent,
    NarrativeStage,
)
from core.persistence.historian.narrative.summarizers import summarize
from core.persistence.historian.query import HistorianQuery
from core.persistence.historian.writer import HistorianWriter

from ..conftest import make_receipt, run


def _seed_scan(db, run_id: str, triggered_by: str = "initial_scan"):
    writer = HistorianWriter(db)
    for stage in ("run_started", "ingested", "preprocessed"):
        run(writer.append_narrative_batch(summarize(stage, "rc1", run_id, {}, triggered_by)))


def test_both_tracks_interleave_chronologically(db):
    repo = ReceiptRepository(db)
    query = HistorianQuery(db)

    _seed_scan(db, "run-1")
    run(repo.save(make_receipt(), actor="worker"))
    run(repo.apply_field_updates("rc1", {"vendor_name": "Corrected"}, actor="human:u1"))

    history = run(query.get_receipt_history("rc1"))

    assert any(isinstance(e, NarrativeEvent) for e in history)
    assert any(isinstance(e, HistorianEvent) for e in history)
    timestamps = [e.occurred_at for e in history]
    assert timestamps == sorted(timestamps), "the merged feed must be chronological"


def test_a_rescan_coexists_with_the_original_narrative(db):
    """Rescan continuity: the original deliberation stays intact underneath the new one."""
    query = HistorianQuery(db)
    _seed_scan(db, "run-1")
    _seed_scan(db, "run-2", "system_rescan:new_ocr_engine_promoted")

    first = run(query.narrative_for_run("rc1", "run-1"))
    second = run(query.narrative_for_run("rc1", "run-2"))

    assert len(first) == 3, "the original scan's narrative was overwritten"
    assert len(second) == 3
    assert first[0].stage is NarrativeStage.RUN_STARTED
    assert second[0].stage is NarrativeStage.RESCAN_STARTED
    assert second[0].triggered_by == "system_rescan:new_ocr_engine_promoted"

    combined = run(query.get_receipt_history("rc1"))
    assert len(combined) == 6


def test_state_as_of_reconstructs_a_past_row_from_the_append_only_trail(db):
    """The concrete payoff of append-only: a past state is answerable honestly.

    This is also what gives Reimport its three-way *base* without a second stored copy of
    the data that could drift from the real history.
    """
    repo = ReceiptRepository(db)
    query = HistorianQuery(db)

    _, first_event = run(repo.save(make_receipt(vendor_name="Vendor A"), actor="worker"))
    run(repo.apply_field_updates("rc1", {"vendor_name": "Vendor B"}, actor="human:u1"))

    at_export = run(query.state_as_of("receipts", "rc1", first_event.occurred_at))
    assert at_export["vendor_name"] == "Vendor A"

    current = run(repo.get("rc1"))
    assert current.vendor_name == "Vendor B"


def test_state_as_of_returns_none_for_a_row_with_no_history_that_old(db):
    from core.persistence.contracts import utcnow

    repo = ReceiptRepository(db)
    query = HistorianQuery(db)
    run(repo.save(make_receipt(), actor="worker"))
    long_ago = utcnow().replace(year=2000)
    assert run(query.state_as_of("receipts", "rc1", long_ago)) is None


def test_latest_event_id_is_what_an_export_stamps(db):
    repo = ReceiptRepository(db)
    query = HistorianQuery(db)
    assert run(query.latest_event_id()) == ""
    _, event = run(repo.save(make_receipt(), actor="worker"))
    assert run(query.latest_event_id()) == event.event_id
