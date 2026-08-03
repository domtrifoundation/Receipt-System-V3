"""`build_audit_view` — the per-receipt audit screen (§3), a workflow layer over Logs,
never a second store."""

from __future__ import annotations

from datetime import datetime, timezone

from core.review_flagging.audit_screen import build_audit_view
from core.review_flagging.contracts import AuditTraceEntry, CreateFlagRequest

from .conftest import run


class FakeTraceSource:
    def __init__(self, entries: tuple[AuditTraceEntry, ...] = (), available: bool = True) -> None:
        self._entries = entries
        self._available = available

    async def fetch(self, receipt_id: str) -> tuple[AuditTraceEntry, ...]:
        return self._entries

    async def is_available(self) -> bool:
        return self._available


def test_audit_view_includes_every_flag_raised_for_the_receipt(store):
    run(store.create_flag(CreateFlagRequest(
        flag_type="vat_math_mismatch", user_id="user-1", receipt_id="receipt-1", created_by="reconciliation",
    )))
    run(store.create_flag(CreateFlagRequest(
        flag_type="tin_format_malformed", user_id="user-1", receipt_id="receipt-1", created_by="content_security",
    )))
    run(store.create_flag(CreateFlagRequest(
        flag_type="implausible_date", user_id="user-1", receipt_id="receipt-2", created_by="reconciliation",
    )))

    view = run(build_audit_view("receipt-1", store, trace_source=FakeTraceSource()))

    assert len(view.flags) == 2
    assert {f.flag_type for f in view.flags} == {"vat_math_mismatch", "tin_format_malformed"}


def test_audit_view_reports_trace_available_true_for_a_real_reachable_source(store):
    entries = (AuditTraceEntry(timestamp=datetime.now(timezone.utc), service="ocr", level="info", message="scanned"),)

    view = run(build_audit_view("receipt-1", store, trace_source=FakeTraceSource(entries=entries)))

    assert view.trace_available is True
    assert view.trace == entries


def test_audit_view_reports_trace_available_false_when_the_source_is_unreachable(store):
    view = run(build_audit_view("receipt-1", store, trace_source=FakeTraceSource(available=False)))

    assert view.trace_available is False
    assert view.ok  # the flags half of the view is still a real, valid answer (§4.4)


def test_audit_view_on_a_never_flagged_receipt_is_empty_but_not_an_error():
    view = run(build_audit_view("nothing-here", _bare_store(), trace_source=FakeTraceSource()))

    assert view.ok
    assert view.flags == ()


def _bare_store():
    from core.review_flagging.lifecycle import FlagStore

    return FlagStore(":memory:")
