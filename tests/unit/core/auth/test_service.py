"""Servicer behaviour at the transport edge.

Two things are asserted here that cannot be asserted anywhere else, because they are about
*how a failure leaves this API*:

- Session and role failures leave as gRPC statuses, not as a field on a response. That is
  `docs/PRINCIPLES.md` §4.1's carve-out made concrete — Gateway turns them into 401/403 and
  a caller cannot ignore them by forgetting to read a field.
- The step-up gate is server-side. §11 asks for a test confirming a sensitive action
  "genuinely cannot proceed without a fresh challenge-response, not just a UI-level prompt
  that a direct API call could skip" — `test_two_factor_config_cannot_be_changed_without_
  step_up` is that test, and it calls the RPC directly with no UI involved.
"""

from __future__ import annotations

import time

import pytest

# `nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio,
# because grpcio has no prebuilt wheel for 3.15 yet (noxfile.py's own module docstring, and
# `docs/MAINTENANCE.md` §8.1). A bare module-level `import grpc` here does not just skip these
# tests under that session — it breaks *collection*, which fails the whole forward_compat gate
# on both interpreters including 3.14, where grpcio is fine. Skip rather than break, the same
# graceful-degradation posture the rest of the project takes toward an unavailable optional
# dependency (`docs/PRINCIPLES.md` §4.4).
grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.auth.assembly import build_servicer  # noqa: E402
from core.auth.auth_methods.two_factor import StdlibTotpEngine  # noqa: E402
from core.auth.contracts import AuthError, Role, TenancyMode, User  # noqa: E402
from core.auth.generated import auth_pb2 as pb  # noqa: E402

from .conftest import RecordingChannel, run


class Aborted(Exception):
    """What the fake context raises. Real `grpc.aio` abort also raises rather than
    returning, so a servicer method that keeps going after aborting is a bug either way."""

    def __init__(self, code, details):
        super().__init__(f"{code}: {details}")
        self.code = code
        self.details = details


class FakeContext:
    async def abort(self, code, details):
        raise Aborted(code, details)


@pytest.fixture
def channel():
    return RecordingChannel("email")


@pytest.fixture
def servicer(db, channel):
    return build_servicer(
        {"tenancy_mode": "multi", "public_facing": False},
        db=db, email_channel=channel,
    )


@pytest.fixture
def single_servicer(db):
    return build_servicer({"tenancy_mode": "single"}, db=db)


@pytest.fixture
def user(db):
    from core.auth.store import UserDirectory

    return UserDirectory(db).create_user(User(
        user_id="u_owner", role=Role.OWNER, email="owner@example.test"
    ))


def _login(servicer, channel, user) -> pb.SessionResponse:
    started = run(servicer.InitiateEmailLogin(
        pb.EmailLoginRequest(email=user.email), FakeContext()
    ))
    assert not started.error_code, started.error_code
    return run(servicer.VerifyEmailLogin(
        pb.OtpVerifyRequest(challenge_id=started.challenge_id, code=channel.last_code),
        FakeContext(),
    ))


def test_a_full_email_login_returns_a_session_and_csrf_token(servicer, channel, user):
    response = _login(servicer, channel, user)
    assert response.session_id and response.csrf_token
    assert response.user_id == user.user_id
    assert response.role == "owner"


def test_validate_session_rejects_an_unknown_session_with_a_status_not_a_field(servicer):
    with pytest.raises(Aborted) as caught:
        run(servicer.ValidateSession(
            pb.ValidateSessionRequest(session_id="nope"), FakeContext()
        ))
    assert caught.value.code is grpc.StatusCode.UNAUTHENTICATED
    assert AuthError.SESSION_INVALID.value in caught.value.details


def test_validate_session_accepts_a_live_session(servicer, channel, user):
    issued = _login(servicer, channel, user)
    validated = run(servicer.ValidateSession(
        pb.ValidateSessionRequest(session_id=issued.session_id), FakeContext()
    ))
    assert validated.user_id == user.user_id


