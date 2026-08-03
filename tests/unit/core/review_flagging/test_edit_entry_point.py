"""`build_edit_link` — the deep-link decision for the system's general in-browser edit
entry point (§3, §4). Pure, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone

from core.review_flagging.contracts import Flag, FlagStatus
from core.review_flagging.edit_entry_point import build_edit_link


def _flag(flag_type: str) -> Flag:
    return Flag(
        flag_id="flg_1", flag_type=flag_type, user_id="user-1", receipt_id="receipt-1",
        status=FlagStatus.OPEN, created_by="reconciliation", created_at=datetime.now(timezone.utc),
    )


def test_known_flag_type_deep_links_to_its_conventional_field():
    link = build_edit_link(_flag("vat_math_mismatch"))

    assert link.field == "vat_amount"
    assert link.receipt_id == "receipt-1"
    assert link.flag_id == "flg_1"
    assert "vat amount" in link.label.lower()


def test_unknown_flag_type_falls_back_to_opening_the_receipt_generally():
    link = build_edit_link(_flag("some_new_flag_type_nobody_registered_yet"))

    assert link.field is None
    assert link.label == "Open receipt"
