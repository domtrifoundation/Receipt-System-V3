"""SSO provider change intake (`sso_linking.py`).

`sso_linking.py` is explicitly the request-intake half of a "future" feature (deep-dive §2)
— these tests hold it to what it actually claims: provider validation against a real
registry (never a hardcoded string comparison), a step-up gate that fails closed, ownership
on cancellation, and an honest `PENDING_AUTH_MUTATION` stage rather than a false
`COMPLETED`.
"""

from __future__ import annotations

from core.account_guardian import sso_linking
from core.account_guardian.contracts import SsoLinkStage
from core.account_guardian.errors import E_INVALID_REQUEST, E_NOT_FOUND, E_OWNERSHIP_DENIED, E_UNSUPPORTED_PROVIDER

from .conftest import run


def test_unknown_provider_is_refused(db, audit_gateway):
    result = run(sso_linking.request_link(db, audit_gateway, "user_a", "not-a-real-idp", step_up_confirmed=True))

    assert result.error == E_UNSUPPORTED_PROVIDER
    assert audit_gateway.calls == []


def test_request_without_a_confirmed_step_up_is_refused(db, audit_gateway):
    """Changing a linked SSO account is one of Auth's own named step-up-gated sensitive
    actions (Auth deep-dive §4.5) — an unconfirmed step-up must fail closed, never proceed
    optimistically (`docs/PRINCIPLES.md` §4.2)."""
    result = run(sso_linking.request_link(db, audit_gateway, "user_a", "google", step_up_confirmed=False))

    assert result.error == E_INVALID_REQUEST
    assert audit_gateway.calls == []


def test_a_confirmed_request_is_recorded_and_honestly_reports_its_own_limitation(db, audit_gateway):
    """The real mutation is blocked on an Auth RPC that does not exist yet (`gateways.py`) —
    the request must say so via `PENDING_AUTH_MUTATION`, never claim `COMPLETED`."""
    result = run(sso_linking.request_link(db, audit_gateway, "user_a", "google", step_up_confirmed=True))

    assert result.request.stage is SsoLinkStage.PENDING_AUTH_MUTATION
    assert result.request.error_detail
    assert result.audit_recorded
    operation, actor, target, _reason, details = audit_gateway.calls[0]
    assert operation == "account_guardian_sso_provider_change_requested"
    assert actor == target == "user_a"
    assert details["provider"] == "google"


def test_one_user_cannot_cancel_anothers_sso_link_request(db, audit_gateway):
    created = run(sso_linking.request_link(db, audit_gateway, "user_a", "google", step_up_confirmed=True)).request

    result = run(sso_linking.cancel(db, created.request_id, "user_b"))

    assert result.error == E_OWNERSHIP_DENIED


def test_the_requesting_user_can_cancel_their_own_request(db, audit_gateway):
    created = run(sso_linking.request_link(db, audit_gateway, "user_a", "google", step_up_confirmed=True)).request

    result = run(sso_linking.cancel(db, created.request_id, "user_a"))

    assert result.request.stage is SsoLinkStage.REJECTED


def test_cancelling_an_unknown_request_is_not_found(db):
    result = run(sso_linking.cancel(db, "sso_ghost", "user_a"))
    assert result.error == E_NOT_FOUND
