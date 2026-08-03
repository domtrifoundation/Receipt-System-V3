"""Shared fixtures for Accounting Sync's unit tests. No fake ever carries a real
OAuth-shaped secret — synthetic strings only, matching every other API's own conftest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.accounting_sync.contracts import AccountingProvider, SyncedRecord


class FakeProvider:
    """A real `AccountingSyncProvider` implementation (Protocol-satisfying, not a mock) —
    push always succeeds unless `fail_with` is set."""

    def __init__(self, provider: AccountingProvider = AccountingProvider.QUICKBOOKS, fail_with: Exception | None = None) -> None:
        self._provider = provider
        self._fail_with = fail_with
        self._connected: set[str] = set()
        self.push_calls: list = []

    @property
    def provider(self) -> AccountingProvider:
        return self._provider

    async def is_available(self) -> bool:
        return True

    async def authenticate(self, user_id: str):
        from core.accounting_sync.contracts import AuthUrl

        return AuthUrl(url=f"https://example.test/auth/{user_id}", state="fake-state")

    async def complete_auth(self, user_id: str, callback_params: dict):
        from core.accounting_sync.contracts import SyncConnection

        self._connected.add(user_id)
        return SyncConnection(user_id=user_id, provider=self._provider, external_account_id="ext-1")

    async def push_record(self, connection, record):
        self.push_calls.append((connection, record))
        if self._fail_with is not None:
            raise self._fail_with
        return SyncedRecord(receipt_id=record.receipt_id, provider=self._provider, external_record_id="ext-record-1")

    async def is_connected(self, user_id: str) -> bool:
        return user_id in self._connected

    async def disconnect(self, user_id: str) -> None:
        self._connected.discard(user_id)


class FakeFlagChecker:
    def __init__(self, flagged_receipt_ids: frozenset[str] = frozenset()) -> None:
        self._flagged = flagged_receipt_ids

    async def has_open_flag(self, receipt_id: str) -> bool:
        return receipt_id in self._flagged


@dataclass
class FakeReceipt:
    receipt_id: str = "receipt-1"
    vendor_name: str = "Acme Corp"
    total_amount: Decimal | None = Decimal("12.50")
    transaction_date: datetime | None = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    currency: str = "PHP"
    fields: dict = field(default_factory=dict)


@pytest.fixture
def fake_receipt() -> FakeReceipt:
    return FakeReceipt()
