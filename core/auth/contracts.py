"""Auth & Tenancy data contracts (`v3-deepdive-05-auth-tenancy-api.md` §3).

This is the only module in this package other APIs import from (deep-dive §2). It holds
types and no logic beyond trivially-derived predicates on a value's own fields.

Two rules meet here and they pull in opposite directions, so both are stated explicitly:

1. Every type below is `@dataclass(frozen=True)` and every dict-typed field is a
   `FrozenDict` (`docs/PRINCIPLES.md` §2.1). A frozen dataclass holding a plain `dict` is
   only shallowly immutable, and these cross a process boundary.
2. `AuthError` exists as *both* a data value and the vocabulary behind `errors.py`'s
   exceptions, because this API is the single documented exception to errors-as-data
   (`docs/PRINCIPLES.md` §4.1). The split is precise and worth learning once:

   - **Session and role failures raise** (`errors.py`). A caller that silently ignores an
     expired session or an insufficient role has just granted access it should not have.
   - **Everything else is data** — a wrong OTP code, an unreachable SMS provider, an OIDC
     state mismatch. These are outcomes of a login *attempt*; the attempt produced no
     session, so a caller ignoring the error still cannot proceed as anyone. Returning them
     keeps the ordinary convention wherever ignoring the error is not itself a security
     failure.

Anything that looks like a password belongs to neither category, because no such thing
exists anywhere in this design (deep-dive §4, §12) — there is no password field, no hash
column, and no recovery path here to add one to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    OWNER = "owner"
    STAFF = "staff"
    CLIENT = "client"


class TenancyMode(str, Enum):
    """`SINGLE` is a structural short-circuit, not a behavioural default (deep-dive §6.2)."""

    SINGLE = "single"
    MULTI = "multi"


class AuthMethod(str, Enum):
    """The four primary methods. There is deliberately no fifth, and never a password one.

    TOTP is not listed here on purpose (deep-dive §4.6): it is a second factor layered over
    one of these, not an independent way of proving identity in its own right.
    """

    SSO = "sso"
    PASSKEY = "passkey"
    EMAIL = "email"
    SMS = "sms"


class TwoFactorPolicy(str, Enum):
    OPTIONAL = "optional"
    REQUIRED_FOR_ELEVATED = "required_for_elevated"
    REQUIRED_FOR_ALL = "required_for_all"


class ChallengePurpose(str, Enum):
    """Why a challenge was issued. A `STEP_UP` challenge can never satisfy a `LOGIN` and
    vice versa — that separation is what stops §4.5's step-up gate being bypassable by
    replaying an ordinary login challenge."""

    LOGIN = "login"
    STEP_UP = "step_up"
    REGISTRATION = "registration"
    SECOND_FACTOR = "second_factor"


class AuthError(str, Enum):
    """Field-only-append discipline, same as the `.proto` (`docs/templates/`).

    The first five are the deep-dive's own §3 list; the rest were added as the flows below
    were actually implemented. Existing values are never renamed or removed.
    """

    SESSION_EXPIRED = "session_expired"
    SESSION_INVALID = "session_invalid"
    OIDC_STATE_MISMATCH = "oidc_state_mismatch"
    ROLE_INSUFFICIENT = "role_insufficient"
    BREAK_GLASS_EXPIRED = "break_glass_expired"
    METHOD_UNAVAILABLE = "method_unavailable"
    METHOD_NOT_ENABLED = "method_not_enabled"
    CHALLENGE_NOT_FOUND = "challenge_not_found"
    CHALLENGE_EXPIRED = "challenge_expired"
    CHALLENGE_CONSUMED = "challenge_consumed"
    CODE_INVALID = "code_invalid"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    UNKNOWN_USER = "unknown_user"
    PASSKEY_VERIFICATION_FAILED = "passkey_verification_failed"
    SECOND_FACTOR_REQUIRED = "second_factor_required"
    SECOND_FACTOR_INVALID = "second_factor_invalid"
    TWO_FACTOR_POLICY_FLOOR = "two_factor_policy_floor"
    STEP_UP_REQUIRED = "step_up_required"
    REASON_REQUIRED = "reason_required"
    DURATION_NOT_ALLOWED = "duration_not_allowed"
    CSRF_TOKEN_INVALID = "csrf_token_invalid"


@dataclass(frozen=True)
class User:
    user_id: str
    role: Role
    email: str
    phone_number: str | None = None
    sso_provider: str | None = None
    #: The IdP's stable subject identifier. **This, not `email`, is the identity key**
    #: (deep-dive §4.2): an IdP-side email change must not silently become a different user.
    sso_subject: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class PasskeyCredential:
    credential_id: str
    user_id: str
    public_key: bytes
    created_at: datetime = field(default_factory=utcnow)
    #: WebAuthn's own replay counter. Stored because a *decreasing* counter is the standard
    #: cloned-authenticator signal; not in the deep-dive's sketch, added because verifying
    #: without it discards the one anti-cloning signal the ceremony actually provides.
    sign_count: int = 0


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: str
    #: Deep-dive §5.3: a *snapshot* taken at creation, not a live join against `users`. Any
    #: role change must therefore revoke that user's sessions — which is why
    #: `roles/role_check.py` makes the revoker a required argument rather than a convention.
    role: Role
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    #: When §4.5's step-up re-authentication was last satisfied on this session. `None`
    #: means never; freshness is judged against the caller's own max-age, not stored here.
    step_up_at: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return self.revoked_at is None and self.expires_at > now


@dataclass(frozen=True)
class IssuedSession:
    """A session plus the CSRF synchronizer token issued alongside it (deep-dive §5.4).

    The token is deliberately not a field on `Session`: it is handed to the client once at
    issue time and compared against on mutating requests, and keeping it off the type every
    consumer passes around means it is not casually logged with the rest of the session.
    """

    session: Session
    csrf_token: str


@dataclass(frozen=True)
class BreakGlassGrant:
    grant_id: str
    staff_user_id: str
    target_client_user_id: str
    #: Required and non-empty, enforced in `break_glass/grant.py` rather than left to
    #: caller discipline. Free text; optionally a Support Ticketing ID, never required to be.
    reason: str
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        return self.revoked_at is None and self.expires_at > now


@dataclass(frozen=True)
class TwoFactorConfig:
    user_id: str
    enabled: bool
    method: str | None = None  # "totp" | "sms" | "email"


@dataclass(frozen=True)
class AuthChallenge:
    """What a provider hands back from `initiate()`.

    `parameters` carries whatever that specific method needs the client to act on — an OIDC
    redirect URL, a WebAuthn options blob, the channel an OTP went to. It is a `FrozenDict`
    rather than a per-method subclass because the key set is genuinely method-specific and
    pinning it into the type would put a second copy of each provider's wire format here.

    `error` is populated (and `challenge_id` left empty) when a method could not even start
    — an unreachable SMS gateway, a disabled method. That is errors-as-data: no challenge
    means no session, so a caller ignoring it cannot end up authenticated.
    """

    challenge_id: str
    method: AuthMethod
    purpose: ChallengePurpose = ChallengePurpose.LOGIN
    user_id: str | None = None
    expires_at: datetime | None = None
    parameters: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error: AuthError | None = None
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.challenge_id)

    @classmethod
    def failure(
        cls,
        method: AuthMethod,
        error: AuthError,
        detail: str = "",
        purpose: ChallengePurpose = ChallengePurpose.LOGIN,
    ) -> AuthChallenge:
        return cls(
            challenge_id="", method=method, purpose=purpose, error=error, error_detail=detail
        )


@dataclass(frozen=True)
class AuthResult:
    """What a provider hands back from `verify()`. Never a session — issuing one is the
    service's job, after the second-factor gate has had its say."""

    authenticated: bool
    method: AuthMethod
    purpose: ChallengePurpose = ChallengePurpose.LOGIN
    user_id: str | None = None
    claims: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error: AuthError | None = None
    error_detail: str = ""

    @classmethod
    def failure(
        cls,
        method: AuthMethod,
        error: AuthError,
        detail: str = "",
        purpose: ChallengePurpose = ChallengePurpose.LOGIN,
    ) -> AuthResult:
        return cls(
            authenticated=False, method=method, purpose=purpose, error=error,
            error_detail=detail,
        )


