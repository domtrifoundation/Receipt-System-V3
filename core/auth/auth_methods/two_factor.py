"""Two-factor authentication — a composable layer, not a fifth primary method (§4.6, §4.6.1).

2FA sits on top of whichever primary method a login used. A user who signs in with an email
code can additionally be required to produce a TOTP code; a user who signs in with SSO can be
required to produce an SMS code. It is modelled as orthogonal to the primary method on
purpose: 2FA is a statement about *how strict this login must be*, not another way of proving
who someone is — which is why it is absent from `AuthMethod` and lives here instead.

**Enforcement is install-type dependent** and resolved in `tenancy.py`; this module applies
the resolved policy to a specific user and login. The floor matters: on a publicly exposed
multi-tenant install, staff and owner 2FA cannot be configured back off while
`public_facing` stays true. `configure()` refuses that rather than accepting it quietly.

**TOTP is implemented against RFC 6238 with the standard library.** The deep-dive names
`pyotp` as the candidate, and this deviates from that on a narrow, deliberate basis: TOTP is
a fully specified HMAC construction of about thirty lines, and taking a dependency for it
means one more package in the Day-0 support matrix that Dependencies Warden then has to
track across every Python release. The `TotpEngine` Protocol is what keeps that reversible —
swapping to `pyotp` is a new engine class in this file and no change anywhere else
(`docs/PRINCIPLES.md` §1.3). This is flagged as a real decision, not a silent substitution.

The TOTP secret is a shared secret with the user's authenticator app, and it is the only
shared secret anywhere in this design. It is worth being explicit that this does not
reintroduce a password: it is never typed by a human, never chosen by one, never reusable
across sites, and never a primary credential — it is a second factor over an already-proven
identity.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from ..contracts import (
    AuthError,
    InstallProfile,
    Role,
    TwoFactorConfig,
    TwoFactorPolicy,
)
from ..errors import TwoFactorPolicyFloor
from ..store import UserDirectory, in_thread
from ..tenancy import enforce_policy_floor, two_factor_required

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
#: One step either side of now. Covers ordinary clock skew between a phone and a server
#: without meaningfully widening the guessing window (three valid codes out of a million,
#: against the attempt cap the challenge store already enforces).
TOTP_WINDOW = 1


class TotpEngine(Protocol):
    def generate_secret(self) -> str: ...

    def code_at(self, secret: str, moment: float) -> str: ...

    def verify(self, secret: str, code: str, moment: float | None = None) -> bool: ...

    def provisioning_uri(self, secret: str, account: str, issuer: str) -> str: ...


@dataclass
class StdlibTotpEngine:
    """RFC 6238, SHA-1, 30-second steps, 6 digits — the parameters every authenticator app
    assumes by default. Changing any of them here would silently break enrolled users."""

    digits: int = TOTP_DIGITS
    period: int = TOTP_PERIOD_SECONDS
    window: int = TOTP_WINDOW

    def generate_secret(self) -> str:
        """160 bits, base32, matching the HMAC-SHA1 block the standard specifies."""
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    def _hotp(self, secret: str, counter: int) -> str:
        padding = "=" * (-len(secret) % 8)
        key = base64.b32decode(secret + padding, casefold=True)
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(truncated % (10**self.digits)).zfill(self.digits)

    def code_at(self, secret: str, moment: float) -> str:
        return self._hotp(secret, int(moment // self.period))

    def verify(self, secret: str, code: str, moment: float | None = None) -> bool:
        now = time.time() if moment is None else moment
        counter = int(now // self.period)
        candidate = (code or "").strip()
        if len(candidate) != self.digits or not candidate.isdigit():
            return False
        # Every step in the window is compared, and all comparisons run, so the loop's
        # duration does not reveal which step matched.
        matched = False
        for drift in range(-self.window, self.window + 1):
            if hmac.compare_digest(self._hotp(secret, counter + drift), candidate):
                matched = True
        return matched

    def provisioning_uri(self, secret: str, account: str, issuer: str) -> str:
        label = quote(f"{issuer}:{account}")
        return (
            f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={self.digits}&period={self.period}"
        )


@dataclass(frozen=True)
class TwoFactorDecision:
    """Whether this specific login may complete without a second factor, and which one."""

    required: bool
    configured: bool
    method: str | None = None

    @property
    def satisfiable(self) -> bool:
        """A login that requires 2FA the user has never enrolled in cannot complete.

        This is a real state, not an impossible one: raising an install to
        `REQUIRED_FOR_ELEVATED` puts every un-enrolled staff member here. Surfacing it as
        its own condition is what lets the surface send them to enrolment instead of showing
        them a code box for a code that does not exist yet.
        """
        return self.configured or not self.required


class TwoFactorGate:
    def __init__(
        self,
        directory: UserDirectory,
        profile: InstallProfile,
        engine: TotpEngine | None = None,
    ) -> None:
        self._directory = directory
        self._profile = profile
        self._engine = engine or StdlibTotpEngine()

    # --------------------------------------------------------------- policy
    def decide(self, user_id: str, role: Role) -> TwoFactorDecision:
        config = self._directory.get_two_factor(user_id)
        required = two_factor_required(self._profile.two_factor_policy, role)
        # A user who has enrolled voluntarily is held to it even where policy is OPTIONAL —
        # opting in and then having it silently skipped would be worse than not offering it.
        return TwoFactorDecision(
            required=required or config.enabled,
            configured=config.enabled,
            method=config.method,
        )

    def configure(
        self, user_id: str, role: Role, enabled: bool, method: str | None
    ) -> TwoFactorConfig:
        """Change a user's 2FA setting, refusing anything the policy floor forbids.

        Raises `TwoFactorPolicyFloor` — a rejected configuration change, deliberately not an
        `AuthFailure`, since nothing about the caller's authentication failed (`errors.py`).
        The service layer additionally requires a fresh step-up before reaching here, because
        disabling a second factor is exactly the sensitive action §4.5 exists for.
        """
        if not enabled and two_factor_required(self._profile.two_factor_policy, role):
            raise TwoFactorPolicyFloor(
                f"two-factor authentication cannot be disabled for role {role.value!r} "
                f"under policy {self._profile.two_factor_policy.value!r}"
            )
        if enabled and method not in ("totp", "sms", "email"):
            raise ValueError(f"unsupported second-factor method {method!r}")
        config = TwoFactorConfig(user_id=user_id, enabled=enabled, method=method)
        self._directory.set_two_factor(config)
        return config

    def set_policy(self, policy: TwoFactorPolicy) -> InstallProfile:
        """Owner-facing policy change, clamped by §4.6.1's floor.

        Returns a new `InstallProfile` rather than mutating one — the profile is a frozen
        contract, and a policy change is a new resolved install shape, not an edit to the
        old one.
        """
        enforce_policy_floor(
            policy, self._profile.tenancy_mode, self._profile.public_facing
        )
        from dataclasses import replace  # noqa: PLC0415

        self._profile = replace(self._profile, two_factor_policy=policy)
        return self._profile

    # ----------------------------------------------------------- enrolment
    async def begin_totp_enrolment(self, user_id: str, account_label: str) -> tuple[str, str]:
        """`(secret, provisioning_uri)`. The secret is stored disabled until a first code is
        verified — enrolling on an unverified secret is how a user locks themselves out."""
        secret = self._engine.generate_secret()
        await in_thread(
            self._directory.set_two_factor,
            TwoFactorConfig(user_id=user_id, enabled=False, method="totp"),
            secret,
        )
        return secret, self._engine.provisioning_uri(
            secret, account_label, self._profile.totp_issuer_name
        )

    async def confirm_totp_enrolment(self, user_id: str, code: str) -> bool:
        secret = await in_thread(self._directory.get_totp_secret, user_id)
        if not secret or not self._engine.verify(secret, code):
            return False
        await in_thread(
            self._directory.set_two_factor,
            TwoFactorConfig(user_id=user_id, enabled=True, method="totp"),
        )
        return True

    # ----------------------------------------------------------- the gate
    async def verify_second_factor(self, user_id: str, code: str) -> AuthError | None:
        """`None` when satisfied, otherwise the error that refuses the login.

        Errors-as-data: a failed second factor produces no session, so this follows the
        ordinary convention rather than the raising carve-out (`errors.py`).
        """
        config = await in_thread(self._directory.get_two_factor, user_id)
        if not config.enabled:
            return AuthError.SECOND_FACTOR_REQUIRED
        if config.method == "totp":
            secret = await in_thread(self._directory.get_totp_secret, user_id)
            if not secret:
                return AuthError.SECOND_FACTOR_REQUIRED
            ok = await in_thread(self._engine.verify, secret, code)
            return None if ok else AuthError.SECOND_FACTOR_INVALID
        # sms/email second factors are redeemed through their own OTP provider, which the
        # service layer routes to. Reaching here with one of those means the caller took the
        # wrong path, and refusing is the safe answer.
        return AuthError.SECOND_FACTOR_INVALID


__all__ = [
    "TOTP_DIGITS", "TOTP_PERIOD_SECONDS", "TOTP_WINDOW", "StdlibTotpEngine", "TotpEngine",
    "TwoFactorDecision", "TwoFactorGate",
]
