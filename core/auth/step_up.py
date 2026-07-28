"""Step-up re-authentication and second-factor configuration (deep-dive §4.5, §4.6).

Split out of `service.py` for the same reason `login_flow.py` was: the servicer stays a
translation layer, and this logic stays testable without a server. The two modules are
deliberately separate from each other too — logging in and *proving you are still there*
before a sensitive action are different questions, and the second one is only meaningful
because its challenges can never be redeemed as the first.

**The challenge is always one of the four passwordless methods.** There is no
"confirm with your password" path here, because there is no password anywhere in this design
to confirm with. A system that got login right and then reintroduced a memorized secret at
the confirmation step would have missed the entire point of §4 — this module is where that
would have happened, so it is stated here.

**Satisfaction is a server-side timestamp**, written only by redeeming a `STEP_UP` challenge
belonging to the session's own user. That chain is what makes the gate un-bypassable by a
direct API call that skips the UI prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from .auth_methods.base import AuthMethodRegistry
from .auth_methods.two_factor import TwoFactorGate
from .challenges import ChallengeStore
from .contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    ChallengePurpose,
    InstallProfile,
    Session,
    TwoFactorConfig,
)
from .errors import TwoFactorPolicyFloor
from .login_flow import LoginFlow
from .session.session_store import SessionStore
from .store import UserDirectory, in_thread


@dataclass(frozen=True)
class StepUpOutcome:
    satisfied: bool = False
    error: AuthError | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class TwoFactorOutcome:
    """Either a settled configuration, or an enrolment that is not finished yet.

    `totp_secret` is populated exactly once, when enrolment begins, and the configuration
    stays disabled until a code from the user's own authenticator confirms it — enabling on
    an unverified secret is how someone locks themselves out of their own account.
    """

    config: TwoFactorConfig | None = None
    totp_secret: str = ""
    provisioning_uri: str = ""
    error: AuthError | None = None
    error_detail: str = ""


class StepUpFlow:
    def __init__(
        self,
        profile: InstallProfile,
        registry: AuthMethodRegistry,
        sessions: SessionStore,
        directory: UserDirectory,
        two_factor: TwoFactorGate,
        challenges: ChallengeStore,
        login: LoginFlow,
    ) -> None:
        self._profile = profile
        self._registry = registry
        self._sessions = sessions
        self._directory = directory
        self._two_factor = two_factor
        self._challenges = challenges
        self._login = login

    async def initiate(self, session: Session, method_name: str) -> AuthChallenge:
        try:
            method = AuthMethod(method_name)
        except ValueError:
            # Catches anything password-shaped a caller might try, along with typos. There
            # is no password method to fall back to, here or anywhere else.
            return AuthChallenge.failure(
                AuthMethod.EMAIL, AuthError.METHOD_NOT_ENABLED,
                f"{method_name!r} is not one of the four supported methods",
                ChallengePurpose.STEP_UP,
            )
        identifier = session.user_id
        if method in (AuthMethod.EMAIL, AuthMethod.SMS):
            user = await in_thread(self._directory.get, session.user_id)
            if user is None:
                return AuthChallenge.failure(
                    AuthMethod.EMAIL, AuthError.UNKNOWN_USER, "", ChallengePurpose.STEP_UP
                )
            identifier = user.email if method is AuthMethod.EMAIL else (user.phone_number or "")
        return await self._login.initiate(method, identifier, ChallengePurpose.STEP_UP)

    async def complete(
        self, session: Session, challenge_id: str, response: str
    ) -> StepUpOutcome:
        """Redeem a step-up challenge and elevate the session if it genuinely satisfies it.

        The challenge itself says which method issued it, and the lookup is filtered to
        `STEP_UP`. Routing that way rather than offering the response to each provider in
        turn matters twice over: a login challenge is rejected outright instead of being
        partially processed, and no provider burns an attempt on a challenge that was never
        its own.
        """
        stored, error = await in_thread(
            self._challenges.load, challenge_id, ChallengePurpose.STEP_UP
        )
        if error is not None or stored is None:
            return StepUpOutcome(error=error or AuthError.CHALLENGE_NOT_FOUND)
        provider = self._registry.get(stored.method)
        if provider is None:
            return StepUpOutcome(error=AuthError.METHOD_UNAVAILABLE)
        result = await provider.verify(challenge_id, response)
        # Two conditions make this gate real rather than decorative: the challenge must have
        # been issued *for* step-up, and the identity that proved it must be the session's
        # own. Either one missing and the session stays un-elevated.
        if not (
            result.authenticated
            and result.purpose is ChallengePurpose.STEP_UP
            and result.user_id == session.user_id
        ):
            return StepUpOutcome(
                error=result.error or AuthError.STEP_UP_REQUIRED,
                error_detail=result.error_detail,
            )
        await self._sessions.mark_step_up(session.session_id)
        return StepUpOutcome(satisfied=True)

    async def configure_two_factor(
        self, user_id: str, role, enabled: bool, method: str | None,
        confirmation_code: str = "", account_label: str = "",
    ) -> TwoFactorOutcome:
        """Callers must have satisfied `require_step_up` first — the servicer does, and the
        gate lives there because it is a property of the *request*, not of this change."""
        try:
            if enabled and method == "totp":
                return await self._totp_enrolment(user_id, confirmation_code, account_label)
            config = await in_thread(
                self._two_factor.configure, user_id, role, enabled, method or None
            )
            return TwoFactorOutcome(config=config)
        except TwoFactorPolicyFloor as exc:
            return TwoFactorOutcome(
                error=AuthError.TWO_FACTOR_POLICY_FLOOR, error_detail=str(exc)
            )
        except ValueError as exc:
            return TwoFactorOutcome(
                error=AuthError.SECOND_FACTOR_INVALID, error_detail=str(exc)
            )

    async def _totp_enrolment(
        self, user_id: str, confirmation_code: str, account_label: str
    ) -> TwoFactorOutcome:
        if not confirmation_code:
            secret, uri = await self._two_factor.begin_totp_enrolment(user_id, account_label)
            return TwoFactorOutcome(
                config=TwoFactorConfig(user_id=user_id, enabled=False, method="totp"),
                totp_secret=secret, provisioning_uri=uri,
            )
        if not await self._two_factor.confirm_totp_enrolment(user_id, confirmation_code):
            return TwoFactorOutcome(error=AuthError.SECOND_FACTOR_INVALID)
        return TwoFactorOutcome(
            config=TwoFactorConfig(user_id=user_id, enabled=True, method="totp")
        )


__all__ = ["StepUpFlow", "StepUpOutcome", "TwoFactorOutcome"]
