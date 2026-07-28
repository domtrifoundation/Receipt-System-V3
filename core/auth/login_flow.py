"""Login orchestration: pick a provider, run it, apply the second-factor gate, issue.

Split out of `service.py` so that file stays what the deep-dive's §2 layout calls it — a
thin gRPC implementation that delegates. Everything here is expressed in this package's own
contract types with no protobuf anywhere, which is also what makes the flow testable without
standing up a server.

**`complete()` is written once for all four methods on purpose.** 2FA is composable over any
primary method (§4.6), so a per-method copy of "verify, then check whether a second factor is
owed, then issue" would be four separate chances for one method to quietly skip the gate.
There is exactly one place in this package where a `Session` comes into existence, and it is
below the second-factor check.

Errors here are data (`errors.py`): every failure in this file is a failed *attempt* to
become someone, which yields no session and therefore cannot be ignored into an access grant.
The raising failures live at the other end — validating a session that already exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from .auth_methods.base import AuthMethodRegistry
from .auth_methods.two_factor import TwoFactorGate
from .contracts import (
    AuthChallenge,
    AuthError,
    AuthMethod,
    AuthResult,
    ChallengePurpose,
    InstallProfile,
    IssuedSession,
)
from .metrics import (
    LOGIN_FAILED,
    LOGIN_INITIATED,
    LOGIN_SUCCEEDED,
    SECOND_FACTOR_REQUIRED,
    AuthMetrics,
)
from .session.session_store import SessionStore
from .store import UserDirectory, in_thread


@dataclass(frozen=True)
class LoginOutcome:
    """Either a session, or the reason there isn't one.

    `second_factor_method` is populated on the specific "primary method succeeded, a second
    factor is still owed" outcome — the caller re-submits with a code rather than starting
    the login again, which is why this is a distinct state and not a plain failure.
    """

    issued: IssuedSession | None = None
    error: AuthError | None = None
    error_detail: str = ""
    second_factor_method: str = ""

    @property
    def ok(self) -> bool:
        return self.issued is not None


class LoginFlow:
    def __init__(
        self,
        profile: InstallProfile,
        registry: AuthMethodRegistry,
        sessions: SessionStore,
        directory: UserDirectory,
        two_factor: TwoFactorGate,
        metrics: AuthMetrics | None = None,
    ) -> None:
        self._profile = profile
        self._registry = registry
        self._sessions = sessions
        self._directory = directory
        self._two_factor = two_factor
        self._metrics = metrics or AuthMetrics()

    async def initiate(
        self, method: AuthMethod, identifier: str,
        purpose: ChallengePurpose = ChallengePurpose.LOGIN,
    ) -> AuthChallenge:
        provider, error = await self._registry.resolve(method, self._profile)
        if error is not None or provider is None:
            return AuthChallenge.failure(
                method, error or AuthError.METHOD_UNAVAILABLE, "", purpose
            )
        self._metrics.increment(LOGIN_INITIATED)
        return await provider.initiate(identifier, purpose)

    async def verify(
        self, method: AuthMethod, challenge_id: str, response: str
    ) -> AuthResult:
        provider, error = await self._registry.resolve(method, self._profile)
        if error is not None or provider is None:
            return AuthResult.failure(method, error or AuthError.METHOD_UNAVAILABLE)
        return await provider.verify(challenge_id, response)

    async def complete(
        self, result: AuthResult, second_factor_code: str = ""
    ) -> LoginOutcome:
        if not result.authenticated or not result.user_id:
            self._metrics.increment(LOGIN_FAILED)
            return LoginOutcome(
                error=result.error or AuthError.SESSION_INVALID,
                error_detail=result.error_detail,
            )
        if result.purpose is not ChallengePurpose.LOGIN:
            # A step-up or registration challenge cannot be cashed in for a session. This is
            # the same separation that makes §4.5's gate real, enforced from the other side.
            self._metrics.increment(LOGIN_FAILED)
            return LoginOutcome(
                error=AuthError.CHALLENGE_NOT_FOUND,
                error_detail=f"challenge was issued for {result.purpose.value}, not login",
            )

        user = await in_thread(self._directory.get, result.user_id)
        if user is None:
            self._metrics.increment(LOGIN_FAILED)
            return LoginOutcome(error=AuthError.UNKNOWN_USER)

        decision = await in_thread(self._two_factor.decide, user.user_id, user.role)
        if decision.required:
            if not decision.satisfiable:
                self._metrics.increment(SECOND_FACTOR_REQUIRED)
                return LoginOutcome(
                    error=AuthError.SECOND_FACTOR_REQUIRED,
                    error_detail="policy requires a second factor this user has not "
                                 "enrolled in; enrol before signing in",
                )
            if not second_factor_code:
                self._metrics.increment(SECOND_FACTOR_REQUIRED)
                return LoginOutcome(
                    error=AuthError.SECOND_FACTOR_REQUIRED,
                    second_factor_method=decision.method or "",
                )
            error = await self._two_factor.verify_second_factor(
                user.user_id, second_factor_code
            )
            if error is not None:
                self._metrics.increment(LOGIN_FAILED)
                return LoginOutcome(error=error, second_factor_method=decision.method or "")

        issued = await self._sessions.create(user.user_id, user.role)
        self._metrics.increment(LOGIN_SUCCEEDED)
        return LoginOutcome(issued=issued)


__all__ = ["LoginFlow", "LoginOutcome"]
