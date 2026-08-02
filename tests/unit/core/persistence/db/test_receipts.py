"""The dual-write atomicity test — deep-dive §11's first named testing hook.

This is the concrete validation of §5's entire "same transaction boundary" claim, which is
also the whole reason Historian is a sub-package of Persistence rather than a peer API. If
these tests pass while the guarantee is broken, they are not testing the right thing.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.persistence.db.receipts import ReceiptRepository
from core.persistence.errors import ReceiptNotFound

from ..conftest import make_receipt, run


def _counts(db):
    def _read(conn: sqlite3.Connection):
        return (
            conn.execute("SELECT COUNT(*) AS n FROM receipts").fetchone()["n"],
            conn.execute("SELECT COUNT(*) AS n FROM historian_events").fetchone()["n"],
        )

    return db.run_sync(_read)


def test_data_write_and_history_event_both_land(db):
    repo = ReceiptRepository(db)
    saved, event = run(repo.save(make_receipt(), actor="worker"))
    assert saved.receipt_id == "rc1"
    assert event.event_id
    assert _counts(db) == (1, 1)


def test_mid_transaction_failure_lands_neither(db, monkeypatch):
    """Simulated failure between the data write and the event insertion.

    The row must not survive on its own. A canonical write landing without its audit record
    is precisely what the one-transaction design exists to make impossible.
    """
    repo = ReceiptRepository(db)
    run(repo.save(make_receipt("rc1"), actor="worker"))
    before = _counts(db)

    def _boom(conn, change):
        raise sqlite3.OperationalError("simulated failure after the row was written")

    monkeypatch.setattr(repo._historian, "append_data_change_sync", _boom)

    with pytest.raises(sqlite3.OperationalError):
        run(repo.save(make_receipt("rc2"), actor="worker"))

    assert _counts(db) == before, "the receipt row survived without its Historian event"
    assert run(repo.get("rc2")) is None


def test_before_image_is_recorded_on_update(db):
    repo = ReceiptRepository(db)
    run(repo.save(make_receipt(vendor_name="Vendor A"), actor="worker"))
    _, event = run(
        repo.apply_field_updates("rc1", {"vendor_name": "Vendor B"}, actor="human:u1")
    )
    assert event.before is not None
    assert event.before["vendor_name"] == "Vendor A"
    assert event.after["vendor_name"] == "Vendor B"
    assert event.actor == "human:u1"


def test_insert_records_no_before_image(db):
    repo = ReceiptRepository(db)
    _, event = run(repo.save(make_receipt(), actor="worker"))
    assert event.before is None
    assert event.after is not None


def test_apply_field_updates_on_unknown_receipt_raises_internally(db):
    """Internal exception, not a boundary error — `service.py` is what converts it."""
    repo = ReceiptRepository(db)
    with pytest.raises(ReceiptNotFound):
        run(repo.apply_field_updates("nope", {"vendor_name": "X"}, actor="worker"))


def test_unknown_fields_land_in_the_typed_fields_map(db):
    repo = ReceiptRepository(db)
    run(repo.save(make_receipt(), actor="worker"))
    saved, _ = run(
        repo.apply_field_updates("rc1", {"or_number": "12345"}, actor="worker")
    )
    assert saved.fields["or_number"] == "12345"


def test_list_for_user_is_cursor_shaped(db):
    repo = ReceiptRepository(db)
    for i in range(3):
        run(repo.save(make_receipt(f"rc{i}"), actor="worker"))
    page = run(repo.list_for_user("user-1", after_receipt_id="rc0", limit=10))
    assert [r.receipt_id for r in page] == ["rc1", "rc2"]
