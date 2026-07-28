"""Login orchestration: the second-factor gate, and what may not be traded for a session."""

from __future__ import annotations

import time

import pytest

from core.auth.auth_methods.base import AuthMethodRegistry
from core.auth.auth_methods.email_login_provider import EmailLoginProvider
from core.auth.auth_methods.two_factor import StdlibTotpEngine, TwoFactorGate
from core.auth.contracts import (
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
    TwoFactorConfig,
)
from core.auth.login_flow import LoginFlow
from core.auth.session.session_store import SessionStore

from .conftest import RecordingChannel, run


@pytest.fixture
def channel():
    return RecordingChannel("email")


@pytest.fixture
def flow(db, challenges, directory, profile, channel):
    registry = AuthMethodRegistry([
        EmailLoginProvider(challenges, directory, profile, channel)
    ])
    return LoginFlow(
        profile, registry, SessionStore(db, profile.session_ttl_hours), directory,
        TwoFactorGate(directory, profile),
    )


@pytest.fixture
def public_flow(db, challenges, directory, public_profile, channel):
    registry = AuthMethodRegistry([
        EmailLoginProvider(challenges, directory, public_profile, channel)
    ])
    return LoginFlow(
        public_profile, registry,
        SessionStore(db, public_profile.session_ttl_hours), directory,
        TwoFactorGate(directory, public_profile),
    )


def _login(flow, channel, user):
    challenge = run(flow.initiate(AuthMethod.EMAIL, user.email))
    return run(flow.verify(AuthMethod.EMAIL, challenge.challenge_id, channel.last_code))


def test_a_clean_login_issues_a_session_and_a_csrf_token(flow, channel, client_user):
    outcome = run(flow.complete(_login(flow, channel, client_user)))
    assert outcome.ok
    assert outcome.issued.session.user_id == client_user.user_id
    assert outcome.issued.csrf_token


def test_a_failed_verification_never_reaches_session_issuance(flow):
    outcome = run(flow.complete(
        AuthResult.failure(AuthMethod.EMAIL, AuthError.CODE_INVALID)
    ))
    assert not outcome.ok and outcome.error is AuthError.CODE_INVALID


def test_a_step_up_challenge_cannot_be_cashed_in_for_a_session(flow, client_user):
    """The other side of §4.5's separation: a step-up proof is not a login."""
    outcome = run(flow.complete(AuthResult(
        authenticated=True, method=AuthMethod.EMAIL, purpose=ChallengePurpose.STEP_UP,
        user_id=client_user.user_id,
    )))
    assert not outcome.ok and outcome.error is AuthError.CHALLENGE_NOT_FOUND


def test_an_enrolled_user_must_supply_a_second_factor(flow, channel, directory, client_user):
    gate = TwoFactorGate(directory, flow._profile)  # noqa: SLF001 - fixture wiring
    secret, _ = run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    directory.set_two_factor(TwoFactorConfig(client_user.user_id, True, "totp"))

    owed = run(flow.complete(_login(flow, channel, client_user)))
    assert not owed.ok
    assert owed.error is AuthError.SECOND_FACTOR_REQUIRED
    assert owed.second_factor_method == "totp"

    code = StdlibTotpEngine().code_at(secret, time.time())
    completed = run(flow.complete(_login(flow, channel, client_user), code))
    assert completed.ok


def test_a_wrong_second_factor_refuses_the_login(flow, channel, directory, client_user):
    gate = TwoFactorGate(directory, flow._profile)  # noqa: SLF001 - fixture wiring
    run(gate.begin_totp_enrolment(client_user.user_id, client_user.email))
    directory.set_two_factor(TwoFactorConfig(client_user.user_id, True, "totp"))
    outcome = run(flow.complete(_login(flow, channel, client_user), "000000"))
    assert not outcome.ok and outcome.error is AuthError.SECOND_FACTOR_INVALID


def test_unenrolled_staff_cannot_sign_in_to_a_public_install(
    public_flow, channel, staff_user
):
    """`REQUIRED_FOR_ELEVATED` with nothing enrolled is a real state, and it must not
    silently fall through to a session."""
    outcome = run(public_flow.complete(_login(public_flow, channel, staff_user)))
    assert not outcome.ok
    assert outcome.error is AuthError.SECOND_FACTOR_REQUIRED
    assert "enrol" in outcome.error_detail


def test_a_client_on_a_public_install_is_not_forced_into_two_factor(
    public_flow, channel, client_user
):
    assert run(public_flow.complete(_login(public_flow, channel, client_user))).ok


def test_an_unavailable_method_is_refused_before_any_provider_runs(flow, channel, client_user):
    channel.up = False
    challenge = run(flow.initiate(AuthMethod.EMAIL, client_user.email))
    assert challenge.error is AuthError.METHOD_UNAVAILABLE
    result = run(flow.verify(AuthMethod.EMAIL, "anything", "000000"))
    assert result.error is AuthError.METHOD_UNAVAILABLE


def test_a_session_is_issued_with_the_users_current_role(flow, channel, staff_user):
    outcome = run(flow.complete(_login(flow, channel, staff_user)))
    assert outcome.issued.session.role is staff_user.role
