"""The `AuthService` gRPC servicer (deep-dive §9) — thin, delegating everything.

Nothing decides anything here. `LoginFlow` orchestrates a login, providers verify,
`TwoFactorGate` rules on strictness, `SessionStore` issues and revokes, `BreakGlassLedger`
grants, `tenancy` resolves install shape. This file translates between those and the wire,
and it is the one place the two error conventions actually become a response:

- `AuthFailure` (session, role, step-up) → `context.abort(UNAUTHENTICATED /
  PERMISSION_DENIED)`, which Gateway turns into a 401/403. Not a field, because a field can
  be ignored, and this API is `docs/PRINCIPLES.md` §4.1's one documented exception for
  exactly that reason.
- Everything else → an `error_code`/`error_detail` pair on the response message.

**Single-tenant installs short-circuit before any of this runs** (§6.2). `ValidateSession`
returns the implicit owner session and the login RPCs refuse rather than pretending: a
self-hosted user should never see OIDC machinery attempt to run at all, let alone run and
silently succeed against a hardcoded identity.

The servicer is `async` and served by `grpc.aio` because every path underneath it is — IdP
round trips, OTP delivery, thread-hopped SQLite reads (deep-dive §8.1).
"""

from __future__ import annotations

import json
from datetime import datetime

import grpc

from .auth_methods.base import AuthMethodRegistry
from .auth_methods.passkey_provider import PasskeyProvider
from .auth_methods.two_factor import TwoFactorGate
from .break_glass.grant import BreakGlassLedger
from .challenges import ChallengeStore
from .contracts import AuthChallenge, AuthError, AuthMethod, ChallengePurpose, InstallProfile
from .errors import AuthFailure, RoleInsufficient, StepUpRequired, TwoFactorPolicyFloor
from .generated import auth_pb2 as pb
from .generated import auth_pb2_grpc as pb_grpc
from .login_flow import LoginFlow, LoginOutcome
from .metrics import (
    BREAK_GLASS_CHECKED,
    BREAK_GLASS_GRANTED,
    LOGIN_LATENCY,
    SESSION_REJECTED,
    SESSION_REVOKED,
    SESSION_VALIDATED,
    STEP_UP_ISSUED,
    VALIDATE_LATENCY,
    AuthMetrics,
)
from .roles.role_check import require_step_up
from .session.cookie import check_csrf
from .session.session_store import SessionStore
from .store import UserDirectory, in_thread
from .tenancy import implicit_owner_session

DEFAULT_ADDRESS = "127.0.0.1:50056"


def _status_for(exc: AuthFailure) -> grpc.StatusCode:
    """Which gRPC status a raised failure becomes.

    A function rather than a lookup table on purpose: the fallback matters more than the
    mapping. Anything unrecognised becomes `UNAUTHENTICATED`, the more restrictive of the
    two, so a failure type added later without touching this file still fails closed.
    """
    if isinstance(exc, (RoleInsufficient, StepUpRequired)):
        return grpc.StatusCode.PERMISSION_DENIED
    return grpc.StatusCode.UNAUTHENTICATED


def _unix(moment: datetime | None) -> int:
    return int(moment.timestamp()) if moment else 0


def _challenge_error(challenge: AuthChallenge) -> tuple[str, str]:
    return (challenge.error or AuthError.METHOD_UNAVAILABLE).value, challenge.error_detail


