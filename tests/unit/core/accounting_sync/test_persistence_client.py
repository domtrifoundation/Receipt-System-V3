"""`PersistenceClient` — real gRPC-unreachable behavior (no Persistence service is
running in this test environment, so this exercises the genuine failure path, not a
mocked one)."""

from __future__ import annotations

import asyncio

import pytest

from core.accounting_sync.persistence_client import PersistenceClient, ReceiptNotFound


def run(coro):
    return asyncio.run(coro)


def test_get_receipt_raises_receipt_not_found_when_service_is_unreachable():
    client = PersistenceClient(address="127.0.0.1:1", timeout_seconds=0.5)

    with pytest.raises(ReceiptNotFound):
        run(client.get_receipt("user-1", "receipt-1"))
