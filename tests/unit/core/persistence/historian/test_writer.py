"""Historian's structural guarantees: append-only, and one transaction for both writes.

The append-only test is deliberately a *surface* test, not a behaviour test. §2.3 says the
guarantee has to be a structural property of the public surface — no mutation method exposed
anywhere — rather than a policy someone could bypass. Asserting "calling update raises" would
be testing a policy; asserting "no such method exists" is testing the structure.
"""

from __future__ import annotations

import sqlite3

import pytest

from common.frozen_dict import FrozenDict
from core.persistence.historian.contracts import DataChange, NarrativeStage
from core.persistence.historian.query import HistorianQuery
from core.persistence.historian.writer import HistorianWriter, dumps_payload

from ..conftest import run

_FORBIDDEN = (
    "update_event",
    "delete_event",
    "amend_event",
    "edit_event",
    "remove_event",
    "purge",
    "connection",
    "conn",
)


def test_writer_exposes_no_mutation_method(db):
    surface = {name for name in dir(HistorianWriter) if not name.startswith("__")}
    for forbidden in _FORBIDDEN:
        assert forbidden not in surface, (
            f"HistorianWriter.{forbidden} exists — append-only is a structural property of "
            "this surface, and adding a mutation method is the bug, not a missing feature"
        )


def test_query_exposes_no_mutation_method():
    surface = {name for name in dir(HistorianQuery) if not name.startswith("__")}
    assert not any(f in surface for f in _FORBIDDEN)


def test_write_with_history_commits_both_or_neither(db):
    writer = HistorianWriter(db)
    change = DataChange(
        table_name="receipts",
        row_id="rc1",
        before=None,
        after=FrozenDict({"vendor_name": "Vendor A"}),
        actor="worker",
    )

    def _apply(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('paired-write', 'landed')"
        )
        return "applied"

    applied, event = run(writer.write_with_history(change, _apply))
    assert applied == "applied"
    assert event.program_version, "the event records which build wrote it"

    count = db.run_sync(
        lambda c: c.execute("SELECT COUNT(*) AS n FROM historian_events").fetchone()["n"]
    )
    assert count == 1


def test_a_failing_data_write_leaves_no_event(db):
    writer = HistorianWriter(db)
    change = DataChange("receipts", "rc1", None, FrozenDict({"a": 1}), "worker")

    def _apply(conn):
        raise RuntimeError("the data write failed")

    with pytest.raises(RuntimeError):
        run(writer.write_with_history(change, _apply))

    count = db.run_sync(
        lambda c: c.execute("SELECT COUNT(*) AS n FROM historian_events").fetchone()["n"]
    )
    assert count == 0


def test_payload_serialization_requires_a_mapping_not_a_dict_subclass(db):
    """Checked as `Mapping`, so a `FrozenDict` passes on every interpreter."""
    assert dumps_payload(FrozenDict({"b": 2, "a": 1})) == '{"a": 1, "b": 2}'
    assert dumps_payload(None) is None
    with pytest.raises(TypeError):
        dumps_payload(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_narrative_batch_lands_together(db):
    from core.persistence.historian.narrative.summarizers import summarize

    writer = HistorianWriter(db)
    events = summarize(
        "ocr",
        "rc1",
        "run-1",
        {
            "readings": ({"engine": "tesseract", "mean_confidence": 0.87},
                         {"engine": "rapidocr", "mean_confidence": 0.91}),
            "agreement": "unanimous",
            "confidence": 0.91,
        },
    )
    run(writer.append_narrative_batch(events))
    stages = db.run_sync(
        lambda c: [r["stage"] for r in c.execute(
            "SELECT stage FROM narrative_events ORDER BY rowid"
        ).fetchall()]
    )
    assert stages == [
        NarrativeStage.OCR_ENGINE_RESULT.value,
        NarrativeStage.OCR_ENGINE_RESULT.value,
        NarrativeStage.OCR_CORROBORATED.value,
    ]