def test_a_mutating_request_without_a_csrf_token_is_refused(servicer, channel, user):
    """Failure injection, §11 — `SameSite=Lax` alone is not treated as sufficient."""
    issued = _login(servicer, channel, user)
    with pytest.raises(Aborted) as caught:
        run(servicer.ValidateSession(
            pb.ValidateSessionRequest(
                session_id=issued.session_id, http_method="POST", csrf_token=""
            ),
            FakeContext(),
        ))
    assert caught.value.code is grpc.StatusCode.PERMISSION_DENIED
    assert AuthError.CSRF_TOKEN_INVALID.value in caught.value.details


def test_a_mutating_request_with_the_right_token_proceeds(servicer, channel, user):
    issued = _login(servicer, channel, user)
    validated = run(servicer.ValidateSession(
        pb.ValidateSessionRequest(
            session_id=issued.session_id, http_method="POST", csrf_token=issued.csrf_token
        ),
        FakeContext(),
    ))
    assert validated.session_id == issued.session_id


def test_revocation_is_visible_on_the_next_validate(servicer, channel, user):
    issued = _login(servicer, channel, user)
    revoked = run(servicer.RevokeSession(
        pb.RevokeSessionRequest(session_id=issued.session_id), FakeContext()
    ))
    assert revoked.revoked
    with pytest.raises(Aborted):
        run(servicer.ValidateSession(
            pb.ValidateSessionRequest(session_id=issued.session_id), FakeContext()
        ))


def test_revoke_all_for_user_reports_how_many_it_killed(servicer, channel, user):
    _login(servicer, channel, user)
    _login(servicer, channel, user)
    response = run(servicer.RevokeSession(
        pb.RevokeSessionRequest(all_for_user=True, user_id=user.user_id), FakeContext()
    ))
    assert response.sessions_revoked == 2


def test_two_factor_config_cannot_be_changed_without_step_up(servicer, channel, user):
    """The §11 bypass test: no UI involved, the RPC is called directly, and it still fails."""
    issued = _login(servicer, channel, user)
    with pytest.raises(Aborted) as caught:
        run(servicer.ConfigureTwoFactor(
            pb.TwoFactorConfigRequest(
                session_id=issued.session_id, user_id=user.user_id, enabled=True,
                method="totp",
            ),
            FakeContext(),
        ))
    assert caught.value.code is grpc.StatusCode.PERMISSION_DENIED
    assert AuthError.STEP_UP_REQUIRED.value in caught.value.details


def test_step_up_then_enrol_totp(servicer, channel, user):
    issued = _login(servicer, channel, user)
    started = run(servicer.InitiateStepUpReauth(
        pb.StepUpRequest(session_id=issued.session_id, method="email", action="enrol"),
        FakeContext(),
    ))
    assert not started.error_code
    completed = run(servicer.CompleteStepUpReauth(
        pb.StepUpCompleteRequest(
            session_id=issued.session_id, challenge_id=started.challenge_id,
            response=channel.last_code,
        ),
        FakeContext(),
    ))
    assert completed.satisfied

    enrolment = run(servicer.ConfigureTwoFactor(
        pb.TwoFactorConfigRequest(
            session_id=issued.session_id, user_id=user.user_id, enabled=True, method="totp"
        ),
        FakeContext(),
    ))
    assert enrolment.totp_secret and not enrolment.enabled
    confirmed = run(servicer.ConfigureTwoFactor(
        pb.TwoFactorConfigRequest(
            session_id=issued.session_id, user_id=user.user_id, enabled=True, method="totp",
            totp_confirmation_code=StdlibTotpEngine().code_at(
                enrolment.totp_secret, time.time()
            ),
        ),
        FakeContext(),
    ))
    assert confirmed.enabled


