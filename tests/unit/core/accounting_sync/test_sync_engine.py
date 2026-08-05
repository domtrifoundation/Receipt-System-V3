"""`SyncEngine` — the real assembly wiring providers, `FlagChecker`, and metrics
together (deep-dive §6). Includes the three tests deep-dive §9 names explicitly:
the one-way boundary test, the flagged-receipt exclusion test, and the
credential-isolation test.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from core.accounting_sync.contracts import AccountingProvider, SyncConnection, SyncErrorCode
from core.accounting_sync.errors import PushFailed, SyncRateLimited
from core.accounting_sync.providers.base import AccountingSyncProvider
from core.accounting_sync.sync_engine import SyncEngine

from .conftest import FakeFlagChecker, FakeProvider


def run(coro):
    return asyncio.run(coro)


# --- deep-dive §9: "one-way boundary test" -----------------------------------------------

def test_provider_protocol_exposes_no_pull_or_read_back_method():
    """One-way push only (deep-dive §4) — `AccountingSyncProvider` must never grow a
    method that reads a record back from the provider; this test fails the moment one is
    added, forcing that decision to be deliberate, not an accidental scope-creep."""
    method_names = {name for name, _ in inspect.getmembers(AccountingSyncProvider, predicate=inspect.isfunction)}
    forbidden_terms = ("pull", "fetch", "list", "read", "import", "sync_from")
    leaked = {name for name in method_names if any(term in name.lower() for term in forbidden_terms)}
    assert leaked == set()


def test_push_record_never_calls_anything_but_the_provider_push_method(fake_receipt):
    from core.accounting_sync.mapping import map_receipt_to_record

    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    record = map_receipt_to_record(fake_receipt)

    run(engine.push_record("user-1", AccountingProvider.QUICKBOOKS, record))

    assert len(provider.push_calls) == 1


# --- deep-dive §9: "flagged-receipt exclusion test" ---------------------------------------

def test_flagged_receipt_is_excluded_before_touching_the_provider(fake_receipt):
    provider = FakeProvider()
    engine = SyncEngine(
        {AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker(frozenset({fake_receipt.receipt_id})),
    )

    result = run(engine.push_receipt("user-1", AccountingProvider.QUICKBOOKS, fake_receipt))

    assert result.error is not None
    assert result.error.code == SyncErrorCode.RECEIPT_FLAGGED
    assert provider.push_calls == []


def test_unflagged_receipt_pushes_normally(fake_receipt):
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())

    result = run(engine.push_receipt("user-1", AccountingProvider.QUICKBOOKS, fake_receipt))

    assert result.error is None
    assert result.external_record_id == "ext-record-1"
    assert len(provider.push_calls) == 1


def test_flagged_push_increments_the_skipped_metric_not_the_failed_metric(fake_receipt):
    provider = FakeProvider()
    engine = SyncEngine(
        {AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker(frozenset({fake_receipt.receipt_id})),
    )

    run(engine.push_receipt("user-1", AccountingProvider.QUICKBOOKS, fake_receipt))

    snapshot = engine.metrics.snapshot()
    assert snapshot.pushes_skipped_flagged == 1
    assert snapshot.pushes_failed == 0


# --- deep-dive §9: "credential isolation test" --------------------------------------------

def test_sync_connection_carries_no_token_material(fake_receipt):
    """`SyncConnection` (`contracts.py`) has no field a token could ever land in — the
    guarantee is structural, not a runtime check; this test locks the field set down so
    a future field can't silently reintroduce one."""
    connection = SyncConnection(user_id="user-1", provider=AccountingProvider.QUICKBOOKS)
    field_names = {f for f in connection.__dataclass_fields__}
    suspicious = {name for name in field_names if any(term in name.lower() for term in ("token", "secret", "password", "credential"))}
    assert suspicious == set()


def test_complete_auth_result_never_contains_the_raw_tokens():
    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())

    connection = run(engine.complete_auth("user-1", AccountingProvider.QUICKBOOKS, {"code": "abc"}))

    assert not hasattr(connection, "access_token")
    assert not hasattr(connection, "refresh_token")


# --- provider-failure conversion (errors.py's own "converted to data here" contract) ------

def test_push_failed_is_converted_to_a_synced_record_error(fake_receipt):
    from core.accounting_sync.mapping import map_receipt_to_record

    provider = FakeProvider(fail_with=PushFailed("boom"))
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    record = map_receipt_to_record(fake_receipt)

    result = run(engine.push_record("user-1", AccountingProvider.QUICKBOOKS, record))

    assert result.error is not None
    assert result.error.code == SyncErrorCode.PUSH_FAILED
    assert engine.metrics.snapshot().pushes_failed == 1


def test_rate_limited_is_converted_and_counts_a_retry(fake_receipt):
    from core.accounting_sync.mapping import map_receipt_to_record

    provider = FakeProvider(fail_with=SyncRateLimited("429"))
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    record = map_receipt_to_record(fake_receipt)

    result = run(engine.push_record("user-1", AccountingProvider.QUICKBOOKS, record))

    assert result.error.code == SyncErrorCode.RATE_LIMITED
    snapshot = engine.metrics.snapshot()
    assert snapshot.retries_attempted == 1
    assert snapshot.pushes_failed == 1


def test_no_adapter_configured_for_provider_reports_not_connected(fake_receipt):
    engine = SyncEngine({}, FakeFlagChecker())

    result = run(engine.push_receipt("user-1", AccountingProvider.QUICKBOOKS, fake_receipt))

    assert result.error.code == SyncErrorCode.NOT_CONNECTED


def test_mapping_failed_receipt_reports_mapping_failed_error(fake_receipt):
    from dataclasses import replace

    provider = FakeProvider()
    engine = SyncEngine({AccountingProvider.QUICKBOOKS: provider}, FakeFlagChecker())
    broken_receipt = replace(fake_receipt, vendor_name="")

    result = run(engine.push_receipt("user-1", AccountingProvider.QUICKBOOKS, broken_receipt))

    assert result.error.code == SyncErrorCode.MAPPING_FAILED
    assert provider.push_calls == []
