"""Install-shape resolution: tenancy mode, 2FA policy, session TTL (deep-dive §6.2, §4.6.1, §12).

Everything here answers the same question — *what kind of install is this* — and every
answer downstream depends on it. Three resolutions live together because they share one
input pair (`tenancy_mode`, `public_facing`) and would otherwise be re-derived, differently,
in three places:

1. **Tenancy mode** decides whether this API's machinery runs at all.
2. **2FA policy** is install-type dependent by design, not one project-wide default. A
   closed internal deployment and a public multi-tenant service carry genuinely different
   stakes for the same "must staff use a second factor" question.
3. **Session TTL** follows the same reasoning: 30 days normally, 7 on a publicly exposed
   install, because a public install carries higher per-session exposure.

The floor in `policy_floor()` is the part worth reading carefully. On a publicly exposed
multi-tenant install the policy may be raised but **never lowered** below
`REQUIRED_FOR_ELEVATED` while `public_facing` stays true. That is a deliberate floor, not a
default an owner can talk themselves out of — what is at risk on a compromised staff account
is other people's financial records, not the account holder's own.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from common.frozen_dict import FrozenDict

from .contracts import (
    AuthMethod,
    InstallProfile,
    Role,
    Session,
    TenancyMode,
    TwoFactorPolicy,
    utcnow,
)
from .errors import SingleTenantShortCircuit, TwoFactorPolicyFloor

#: Ordering for "may be raised, never lowered". A module-level table nothing should ever
#: write, so it is a `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1) — under free-threading a
#: shared mutable lookup table read across real threads is a genuine race hazard, which is
#: where that principle and the immutability one turn out to be the same requirement.
POLICY_RANK: FrozenDict = FrozenDict({
    TwoFactorPolicy.OPTIONAL: 0,
    TwoFactorPolicy.REQUIRED_FOR_ELEVATED: 1,
    TwoFactorPolicy.REQUIRED_FOR_ALL: 2,
})

#: What `ttl_hours: auto` resolves to (deep-dive §12). Both are config-overridable; these
#: are the meaning of "auto", not a ceiling.
SESSION_TTL_HOURS: FrozenDict = FrozenDict({
    "default": 720,        # 30 days
    "public_facing": 168,  # 7 days
})

#: The implicit sole user of a `single`-tenant install. Setup API's first-run wizard creates
#: the real row; this is the id it uses, named here so both sides agree on one value.
IMPLICIT_OWNER_USER_ID = "owner"
SINGLE_MODE_SESSION_ID = "single-tenant-implicit"


def policy_floor(mode: TenancyMode, public_facing: bool) -> TwoFactorPolicy:
    """The lowest policy this install is permitted to hold (§4.6.1)."""
    if mode is TenancyMode.MULTI and public_facing:
        return TwoFactorPolicy.REQUIRED_FOR_ELEVATED
    return TwoFactorPolicy.OPTIONAL


def enforce_policy_floor(
    policy: TwoFactorPolicy, mode: TenancyMode, public_facing: bool
) -> TwoFactorPolicy:
    """Raise if `policy` sits below this install's floor. Returns it unchanged otherwise."""
    floor = policy_floor(mode, public_facing)
    if POLICY_RANK[policy] < POLICY_RANK[floor]:
        raise TwoFactorPolicyFloor(
            f"two-factor policy {policy.value!r} is below the {floor.value!r} floor a "
            f"publicly exposed multi-tenant install enforces; this can only be lowered by "
            f"the install genuinely ceasing to be publicly reachable, not by config alone"
        )
    return policy


def resolve_two_factor_policy(
    mode: TenancyMode, public_facing: bool, configured: str | None = None
) -> TwoFactorPolicy:
    """`auto` (or unset) resolves per install type; an explicit value overrides — upward.

    An explicit value below the floor is neither silently accepted nor silently corrected:
    `enforce_policy_floor` raises on it. Quietly raising a value an owner explicitly set
    would be the "never silently override a genuine conflict" failure (`docs/PRINCIPLES.md`
    §4.3) pointed the other way — the owner is told, not overruled behind their back.
    """
    if configured in (None, "", "auto"):
        return policy_floor(mode, public_facing)
    policy = TwoFactorPolicy(configured)
    enforce_policy_floor(policy, mode, public_facing)
    return policy


def resolve_session_ttl_hours(public_facing: bool, configured: object = None) -> int:
    """`auto` resolves per §12; an explicit positive integer always wins."""
    if configured in (None, "", "auto"):
        return int(SESSION_TTL_HOURS["public_facing" if public_facing else "default"])
    hours = int(configured)  # type: ignore[arg-type]
    if hours <= 0:
        raise ValueError("session ttl_hours must be positive")
    return hours


