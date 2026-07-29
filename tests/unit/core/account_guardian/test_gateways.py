"""External-service adapters (`gateways.py`) — the honest-defaults and failure-mapping this
package's whole security posture leans on.

These are the "fail closed, not silently permitted" tests the task calls for at the adapter
boundary itself, distinct from the higher-level module tests that exercise the same
guarantee through `devices.py`/`privacy/*.py`.
"""

from __future__ import annotations

import pytest

from core.account_guardian.contracts import ExportOutcome
from core.account_guardian.errors import CapabilityMissing
from core.account_guardian.gateways import (
    BillingClearance,
    NoBillingConfiguredGateway,
    UnavailablePersistenceGateway,
    _map_validate_failure,
)
from core.auth.errors import SessionExpired, SessionInvalid

from .conftest import run


def test_validate_failure_mapping_recognises_session_expired_by_its_documented_prefix():
    """Auth's own `service.py._abort` formats every failure as `f"{exc.error.value}: ..."`
    (`core/auth/service.py`) — this is the one piece of structure `GrpcSessionGateway` can
    reliably parse back out of a wire failure."""
    mapped = _map_validate_failure("session_expired: session s_1… expired at ...")
    assert isinstance(mapped, SessionExpired)


def test_validate_failure_mapping_defaults_to_the_more_restrictive_session_invalid():
    """Anything that does not match the expected prefix denies rather than assumes the
    milder case (`docs/PRINCIPLES.md` §4.2) — an ambiguous auth failure must never be read
    as "probably just expired, so maybe still sort of valid"."""
    mapped = _map_validate_failure("something unexpected and unparseable")
    assert isinstance(mapped, SessionInvalid)
    assert not isinstance(mapped, SessionExpired)


def test_grpc_session_gateway_list_sessions_raises_the_documented_capability_gap():
    """Real, current gap: `auth.proto` has no session-listing RPC at all
    (`core/auth/auth.proto`) — every implementation in this file raises `CapabilityMissing`
    rather than returning a fabricated empty list that would look like "this user has no
    devices" instead of "this cannot be answered yet"."""
    from core.account_guardian.gateways import GrpcSessionGateway

    gateway = GrpcSessionGateway()

    with pytest.raises(CapabilityMissing):
        run(gateway.list_sessions("user_a"))


def test_unavailable_persistence_gateway_degrades_both_calls_never_raises():
    """The honest default while Persistence has no generated gRPC servicer at all
    (`core/persistence/` has no `generated/` package) — every call returns a clearly-labeled
    unavailable result rather than attempting a connection that cannot succeed."""
    gateway = UnavailablePersistenceGateway()

    export_outcome = run(gateway.generate_export("user_a", "data_portability"))
    erase_outcome = run(gateway.erase_account("user_a"))

    assert isinstance(export_outcome, ExportOutcome)
    assert not export_outcome.ok
    assert export_outcome.error == "CAPABILITY_MISSING"
    assert not erase_outcome.ok
    assert erase_outcome.error == "CAPABILITY_MISSING"


def test_no_billing_configured_gateway_clears_by_default_with_a_documented_reason():
    """Deliberately `clear=True`, not a fail-closed denial — billing clearance is a business
    process gate with no configured backend in this build, not a security check
    (`gateways.py`'s own extensive docstring on this exact distinction). The detail string
    must say so, so the choice is inspectable rather than a silent assumption."""
    gateway = NoBillingConfiguredGateway()

    clearance = run(gateway.resolve_deletion_clearance("user_a"))

    assert isinstance(clearance, BillingClearance)
    assert clearance.clear is True
    assert "no Billing API is wired" in clearance.detail