def test_a_login_challenge_cannot_satisfy_a_step_up(servicer, channel, user):
    """The challenge was issued for login, so redeeming it must not elevate the session."""
    issued = _login(servicer, channel, user)
    started = run(servicer.InitiateEmailLogin(
        pb.EmailLoginRequest(email=user.email), FakeContext()
    ))
    completed = run(servicer.CompleteStepUpReauth(
        pb.StepUpCompleteRequest(
            session_id=issued.session_id, challenge_id=started.challenge_id,
            response=channel.last_code,
        ),
        FakeContext(),
    ))
    assert not completed.satisfied


def test_step_up_refuses_anything_that_is_not_one_of_the_four_methods(
    servicer, channel, user
):
    issued = _login(servicer, channel, user)
    response = run(servicer.InitiateStepUpReauth(
        pb.StepUpRequest(session_id=issued.session_id, method="password", action="anything"),
        FakeContext(),
    ))
    assert response.error_code == AuthError.METHOD_NOT_ENABLED.value


def test_break_glass_requires_a_reason_and_reports_it_as_data(servicer):
    refused = run(servicer.RequestBreakGlassGrant(
        pb.BreakGlassRequest(
            staff_user_id="s", target_client_user_id="c", reason="  "
        ),
        FakeContext(),
    ))
    assert refused.error_code == AuthError.REASON_REQUIRED.value
    assert not run(servicer.CheckBreakGlassAccess(
        pb.BreakGlassCheckRequest(staff_user_id="s", target_client_user_id="c"),
        FakeContext(),
    )).allowed

    granted = run(servicer.RequestBreakGlassGrant(
        pb.BreakGlassRequest(
            staff_user_id="s", target_client_user_id="c", reason="ticket-4",
            duration_minutes=30,
        ),
        FakeContext(),
    ))
    assert granted.grant_id
    assert run(servicer.CheckBreakGlassAccess(
        pb.BreakGlassCheckRequest(staff_user_id="s", target_client_user_id="c"),
        FakeContext(),
    )).allowed


def test_break_glass_duration_over_the_maximum_is_refused(servicer):
    response = run(servicer.RequestBreakGlassGrant(
        pb.BreakGlassRequest(
            staff_user_id="s", target_client_user_id="c", reason="ticket-4",
            duration_minutes=10_000,
        ),
        FakeContext(),
    ))
    assert response.error_code == AuthError.DURATION_NOT_ALLOWED.value


def test_list_auth_methods_reports_each_method_state(servicer, channel):
    response = run(servicer.ListAuthMethods(pb.ListAuthMethodsRequest(), FakeContext()))
    states = {m.method: m for m in response.methods}
    assert set(states) == {"sso", "passkey", "email", "sms"}
    assert states["email"].available and not states["sms"].available
    assert response.tenancy_mode == TenancyMode.MULTI.value


def test_single_tenant_installs_short_circuit_every_login_path(single_servicer):
    """A self-hosted user never sees the OIDC machinery attempt to run (§6.2)."""
    assert single_servicer.InitiateOIDCLogin.__name__  # sanity: the RPC exists
    started = run(single_servicer.InitiateOIDCLogin(
        pb.InitiateLoginRequest(provider="google"), FakeContext()
    ))
    assert started.error_code == AuthError.METHOD_NOT_ENABLED.value
    otp = run(single_servicer.InitiateEmailLogin(
        pb.EmailLoginRequest(email="anyone@example.test"), FakeContext()
    ))
    assert otp.error_code == AuthError.METHOD_NOT_ENABLED.value


def test_single_tenant_validate_returns_the_implicit_owner(single_servicer):
    response = run(single_servicer.ValidateSession(
        pb.ValidateSessionRequest(session_id="anything"), FakeContext()
    ))
    assert response.role == Role.OWNER.value
    assert response.user_id == "owner"


# --------------------------------------------------------------------------------------
# Regression: the step-up gate proves *this human is still present*. It says nothing about
# whose account they may act on. `ConfigureTwoFactor` took `request.user_id` on trust, so any
# authenticated session — a client's — could name another user and switch that user's second
# factor off. Gateway structurally cannot catch this: it sees a route, not which account a
# body field targets.
# --------------------------------------------------------------------------------------


