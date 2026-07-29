"""`metrics.py` — the counters, and the frozen snapshot handed out of them."""

from __future__ import annotations

import dataclasses

import pytest

from core.account_guardian.contracts import AccountGuardianMetrics
from core.account_guardian.metrics import COUNTER_NAMES, AccountGuardianMetricsCollector


def test_counter_names_are_derived_from_the_contract_not_hand_maintained():
    """Adding a counter means adding a field to `AccountGuardianMetrics` and nothing else —
    if these two ever drift, this test is what would catch it."""
    contract_fields = {f.name for f in dataclasses.fields(AccountGuardianMetrics)}
    assert set(COUNTER_NAMES) == contract_fields


def test_increment_and_snapshot_are_independent():
    collector = AccountGuardianMetricsCollector()
    collector.increment("devices_revoked")
    collector.increment("devices_revoked")

    snapshot = collector.snapshot()

    assert snapshot.devices_revoked == 2
    assert isinstance(snapshot, AccountGuardianMetrics)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.devices_revoked = 99  # type: ignore[misc]


def test_an_unknown_counter_name_is_ignored_not_raised():
    """Instrumentation must never be able to fail the privileged action it is counting."""
    collector = AccountGuardianMetricsCollector()
    collector.increment("not_a_real_counter")  # must not raise
    assert collector.snapshot().devices_revoked == 0


def test_reset_zeroes_every_counter():
    collector = AccountGuardianMetricsCollector()
    collector.increment("export_requests", 5)
    collector.reset()
    assert collector.snapshot().export_requests == 0
