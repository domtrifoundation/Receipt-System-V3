"""Regression: the real export → reimport round trip, in the export's own representation.

Every pre-existing reimport test used `vendor_name`, a plain string that happens to look
identical on both sides of the round trip. That is exactly why the defect these tests cover
survived: `exports/providers/common.receipt_row` writes `transaction_date` as a *date-only*
string and renders `None` as `""`, while the canonical row image Historian records keeps a
full timezone-aware ISO datetime and a real `None`. Diffed directly, those never compare
equal, so a pure round trip with no user edit at all reported every dated receipt as
user-changed — and then assigned the date-only *string* into `Receipt.transaction_date`,
which made the very next `receipt_to_row` raise `AttributeError: 'str' object has no
attribute 'isoformat'` out through `submit()`, across what will be a gRPC boundary.

These tests build the reimported row from `exports/providers/common` itself rather than from
a hand-written literal, so the two halves of the round trip cannot drift apart again without
failing here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from common.frozen_dict import FrozenDict
from core.persistence.db.receipts import ReceiptRepository
from core.persistence.exports.providers.common import EXPORT_COLUMNS, receipt_row
from core.persistence.historian.query import HistorianQuery
from core.persistence.reimport.conflict_resolution import ReimportService
from core.persistence.reimport.contracts import (
    ParsedRow,
    ParsedWorkbook,
    ReimportRequest,
)

from ..conftest import make_receipt, run

DATED = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)


def _register_snapshot(db, when, export_id="exp-1"):
    run(
        db.transaction(
            lambda c: c.execute(
                "INSERT INTO export_snapshots (export_id, user_id, historian_event_id,"
                " generated_at) VALUES (?,?,?,?)",
                (export_id, "user-1", "ev-1", when.isoformat()),
            )
        )
    )


def _patch_parser(monkeypatch, workbook: ParsedWorkbook):
    monkeypatch.setattr(
        "core.persistence.reimport.conflict_resolution.parse_workbook",
        lambda path: workbook,
    )


def _exported_values(receipt, **edits):
    """The row the export provider actually writes, optionally with the user's own edits."""
    values = {
        column: value
        for column, value in zip(EXPORT_COLUMNS, receipt_row(receipt))
        if column != "receipt_id"
    }
    values.update(edits)
    return FrozenDict(values)


def _submit(db, monkeypatch, values, receipt_id="rc1"):
    _patch_parser(
        monkeypatch,
        ParsedWorkbook(
            ok=True,
            snapshot_export_id="exp-1",
            rows=(ParsedRow(receipt_id, values),),
        ),
    )
    return run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )


def test_an_unedited_round_trip_changes_nothing_and_does_not_raise(db, monkeypatch):
    """The whole file came back untouched. Nothing may be written, and nothing may raise."""
    repo = ReceiptRepository(db)
    saved, event = run(
        repo.save(
            make_receipt(transaction_date=DATED, group_id=None), actor="worker"
        )
    )
    _register_snapshot(db, event.occurred_at)

    result = _submit(db, monkeypatch, _exported_values(saved))

    assert result.ok
    assert result.fields_applied == 0, "a pure round trip wrote fields nobody edited"
    assert result.receipts_touched == ()
    assert result.conflicts == ()
    assert result.rejected_fields == ()

    after = run(repo.get("rc1"))
    assert after.transaction_date == DATED, "the timestamp was truncated by a phantom edit"
    assert after.group_id is None, "an empty cell was written back as a real value"

    # And the phantom write left no phantom audit trail either.
    changes = run(HistorianQuery(db).get_row_changes("receipts", "rc1"))
    assert len(changes) == 1, "a no-op reimport appended a Historian event"


def test_a_real_date_edit_is_written_as_a_datetime_not_a_string(db, monkeypatch):
    repo = ReceiptRepository(db)
    saved, event = run(repo.save(make_receipt(transaction_date=DATED), actor="worker"))
    _register_snapshot(db, event.occurred_at)

    result = _submit(
        db, monkeypatch, _exported_values(saved, transaction_date="2026-08-01")
    )

    assert result.ok
    assert result.fields_applied == 1
    after = run(repo.get("rc1"))
    assert isinstance(after.transaction_date, datetime), (
        "a workbook string reached a datetime column — the next receipt_to_row would raise"
    )
    assert after.transaction_date.date().isoformat() == "2026-08-01"

    # And the row is still readable/writable afterwards, which is the actual crash.
    run(repo.save(after, actor="worker"))


def test_an_amount_edit_is_written_as_a_decimal(db, monkeypatch):
    repo = ReceiptRepository(db)
    saved, event = run(
        repo.save(make_receipt(total_amount=Decimal("100.00")), actor="worker")
    )
    _register_snapshot(db, event.occurred_at)

    result = _submit(db, monkeypatch, _exported_values(saved, total_amount="250.75"))

    assert result.fields_applied == 1
    after = run(repo.get("rc1"))
    assert after.total_amount == Decimal("250.75")


def test_an_uncoercible_edit_is_reported_and_never_written(db, monkeypatch):
    """Never silently overridden, never silently dropped (`docs/PRINCIPLES.md` §4.3)."""
    repo = ReceiptRepository(db)
    saved, event = run(repo.save(make_receipt(transaction_date=DATED), actor="worker"))
    _register_snapshot(db, event.occurred_at)

    result = _submit(
        db, monkeypatch, _exported_values(saved, transaction_date="last tuesday")
    )

    assert result.ok, "one bad cell must not reject the whole file"
    assert result.fields_applied == 0
    assert result.rejected_fields == ("rc1.transaction_date",)
    assert "could not be read" in result.error_detail
    assert run(repo.get("rc1")).transaction_date == DATED


def test_a_conflict_still_surfaces_in_the_projected_representation(db, monkeypatch):
    """The projection must not accidentally make two genuinely different dates compare
    equal — the conflict rule has to keep working through it."""
    repo = ReceiptRepository(db)
    saved, event = run(repo.save(make_receipt(transaction_date=DATED), actor="worker"))
    _register_snapshot(db, event.occurred_at)
    run(
        repo.apply_field_updates(
            "rc1",
            {"transaction_date": datetime(2026, 9, 9, tzinfo=timezone.utc)},
            actor="worker",
        )
    )

    result = _submit(
        db, monkeypatch, _exported_values(saved, transaction_date="2026-08-01")
    )

    assert result.fields_applied == 0
    assert [c.field for c in result.conflicts] == ["transaction_date"]
    assert run(repo.get("rc1")).transaction_date.date().isoformat() == "2026-09-09"
