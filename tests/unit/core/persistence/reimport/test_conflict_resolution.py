"""Reimport orchestration: the fail-closed scan gate, the stale-snapshot rejection, and the
actor tag that keeps a round-tripped edit distinguishable from a live one."""

from __future__ import annotations

from core.persistence.contracts import utcnow
from core.persistence.db.receipts import ReceiptRepository
from core.persistence.historian.query import HistorianQuery
from core.persistence.reimport import errors
from core.persistence.reimport.conflict_resolution import ReimportService
from core.persistence.reimport.contracts import (
    ParsedRow,
    ParsedWorkbook,
    ReimportRequest,
)

from common.frozen_dict import FrozenDict

from ..conftest import make_receipt, run


class _RecordingFlagSink:
    def __init__(self):
        self.raised = []

    async def raise_flag(self, flag_type, user_id, payload):
        self.raised.append((flag_type, user_id, dict(payload)))
        return "flag-1"


def _register_snapshot(db, export_id="exp-1", when=None):
    generated_at = when or utcnow()
    run(
        db.transaction(
            lambda c: c.execute(
                "INSERT INTO export_snapshots (export_id, user_id, historian_event_id,"
                " generated_at) VALUES (?,?,?,?)",
                (export_id, "user-1", "ev-1", generated_at.isoformat()),
            )
        )
    )
    return generated_at


def _patch_parser(monkeypatch, workbook: ParsedWorkbook):
    monkeypatch.setattr(
        "core.persistence.reimport.conflict_resolution.parse_workbook",
        lambda path: workbook,
    )


def test_an_unscanned_file_is_rejected_before_anything_is_read(db, monkeypatch):
    """Fail closed. A scan that failed, timed out, or never ran all mean 'unsafe' here."""

    def _should_not_be_called(path):
        raise AssertionError("the file was parsed before the scan gate")

    _patch_parser(monkeypatch, ParsedWorkbook(ok=True))
    monkeypatch.setattr(
        "core.persistence.reimport.conflict_resolution.parse_workbook",
        _should_not_be_called,
    )

    result = run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=False)
        )
    )
    assert not result.ok
    assert result.error_code == errors.UNSCANNED_FILE


def test_a_missing_snapshot_reference_fails_cleanly(db, monkeypatch):
    _patch_parser(
        monkeypatch,
        ParsedWorkbook(
            ok=False,
            error_code=errors.MISSING_SNAPSHOT_REFERENCE,
            error_detail="reference cell stripped",
        ),
    )
    result = run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )
    assert not result.ok
    assert result.error_code == errors.MISSING_SNAPSHOT_REFERENCE
    assert result.fields_applied == 0, "no silent full-canonical overwrite"


def test_a_stale_snapshot_reference_asks_for_a_fresh_export(db, monkeypatch):
    _patch_parser(
        monkeypatch, ParsedWorkbook(ok=True, snapshot_export_id="exp-that-was-purged")
    )
    result = run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )
    assert not result.ok
    assert result.error_code == errors.STALE_SNAPSHOT_REFERENCE
    assert "fresh export" in result.error_detail


def test_a_clean_edit_applies_and_is_tagged_as_coming_via_reimport(db, monkeypatch):
    repo = ReceiptRepository(db)
    _, event = run(repo.save(make_receipt(vendor_name="Vendor A"), actor="worker"))
    _register_snapshot(db, when=event.occurred_at)

    _patch_parser(
        monkeypatch,
        ParsedWorkbook(
            ok=True,
            snapshot_export_id="exp-1",
            rows=(ParsedRow("rc1", FrozenDict({"vendor_name": "Vendor A Corrected"})),),
        ),
    )

    result = run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )
    assert result.ok
    assert result.fields_applied == 1
    assert result.conflicts == ()
    assert run(repo.get("rc1")).vendor_name == "Vendor A Corrected"

    history = run(HistorianQuery(db).get_row_changes("receipts", "rc1"))
    assert history[-1].actor == "human:user-1-via-reimport"


def test_a_genuine_conflict_raises_a_flag_and_keeps_canonical(db, monkeypatch):
    repo = ReceiptRepository(db)
    _, first = run(repo.save(make_receipt(vendor_name="base"), actor="worker"))
    _register_snapshot(db, when=first.occurred_at)
    # Canonical moved on after the export was generated.
    run(repo.apply_field_updates("rc1", {"vendor_name": "canonical-edit"}, actor="worker"))

    _patch_parser(
        monkeypatch,
        ParsedWorkbook(
            ok=True,
            snapshot_export_id="exp-1",
            rows=(ParsedRow("rc1", FrozenDict({"vendor_name": "user-edit"})),),
        ),
    )
    sink = _RecordingFlagSink()

    result = run(
        ReimportService(db, flags=sink).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )
    assert result.ok
    assert result.fields_applied == 0
    assert len(result.conflicts) == 1
    assert result.flag_id == "flag-1"
    assert sink.raised[0][0] == errors.CONFLICT_FLAG_TYPE
    assert run(repo.get("rc1")).vendor_name == "canonical-edit"


def test_conflicts_with_no_flag_sink_are_reported_not_swallowed(db, monkeypatch):
    """A conflict a human never hears about is exactly the failure §4.3 exists to prevent,
    so an unconfigured sink must be loud in the result rather than silently dropped."""
    repo = ReceiptRepository(db)
    _, first = run(repo.save(make_receipt(vendor_name="base"), actor="worker"))
    _register_snapshot(db, when=first.occurred_at)
    run(repo.apply_field_updates("rc1", {"vendor_name": "canonical-edit"}, actor="worker"))

    _patch_parser(
        monkeypatch,
        ParsedWorkbook(
            ok=True,
            snapshot_export_id="exp-1",
            rows=(ParsedRow("rc1", FrozenDict({"vendor_name": "user-edit"})),),
        ),
    )
    result = run(
        ReimportService(db).submit(
            ReimportRequest("user-1", "x.xlsx", "user-1", content_scan_passed=True)
        )
    )
    assert result.conflicts
    assert result.flag_id == ""
    assert "NOT been surfaced" in result.error_detail