class AuthServicer(pb_grpc.AuthServiceServicer):
    def __init__(
        self,
        profile: InstallProfile,
        registry: AuthMethodRegistry,
        sessions: SessionStore,
        directory: UserDirectory,
        two_factor: TwoFactorGate,
        break_glass: BreakGlassLedger,
        challenges: ChallengeStore,
        metrics: AuthMetrics | None = None,
    ) -> None:
        self._profile = profile
        self._registry = registry
        self._sessions = sessions
        self._directory = directory
        self._challenges = challenges
        self._two_factor = two_factor
        self._break_glass = break_glass
        self._metrics = metrics or AuthMetrics()
        self._flow = LoginFlow(
            profile, registry, sessions, directory, two_factor, self._metrics
        )

    # ------------------------------------------------------------- helpers
    async def _abort(self, context, exc: AuthFailure) -> None:
        self._metrics.increment(SESSION_REJECTED)
        await context.abort(_status_for(exc), f"{exc.error.value}: {exc.detail}")

    @staticmethod
    def _session_response(outcome: LoginOutcome) -> pb.SessionResponse:
        if not outcome.ok or outcome.issued is None:
            return pb.SessionResponse(
                error_code=(outcome.error or AuthError.SESSION_INVALID).value,
                error_detail=outcome.error_detail,
                second_factor_method=outcome.second_factor_method,
            )
        session = outcome.issued.session
        return pb.SessionResponse(
            session_id=session.session_id, user_id=session.user_id,
            role=session.role.value, expires_at_unix=_unix(session.expires_at),
            csrf_token=outcome.issued.csrf_token,
        )

    def _login_disabled(self) -> pb.SessionResponse:
        """What every login RPC returns on a `single`-tenant install."""
        return pb.SessionResponse(
            error_code=AuthError.METHOD_NOT_ENABLED.value,
            error_detail="this install is tenancy_mode: single and has no login flow",
        )

    async def _complete(
        self, method: AuthMethod, challenge_id: str, response: str, second_factor: str
    ) -> pb.SessionResponse:
        with self._metrics.timer(LOGIN_LATENCY):
            result = await self._flow.verify(method, challenge_id, response)
            return self._session_response(await self._flow.complete(result, second_factor))

    # ---------------------------------------------------------------- SSO
    async def InitiateOIDCLogin(self, request, context):
        if self._profile.short_circuited:
            return pb.InitiateLoginResponse(
                error_code=AuthError.METHOD_NOT_ENABLED.value,
                error_detail="this install is tenancy_mode: single",
            )
        challenge = await self._flow.initiate(AuthMethod.SSO, request.provider or "google")
        if not challenge.ok:
            code, detail = _challenge_error(challenge)
            return pb.InitiateLoginResponse(error_code=code, error_detail=detail)
        return pb.InitiateLoginResponse(
            challenge_id=challenge.challenge_id,
            redirect_url=str(challenge.parameters.get("redirect_url", "")),
            state=str(challenge.parameters.get("state", "")),
        )

    async def CompleteOIDCLogin(self, request, context):
        if self._profile.short_circuited:
            return self._login_disabled()
        return await self._complete(
            AuthMethod.SSO, request.challenge_id, request.callback,
            request.second_factor_code,
        )

    # ----------------------------------------------------------- passkeys
    def _passkey_provider(self) -> PasskeyProvider | None:
        provider = self._registry.get(AuthMethod.PASSKEY)
        return provider if isinstance(provider, PasskeyProvider) else None

    async def RegisterPasskey(self, request, context):
        provider = self._passkey_provider()
        if provider is None:
            return pb.RegisterPasskeyResponse(error_code=AuthError.METHOD_UNAVAILABLE.value)
        challenge = await provider.begin_registration(request.user_id)
        if not challenge.ok:
            code, detail = _challenge_error(challenge)
            return pb.RegisterPasskeyResponse(error_code=code, error_detail=detail)
        return pb.RegisterPasskeyResponse(
            challenge_id=challenge.challenge_id,
            options_json=json.dumps(dict(challenge.parameters), default=str),
        )

    async def CompletePasskeyRegistration(self, request, context):
        provider = self._passkey_provider()
        if provider is None:
            return pb.RegisterPasskeyResponse(error_code=AuthError.METHOD_UNAVAILABLE.value)
        result = await provider.complete_registration(
            request.challenge_id, request.assertion_json
        )
        if not result.authenticated:
            return pb.RegisterPasskeyResponse(
                error_code=(result.error or AuthError.PASSKEY_VERIFICATION_FAILED).value,
                error_detail=result.error_detail,
            )
        return pb.RegisterPasskeyResponse(
            credential_id=str(result.claims.get("credential_id", ""))
        )

    async def InitiatePasskeyLogin(self, request, context):
        if self._profile.short_circuited:
            return pb.PasskeyChallengeResponse(error_code=AuthError.METHOD_NOT_ENABLED.value)
        challenge = await self._flow.initiate(AuthMethod.PASSKEY, request.user_id)
        if not challenge.ok:
            code, detail = _challenge_error(challenge)
            return pb.PasskeyChallengeResponse(error_code=code, error_detail=detail)
        return pb.PasskeyChallengeResponse(
            challenge_id=challenge.challenge_id,
            options_json=json.dumps(dict(challenge.parameters), default=str),
        )

    async def CompletePasskeyLogin(self, request, context):
        if self._profile.short_circuited:
            return self._login_disabled()
        return await self._complete(
            AuthMethod.PASSKEY, request.challenge_id, request.assertion_json,
            request.second_factor_code,
        )

    # ------------------------------------------------------------ OTP pair
    async def _initiate_otp(self, method: AuthMethod, identifier: str):
        challenge = await self._flow.initiate(method, identifier)
        if not challenge.ok:
            code, detail = _challenge_error(challenge)
            return pb.OtpSentResponse(error_code=code, error_detail=detail)
        return pb.OtpSentResponse(
            challenge_id=challenge.challenge_id,
            channel=str(challenge.parameters.get("channel", "")),
            code_length=int(challenge.parameters.get("code_length", 6)),
            expires_at_unix=_unix(challenge.expires_at),
        )

    async def InitiateEmailLogin(self, request, context):
        if self._profile.short_circuited:
            return pb.OtpSentResponse(error_code=AuthError.METHOD_NOT_ENABLED.value)
        return await self._initiate_otp(AuthMethod.EMAIL, request.email)

    async def VerifyEmailLogin(self, request, context):
        return await self._complete(
            AuthMethod.EMAIL, request.challenge_id, request.code,
            request.second_factor_code,
        )

    async def InitiateSmsLogin(self, request, context):
        if self._profile.short_circuited:
            return pb.OtpSentResponse(error_code=AuthError.METHOD_NOT_ENABLED.value)
        return await self._initiate_otp(AuthMethod.SMS, request.phone_number)

    async def VerifySmsLogin(self, request, context):
        return await self._complete(
            AuthMethod.SMS, request.challenge_id, request.code, request.second_factor_code
        )

    # ------------------------------------------------- 2FA config, step-up
    async def ConfigureTwoFactor(self, request, context):
        """Changing 2FA is a sensitive action, gated on a fresh step-up (§4.5).

        The gate is server-side and raises. A caller that skips the UI prompt and calls this
        RPC directly hits the same check — the property §11's own bypass test exists for.
        """
        try:
            session = await self._sessions.validate(request.session_id)
            require_step_up(session, "configure two-factor authentication")
        except AuthFailure as exc:
            await self._abort(context, exc)
            return pb.TwoFactorConfigResponse()

        user_id = request.user_id or session.user_id
        user = await in_thread(self._directory.get, user_id)
        if user is None:
            return pb.TwoFactorConfigResponse(error_code=AuthError.UNKNOWN_USER.value)
        try:
            if request.enabled and request.method == "totp":
                return await self._totp_enrolment(request, user_id, user.email)
            config = await in_thread(
                self._two_factor.configure, user_id, user.role, request.enabled,
                request.method or None,
            )
            return pb.TwoFactorConfigResponse(
                enabled=config.enabled, method=config.method or ""
            )
        except TwoFactorPolicyFloor as exc:
            return pb.TwoFactorConfigResponse(
                error_code=AuthError.TWO_FACTOR_POLICY_FLOOR.value, error_detail=str(exc)
            )
        except ValueError as exc:
            return pb.TwoFactorConfigResponse(
                error_code=AuthError.SECOND_FACTOR_INVALID.value, error_detail=str(exc)
            )

    async def _totp_enrolment(self, request, user_id: str, account_label: str):
        """Two-step by design: the secret is issued disabled, and only a correct code from
        the user's own authenticator turns it on. Enabling on an unverified secret is how
        someone locks themselves out of their own account."""
        if not request.totp_confirmation_code:
            secret, uri = await self._two_factor.begin_totp_enrolment(user_id, account_label)
            return pb.TwoFactorConfigResponse(
                enabled=False, method="totp", totp_secret=secret, provisioning_uri=uri
            )
        confirmed = await self._two_factor.confirm_totp_enrolment(
            user_id, request.totp_confirmation_code
        )
        if not confirmed:
            return pb.TwoFactorConfigResponse(
                error_code=AuthError.SECOND_FACTOR_INVALID.value
            )
        return pb.TwoFactorConfigResponse(enabled=True, method="totp")

    async def InitiateStepUpReauth(self, request, context):
        try:
            session = await self._sessions.validate(request.session_id)
        except AuthFailure as exc:
            await self._abort(context, exc)
            return pb.StepUpChallengeResponse()
        try:
            method = AuthMethod(request.method)
        except ValueError:
            # Includes anything password-shaped a caller might try. There is no password
            # method to fall back to, here or anywhere else (§4.5).
            return pb.StepUpChallengeResponse(
                error_code=AuthError.METHOD_NOT_ENABLED.value,
                error_detail=f"{request.method!r} is not one of the four supported methods",
            )
        identifier = session.user_id
        if method in (AuthMethod.EMAIL, AuthMethod.SMS):
            user = await in_thread(self._directory.get, session.user_id)
            if user is None:
                return pb.StepUpChallengeResponse(error_code=AuthError.UNKNOWN_USER.value)
            identifier = user.email if method is AuthMethod.EMAIL else (user.phone_number or "")
        challenge = await self._flow.initiate(method, identifier, ChallengePurpose.STEP_UP)
        if not challenge.ok:
            code, detail = _challenge_error(challenge)
            return pb.StepUpChallengeResponse(error_code=code, error_detail=detail)
        self._metrics.increment(STEP_UP_ISSUED)
        return pb.StepUpChallengeResponse(
            challenge_id=challenge.challenge_id, method=method.value,
            parameters_json=json.dumps(dict(challenge.parameters), default=str),
        )

    async def CompleteStepUpReauth(self, request, context):
        try:
            session = await self._sessions.validate(request.session_id)
        except AuthFailure as exc:
            await self._abort(context, exc)
            return pb.StepUpCompleteResponse()
        # The challenge itself says which method issued it, and the lookup is filtered to
        # STEP_UP. Routing this way rather than offering the response to each provider in
        # turn matters twice over: a login challenge is rejected here instead of being
        # partially processed, and no provider burns an attempt on a challenge that was
        # never its own.
        stored, error = await in_thread(
            self._challenges.load, request.challenge_id, ChallengePurpose.STEP_UP
        )
        if error is not None or stored is None:
            return pb.StepUpCompleteResponse(
                error_code=(error or AuthError.CHALLENGE_NOT_FOUND).value
            )
        provider = self._registry.get(stored.method)
        if provider is None:
            return pb.StepUpCompleteResponse(error_code=AuthError.METHOD_UNAVAILABLE.value)
        result = await provider.verify(request.challenge_id, request.response)
        # Two conditions make this gate real rather than decorative: the challenge must have
        # been issued *for* step-up, and the identity that proved it must be the session's
        # own. Either one missing and the session stays un-elevated.
        if not (
            result.authenticated
            and result.purpose is ChallengePurpose.STEP_UP
            and result.user_id == session.user_id
        ):
            return pb.StepUpCompleteResponse(
                error_code=(result.error or AuthError.STEP_UP_REQUIRED).value,
                error_detail=result.error_detail,
            )
        await self._sessions.mark_step_up(session.session_id)
        refreshed = await self._sessions.get(session.session_id)
        return pb.StepUpCompleteResponse(
            satisfied=True,
            satisfied_at_unix=_unix(refreshed.step_up_at if refreshed else None),
        )

    # ------------------------------------------------------------ sessions
    async def ValidateSession(self, request, context):
        """The hot path. Every authenticated request in the cluster lands here."""
        if self._profile.short_circuited:
            session = implicit_owner_session(self._profile)
            return pb.SessionResponse(
                session_id=session.session_id, user_id=session.user_id,
                role=session.role.value, expires_at_unix=_unix(session.expires_at),
            )
        with self._metrics.timer(VALIDATE_LATENCY):
            try:
                session = await self._sessions.validate(request.session_id)
            except AuthFailure as exc:
                await self._abort(context, exc)
                return pb.SessionResponse()
            if request.http_method:
                expected = await self._sessions.csrf_token(request.session_id)
                error = check_csrf(request.http_method, request.csrf_token, expected)
                if error is not None:
                    self._metrics.increment(SESSION_REJECTED)
                    await context.abort(grpc.StatusCode.PERMISSION_DENIED, error.value)
                    return pb.SessionResponse()
            await self._sessions.touch(request.session_id)
            self._metrics.increment(SESSION_VALIDATED)
            return pb.SessionResponse(
                session_id=session.session_id, user_id=session.user_id,
                role=session.role.value, expires_at_unix=_unix(session.expires_at),
            )

    async def RevokeSession(self, request, context):
        if request.all_for_user:
            count = await self._sessions.revoke_all_for_user(request.user_id)
            self._metrics.increment(SESSION_REVOKED, count)
            return pb.RevokeResponse(revoked=count > 0, sessions_revoked=count)
        revoked = await self._sessions.revoke(request.session_id)
        self._metrics.increment(SESSION_REVOKED, int(revoked))
        return pb.RevokeResponse(revoked=revoked, sessions_revoked=int(revoked))

    # --------------------------------------------------------- break-glass
    async def RequestBreakGlassGrant(self, request, context):
        try:
            grant = await self._break_glass.request_grant(
                request.staff_user_id, request.target_client_user_id, request.reason,
                request.duration_minutes or None,
            )
        except ValueError as exc:
            code = (
                AuthError.REASON_REQUIRED if "reason" in str(exc)
                else AuthError.DURATION_NOT_ALLOWED
            )
            return pb.BreakGlassResponse(error_code=code.value, error_detail=str(exc))
        self._metrics.increment(BREAK_GLASS_GRANTED)
        return pb.BreakGlassResponse(
            grant_id=grant.grant_id, granted_at_unix=_unix(grant.granted_at),
            expires_at_unix=_unix(grant.expires_at),
        )

    async def CheckBreakGlassAccess(self, request, context):
        allowed = await self._break_glass.check_access(
            request.staff_user_id, request.target_client_user_id
        )
        self._metrics.increment(BREAK_GLASS_CHECKED)
        return pb.BreakGlassCheckResponse(allowed=allowed)

    # --------------------------------------------------------- login screen
    async def ListAuthMethods(self, request, context):
        statuses = await self._registry.availability(self._profile)
        return pb.ListAuthMethodsResponse(
            methods=[
                pb.AuthMethodStatus(
                    method=s.method.value, enabled=s.enabled, available=s.available,
                    detail=s.detail,
                )
                for s in statuses
            ],
            tenancy_mode=self._profile.tenancy_mode.value,
            two_factor_policy=self._profile.two_factor_policy.value,
        )


async def serve(servicer: AuthServicer, address: str = DEFAULT_ADDRESS) -> grpc.aio.Server:
    """Start the service and return the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one; the bound address is attached as
    `bound_address`. Worth having rather than a fixed port: Windows reserves scattered
    ranges in the 50000s, so a hard-coded high port is not reliably bindable everywhere.
    """
    server = grpc.aio.server()
    pb_grpc.add_AuthServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


__all__ = ["DEFAULT_ADDRESS", "AuthServicer", "serve"]