@dataclass(frozen=True)
class MethodAvailability:
    """One row of the login screen. `available=False` hides that option and nothing else
    (`docs/PRINCIPLES.md` §4.4) — a dead SMS gateway is not a broken login page."""

    method: AuthMethod
    enabled: bool
    available: bool
    detail: str = ""

    @property
    def offerable(self) -> bool:
        return self.enabled and self.available


@dataclass(frozen=True)
class InstallProfile:
    """The resolved shape of this install, read once from config rather than re-derived per
    login (deep-dive §4.6.1's own note about keeping the hot path dependency-free)."""

    tenancy_mode: TenancyMode
    public_facing: bool
    two_factor_policy: TwoFactorPolicy
    session_ttl_hours: int
    methods_enabled: tuple[AuthMethod, ...]
    otp_code_length: int = 6
    otp_ttl_seconds: int = 300
    totp_issuer_name: str = "DOMTRI"
    break_glass_default_minutes: int = 60
    break_glass_max_minutes: int = 480
    csrf_protection: str = "synchronizer_token"
    passkey_rp_id: str = ""

    @property
    def short_circuited(self) -> bool:
        """`single` mode does not run this API's multi-tenant machinery at all (§6.2)."""
        return self.tenancy_mode is TenancyMode.SINGLE


__all__ = [
    "AuthChallenge", "AuthError", "AuthMethod", "AuthResult", "BreakGlassGrant",
    "ChallengePurpose", "InstallProfile", "IssuedSession", "MethodAvailability",
    "PasskeyCredential", "Role", "Session", "TenancyMode", "TwoFactorConfig",
    "TwoFactorPolicy", "User", "utcnow",
]
