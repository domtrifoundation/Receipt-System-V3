"""`AccountingSyncServicer` — the real assembly point (this session's own repeated
lesson: a module built and tested in isolation is still a gap until something in the
real service construction calls it)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# Neither the generated stubs (needs `google.protobuf`/`grpc`) nor `build_sync_engine`
# (needs `cryptography` for `TokenStore`) import cleanly on an interpreter missing those
# packages — same collection-time-skip pattern `core/auth`'s own `test_service.py` uses.
pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")
pytest.importorskip("cryptography", reason="cryptography is not installed here")

from core.accounting_sync.contracts import AccountingProvider  # noqa: E402
from core.accounting_sync.generated import accounting_sync_pb2 as pb  # noqa: E402
from core.accounting_sync.persistence_client import ReceiptNotFound, _ReceiptView  # noqa: E402
from core.accounting_sync.providers.quickbooks import QuickBooksConfig  # noqa: E402
from core.accounting_sync.service import (  # noqa: E402
    AccountingSyncConfig,
    AccountingSyncServicer,
    NoOpFlagChecker,
    build_sync_engine,
)
from core.accounting_sync.sync_engine import SyncEngine  # noqa: E402

from .conftest import FakeFlagChecker, FakeProvider  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakePersistence:
    def __init__(self, receipt: _ReceiptView | None = None, missing: bool = False) -> None:
        self._receipt = receipt
        self._missing = missing

    async def get_receipt(self, user_id: str, receipt_id: str) -> _ReceiptView:
        if self._missing:
            raise ReceiptNotFound("no such receipt")
        return self._receipt or _ReceiptView(
            receipt_id=receipt_id, vendor_name="Acme Corp", total_amount=Decimal("12.50"),
            transaction_date=datetime.now(timezone.utc), currency="PHP", fields={},
        )


def test_build_sync_engine_registers_both_providers():
    """Real assembly: `build_sync_engine` must actually construct and register both
    QuickBooks and Xero — the exact "declared but never constructed" gap this session
    found repeatedly (Ingestion's `GoogleDriveSource`, Preprocessing's metrics collector)."""
    engine = build_sync_engine(AccountingSyncConfig())

    assert AccountingProvider.QUICKBOOKS in engine._providers
    assert AccountingProvider.XERO in engine._providers


def test_no_op_flag_checker_never_excludes_anything():
    """Documents the real, current limitation honestly: Review/Flagging has no gRPC
    surface yet, so the default checker cannot actually enforce deep-dive §6's rule.
    This test exists so the day a real `FlagChecker` gets wired in, someone has to
    deliberately change this behavior, not silently inherit it."""
    checker = NoOpFlagChecker()

    assert run(checker.has_open_flag("anything")) is False


def test_initiate_auth_rpc_reports_a_real_error_for_unconfigured_quickbooks():
    config = AccountingSyncConfig(quickbooks=QuickBooksConfig())
    servicer = AccountingSyncServicer(config)

    response = run(servicer.InitiateAuth(pb.InitiateAuthRequest(user_id="user-1", provider="quickbooks")))

    assert response.error_code == "auth_failed"
    assert response.url == ""


def test_push_receipt_rpc_pushes_through_to_the_real_engine():
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    servicer = AccountingSyncServicer(engine=engine, persistence_client=FakePersistence())

    response = run(servicer.PushReceipt(
        pb.PushReceiptRequest(user_id="user-1", provider="quickbooks", receipt_id="receipt-1"),
    ))

    assert response.error_code == ""
    assert response.external_record_id == "ext-record-1"
    assert len(provider.push_calls) == 1


def test_push_receipt_rpc_excludes_a_flagged_receipt_before_any_provider_call():
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker(frozenset({"receipt-1"})))
    servicer = AccountingSyncServicer(engine=engine, persistence_client=FakePersistence())

    response = run(servicer.PushReceipt(
        pb.PushReceiptRequest(user_id="user-1", provider="quickbooks", receipt_id="receipt-1"),
    ))

    assert response.error_code == "receipt_flagged"
    assert provider.push_calls == []


def test_push_receipt_rpc_reports_not_connected_when_persistence_has_no_such_receipt():
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    servicer = AccountingSyncServicer(engine=engine, persistence_client=FakePersistence(missing=True))

    response = run(servicer.PushReceipt(
        pb.PushReceiptRequest(user_id="user-1", provider="quickbooks", receipt_id="missing-1"),
    ))

    assert response.error_code == "not_connected"
    assert provider.push_calls == []


def test_get_sync_status_and_disconnect_rpcs_delegate_to_the_engine():
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    servicer = AccountingSyncServicer(engine=engine, persistence_client=FakePersistence())

    run(engine.complete_auth("user-1", AccountingProvider.QUICKBOOKS, {"code": "abc"}))
    status = run(servicer.GetSyncStatus(pb.SyncStatusRequest(user_id="user-1", provider="quickbooks")))
    assert status.connected is True

    run(servicer.Disconnect(pb.DisconnectRequest(user_id="user-1", provider="quickbooks")))
    status_after = run(servicer.GetSyncStatus(pb.SyncStatusRequest(user_id="user-1", provider="quickbooks")))
    assert status_after.connected is False
