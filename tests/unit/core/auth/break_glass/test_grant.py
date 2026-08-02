"""Break-glass: required reasons, bounded durations, and expiry that never waits for a sweep.

The expiry test is §11's own break-glass case, stated there as "a grant created with a short
duration, confirming `check_access()` correctly returns `False` the instant it expires,
without depending on a background sweep having run".
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.auth.break_glass.grant import BreakGlassLedger
from core.auth.contracts import utcnow
from core.auth.errors import BreakGlassExpired

from ..conftest import run


@pytest.fixture
def ledger(db):
    return BreakGlassLedger(db, default_duration_minutes=60, max_duration_minutes=480)


@pytest.fixture
def audited(db):
    recorded: list[tuple[str, dict]] = []
    return BreakGlassLedger(db, audit_sink=lambda e, p: recorded.append((e, p))), recorded


def test_a_reason_is_required(ledger):
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="reason"):
            run(ledger.request_grant("staff", "client", bad))


def test_duration_is_bounded_by_config(ledger):
    with pytest.raises(ValueError):
        run(ledger.request_grant("staff", "client", "ticket-9", 481))
    with pytest.raises(ValueError):
        run(ledger.request_grant("staff", "client", "ticket-9", 0))
    grant = run(ledger.request_grant("staff", "client", "ticket-9"))
    assert grant.expires_at - grant.granted_at == timedelta(minutes=60)


def test_access_is_scoped_to_exactly_one_staff_client_pair(ledger):
    run(ledger.request_grant("staff_a", "client_1", "ticket-1"))
    assert run(ledger.check_access("staff_a", "client_1"))
    assert not run(ledger.check_access("staff_a", "client_2"))
    assert not run(ledger.check_access("staff_b", "client_1"))


def test_staff_have_no_standing_access_without_a_grant(ledger):
    """Break-glass is not a permission bit on the staff role — absent a grant there is
    nothing to fall back on."""
    assert not run(ledger.check_access("staff_a", "client_1"))


def test_expiry_needs_no_sweep(ledger):
    grant = ledger.request_grant_sync("staff_a", "client_1", "ticket-1", duration_minutes=1)
    just_before = grant.expires_at - timedelta(seconds=1)
    just_after = grant.expires_at + timedelta(seconds=1)
    assert ledger.check_access_sync("staff_a", "client_1", now=just_before)
    assert not ledger.check_access_sync("staff_a", "client_1", now=just_after)
    # The sweep is cleanliness. It runs afterwards and changes no access decision.
    assert ledger.sweep_expired_sync(now=just_after) == 1
    assert not ledger.check_access_sync("staff_a", "client_1", now=just_after)


def test_assert_access_is_the_raising_form(ledger):
    with pytest.raises(BreakGlassExpired):
        ledger.assert_access_sync("staff_a", "client_1")
    run(ledger.request_grant("staff_a", "client_1", "ticket-1"))
    ledger.assert_access_sync("staff_a", "client_1")


def test_revocation_is_immediate(ledger):
    grant = run(ledger.request_grant("staff_a", "client_1", "ticket-1"))
    assert run(ledger.revoke(grant.grant_id))
    assert not run(ledger.check_access("staff_a", "client_1"))
    assert not run(ledger.revoke(grant.grant_id))


def test_client_can_see_every_grant_ever_made_over_their_data(ledger):
    active = run(ledger.request_grant("staff_a", "client_1", "ticket-1"))
    revoked = run(ledger.request_grant("staff_b", "client_1", "ticket-2"))
    run(ledger.revoke(revoked.grant_id))
    history = ledger.list_for_client_sync("client_1")
    assert {g.grant_id for g in history} == {active.grant_id, revoked.grant_id}


def test_grants_are_reported_to_the_audit_sink(audited):
    ledger, recorded = audited
    grant = run(ledger.request_grant("staff_a", "client_1", "ticket-7"))
    run(ledger.revoke(grant.grant_id))
    events = [name for name, _ in recorded]
    assert events == ["break_glass_granted", "break_glass_revoked"]
    assert recorded[0][1]["reason"] == "ticket-7"


def test_a_missing_audit_sink_does_not_block_a_grant(ledger):
    """Auth must not depend on Audit being up to record its own ledger — the grant row is
    itself durable evidence."""
    grant = run(ledger.request_grant("staff_a", "client_1", "ticket-1"))
    assert ledger.get_sync(grant.grant_id) is not None


def test_active_listing_excludes_expired(ledger):
    ledger.request_grant_sync("staff_a", "client_1", "ticket-1", duration_minutes=1)
    assert len(ledger.list_active_sync()) == 1
    assert ledger.list_active_sync(now=utcnow() + timedelta(minutes=2)) == []