@pytest.fixture
def two_users(db):
    from core.auth.store import UserDirectory

    directory = UserDirectory(db)
    attacker = directory.create_user(User(
        user_id="u_attacker", role=Role.CLIENT, email="attacker@example.test"
    ))
    victim = directory.create_user(User(
        user_id="u_victim", role=Role.CLIENT, email="victim@example.test"
    ))
    return directory, attacker, victim


def _enrol_totp(servicer, channel, user) -> str:
    """Enrol `user` in TOTP through the real RPC path and return their secret."""
    issued = _login(servicer, channel, user)
    _satisfy_step_up(servicer, channel, issued.session_id)
    begun = run(servicer.ConfigureTwoFactor(
        pb.TwoFactorConfigRequest(
            session_id=issued.session_id, user_id=user.user_id, enabled=True, method="totp"
        ),
        FakeContext(),
    ))
    assert begun.totp_secret
    confirmed = run(servicer.ConfigureTwoFactor(
        pb.TwoFactorConfigRequest(
            session_id=issued.session_id, user_id=user.user_id, enabled=True, method="totp",
            totp_confirmation_code=StdlibTotpEngine().code_at(
                begun.totp_secret, time.time()
            ),
        ),
        FakeContext(),
    ))
    assert confirmed.enabled
    return begun.totp_secret


def _satisfy_step_up(servicer, channel, session_id) -> None:
    started = run(servicer.InitiateStepUpReauth(
        pb.StepUpRequest(session_id=session_id, method="email", action="x"), FakeContext()
    ))
    assert not started.error_code, started.error_code
    done = run(servicer.CompleteStepUpReauth(
        pb.StepUpCompleteRequest(
            session_id=session_id, challenge_id=started.challenge_id,
            response=channel.last_code,
        ),
        FakeContext(),
    ))
    assert done.satisfied


def test_a_session_cannot_configure_another_users_second_factor(
    servicer, channel, two_users
):
    directory, attacker, victim = two_users
    _enrol_totp(servicer, channel, victim)
    assert directory.get_two_factor(victim.user_id).enabled

    issued = _login(servicer, channel, attacker)
    _satisfy_step_up(servicer, channel, issued.session_id)
    with pytest.raises(Aborted) as caught:
        run(servicer.ConfigureTwoFactor(
            pb.TwoFactorConfigRequest(
                session_id=issued.session_id, user_id=victim.user_id, enabled=False
            ),
            FakeContext(),
        ))
    assert caught.value.code is grpc.StatusCode.PERMISSION_DENIED
    assert AuthError.ROLE_INSUFFICIENT.value in caught.value.details
    assert directory.get_two_factor(victim.user_id).enabled


def test_starting_an_enrolment_on_another_user_is_refused_too(servicer, channel, two_users):
    """The enrolment branch is a separate code path inside the same RPC, so it needs its own
    assertion — writing a fresh secret against someone else's account is exactly as much of
    a takeover as disabling their existing one."""
    directory, attacker, victim = two_users
    secret = _enrol_totp(servicer, channel, victim)

    issued = _login(servicer, channel, attacker)
    _satisfy_step_up(servicer, channel, issued.session_id)
    with pytest.raises(Aborted):
        run(servicer.ConfigureTwoFactor(
            pb.TwoFactorConfigRequest(
                session_id=issued.session_id, user_id=victim.user_id, enabled=True,
                method="totp",
            ),
            FakeContext(),
        ))
    assert directory.get_totp_secret(victim.user_id) == secret
    assert directory.get_pending_totp_secret(victim.user_id) is None


def test_a_session_may_still_configure_its_own_second_factor(servicer, channel, two_users):
    """The fix must not close the ordinary self-service case it sits in front of."""
    directory, attacker, _victim = two_users
    _enrol_totp(servicer, channel, attacker)
    assert directory.get_two_factor(attacker.user_id).enabled
