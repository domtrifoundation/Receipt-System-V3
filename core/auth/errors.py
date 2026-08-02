"""The exceptions this API raises — and, just as importantly, the ones it does not define.

`docs/PRINCIPLES.md` §4.1 makes Auth & Tenancy the single deliberate exception to
errors-as-data, and the deep-dive (§3) is specific about why: a `SESSION_EXPIRED` or
`ROLE_INSUFFICIENT` should propagate as a real gRPC error status that Gateway turns into a
401/403, not a result field a caller could accidentally never check.

**The line, drawn once, so it does not get redrawn ad hoc later:**

- **Raised (everything in this module).** Failures of an *already-granted* identity:
  the session is invalid, expired, or revoked; the role on it is insufficient; a step-up
  gate has not been satisfied; a break-glass grant relied on for access has expired.
  Ignoring any of these means proceeding with access that was not granted.
- **Returned as data** (`AuthResult.error` / `AuthChallenge.error`, `contracts.py`).
  Failures of an *attempt to become* an identity: a wrong OTP, a mismatched OIDC state, an
  unreachable SMS gateway, a disabled method. These produce no session at all, so a caller
  that ignores the error is not thereby authenticated as anyone — the ordinary convention
  is safe here and is therefore what this package uses.

If a future change needs a new error, the question to answer is that one: *does ignoring it
grant access?* Yes means it belongs here. No means it belongs in `AuthError` as data.

There is deliberately no exception here for a password failure, because there is no
password anywhere in this design (deep-dive §4).
"""

from __future__ import annotations

from .contracts import AuthError, Role


class AuthFailure(Exception):
    """Base for every failure this API raises rather than returns.

    Carries an `AuthError` so a transport layer can map it without re-deriving the meaning
    from the exception class name — `service.py` aborts with an `UNAUTHENTICATED` or
    `PERMISSION_DENIED` status and this code as the detail.
    """

    error: AuthError = AuthError.SESSION_INVALID

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.error.value)
        self.detail = detail


class SessionInvalid(AuthFailure):
    """No such session, or it has been revoked. Revocation takes effect on the very next
    request — a single committed row update, no propagation delay (deep-dive §5.1)."""

    error = AuthError.SESSION_INVALID


class SessionExpired(AuthFailure):
    """The session existed and has passed its own TTL."""

    error = AuthError.SESSION_EXPIRED


class RoleInsufficient(AuthFailure):
    """The session is valid but its role does not cover the requested action.

    Auth produces the role claim; acting on it is Gateway's job (deep-dive §6.1). This
    exception is the shared helper both sides use so the check reads the same everywhere.
    """

    error = AuthError.ROLE_INSUFFICIENT

    def __init__(self, held: Role, required: tuple[Role, ...]) -> None:
        super().__init__(
            f"role {held.value!r} is not one of "
            f"{', '.join(sorted(r.value for r in required))}"
        )
        self.held = held
        self.required = required


class StepUpRequired(AuthFailure):
    """A sensitive action was attempted without a fresh re-authentication (§4.5).

    Raised, not returned, precisely because the failure mode this guards against is a
    caller skipping the UI prompt and calling the API directly — a result field it could
    forget to check would leave exactly that hole open.
    """

    error = AuthError.STEP_UP_REQUIRED


class BreakGlassExpired(AuthFailure):
    """A grant relied on for access is expired or revoked.

    `check_access()` itself returns a plain `bool` (deep-dive §6.3) — this is for the
    `assert_access()` form used where a caller wants the failure to stop it dead rather
    than branch on it.
    """

    error = AuthError.BREAK_GLASS_EXPIRED


class TwoFactorPolicyFloor(ValueError):
    """An attempt to configure 2FA below the floor a publicly-exposed multi-tenant install
    enforces (§4.6.1).

    Deliberately a `ValueError`, not an `AuthFailure`: this is a rejected *configuration*
    change, not a failed authentication, and it is a caller programming error rather than
    something Gateway should translate into a 401.
    """


class SingleTenantShortCircuit(RuntimeError):
    """Multi-tenant machinery was reached on a `tenancy_mode: single` install.

    Deep-dive §6.2 asks for `single` mode to *structurally skip* the OIDC handshake, cookie
    negotiation and role enforcement — not to run them and silently succeed with a hardcoded
    identity. This is the guard that makes "structurally" true: reaching this exception
    means a caller bypassed the short-circuit, which is a bug in that caller and not an
    authentication outcome. Like `TwoFactorPolicyFloor`, it is deliberately not an
    `AuthFailure`, because Gateway must not translate a programming error into a 401.
    """


__all__ = [
    "AuthFailure", "BreakGlassExpired", "RoleInsufficient", "SessionExpired",
    "SessionInvalid", "SingleTenantShortCircuit", "StepUpRequired", "TwoFactorPolicyFloor",
]