def two_factor_required(policy: TwoFactorPolicy, role: Role) -> bool:
    """Whether a login by `role` may not complete without a second factor."""
    if policy is TwoFactorPolicy.REQUIRED_FOR_ALL:
        return True
    if policy is TwoFactorPolicy.REQUIRED_FOR_ELEVATED:
        return role in (Role.OWNER, Role.STAFF)
    return False


def _methods(value: object) -> tuple[AuthMethod, ...]:
    if value is None:
        return tuple(AuthMethod)
    return tuple(AuthMethod(str(m)) for m in value)  # type: ignore[union-attr]


def _submapping(cfg: Mapping, key: str) -> Mapping:
    value = cfg.get(key)
    return value if isinstance(value, Mapping) else {}


def resolve_profile(config: Mapping | None = None) -> InstallProfile:
    """Build the `InstallProfile` from the §10 config surface.

    `config` is the `auth:` subtree as a mapping. **Every membership test here is against
    `collections.abc.Mapping`, never `dict`** — a `FrozenDict` config tree on Python 3.15+
    is not a `dict` subclass, so an `isinstance(x, dict)` check would silently take the "no
    config" branch and hand back defaults on a fully configured install
    (`docs/PRINCIPLES.md` §2.1). That is the exact silent-wrong-branch failure the shim's
    own docstring warns about, and config resolution is where it would hurt most.
    """
    cfg: Mapping = config if isinstance(config, Mapping) else {}
    mode = TenancyMode(str(cfg.get("tenancy_mode", "multi")))
    public_facing = bool(cfg.get("public_facing", False))

    two_factor = _submapping(cfg, "two_factor")
    session = _submapping(cfg, "session")
    otp = _submapping(cfg, "otp")
    passkey = _submapping(cfg, "passkey")
    break_glass = _submapping(cfg, "break_glass")

    return InstallProfile(
        tenancy_mode=mode,
        public_facing=public_facing,
        two_factor_policy=resolve_two_factor_policy(
            mode, public_facing, two_factor.get("policy")
        ),
        session_ttl_hours=resolve_session_ttl_hours(public_facing, session.get("ttl_hours")),
        methods_enabled=_methods(cfg.get("methods_enabled")),
        otp_code_length=int(otp.get("code_length", 6)),
        otp_ttl_seconds=int(otp.get("ttl_seconds", 300)),
        totp_issuer_name=str(two_factor.get("totp_issuer_name", "DOMTRI")),
        break_glass_default_minutes=int(break_glass.get("default_duration_minutes", 60)),
        break_glass_max_minutes=int(break_glass.get("max_duration_minutes", 480)),
        csrf_protection=str(session.get("csrf_protection", "synchronizer_token")),
        passkey_rp_id=str(passkey.get("rp_id", "")),
    )


def assert_multi_tenant(profile: InstallProfile, what: str) -> None:
    """Guard at the entrance to any multi-tenant-only code path (§6.2).

    A self-hosted single user should never see OIDC machinery attempt to run at all — not
    see it run and quietly succeed against a hardcoded identity. Callers check
    `profile.short_circuited` and take the implicit-owner path instead; this exists so a
    caller that forgets fails loudly rather than drifting into the behaviour §6.2 is
    written specifically to prevent.
    """
    if profile.short_circuited:
        raise SingleTenantShortCircuit(
            f"{what} is multi-tenant machinery and this install is tenancy_mode: single"
        )


def implicit_owner_session(profile: InstallProfile, user_id: str | None = None) -> Session:
    """The trivially-authenticated session a `single`-tenant install uses.

    Not persisted, not revocable, and not issued through `SessionStore` — there is nothing
    to revoke on an install with one implicit user and no login at all. Returning a real
    `Session` means every consumer downstream (Gateway, Persistence) reads one shape
    regardless of install type, with no single-tenant special case of its own.
    """
    now = utcnow()
    return Session(
        session_id=SINGLE_MODE_SESSION_ID,
        user_id=user_id or IMPLICIT_OWNER_USER_ID,
        role=Role.OWNER,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=profile.session_ttl_hours),
    )


__all__ = [
    "IMPLICIT_OWNER_USER_ID", "POLICY_RANK", "SESSION_TTL_HOURS", "SINGLE_MODE_SESSION_ID",
    "assert_multi_tenant", "enforce_policy_floor", "implicit_owner_session", "policy_floor",
    "resolve_profile", "resolve_session_ttl_hours", "resolve_two_factor_policy",
    "two_factor_required",
]
