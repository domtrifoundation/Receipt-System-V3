"""Device/session management — a thin, user-facing view over Auth's own session store
(deep-dive §4).

This module never maintains its own copy of session state; every function here reads or
acts through a `gateways.SessionGateway`, then presents or acts on what Auth reports.

**The security-critical property this module exists to hold**: `revoke_device` never
revokes a session by id alone. It first resolves that session's *real* owner through the
gateway and compares it against the `acting_user_id` the caller authenticated as — a
mismatch is `errors.E_OWNERSHIP_DENIED`, not an attempt. Without this check, any
authenticated user who learned or guessed another user's `session_id` could log them out,
which is exactly the "one user acting on another's devices" failure this package's tests
are required to rule out (`docs/PRINCIPLES.md` §4.2 — an ambiguous ownership check fails
closed, it is never assumed permitted).

Listing degrades rather than crashes when the underlying capability is missing
(`gateways.SessionGateway.list_sessions` — see `gateways.py`'s own documented gap): a
`DeviceListResult` with `.error` set, never an exception a caller could forget to catch.
"""

from __future__ import annotations

from .contracts import DeviceListResult, DeviceSession, RevokeResult
from .errors import E_CAPABILITY_MISSING, E_DEPENDENCY_UNAVAILABLE, E_NOT_FOUND, E_OWNERSHIP_DENIED
from .gateways import AuditGateway, PROPOSED_AUDIT_OPERATIONS, SessionGateway

#: Auth's own `sessions` table (`core/auth/store.py`) has no user-agent column at all today
#: — there is nothing yet to parse "Chrome on Windows" out of. Real, current gap: a session
#: row would need Auth to start capturing a User-Agent at login before this label could be
#: anything but a placeholder. Never the raw header even once Auth adds it (deep-dive §4).
UNKNOWN_DEVICE_LABEL = "unknown device"


async def list_sessions(
    gateway: SessionGateway, user_id: str, current_session_id: str | None = None
) -> DeviceListResult:
    """Every active device/session this user holds, `is_current` marked for whichever one
    matches `current_session_id` — the same convention most account-security screens use
    (deep-dive §4)."""
    from .errors import AccountGuardianError

    try:
        raw = await gateway.list_sessions(user_id)
    except AccountGuardianError as exc:
        code = exc.code if exc.code in (E_CAPABILITY_MISSING, E_DEPENDENCY_UNAVAILABLE) else E_CAPABILITY_MISSING
        return DeviceListResult(error=code, error_detail=str(exc))

    devices = tuple(
        DeviceSession(
            session_id=r.session_id,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            user_agent_summary=UNKNOWN_DEVICE_LABEL,
            is_current=(r.session_id == current_session_id),
        )
        for r in raw
    )
    return DeviceListResult(devices=devices)


async def revoke_device(
    gateway: SessionGateway,
    audit: AuditGateway,
    acting_user_id: str,
    target_session_id: str,
) -> RevokeResult:
    """Revoke one session — the caller's own, or one of their other devices' — never
    someone else's (see this module's own docstring for why the ownership check is not
    optional)."""
    from core.auth.errors import SessionExpired, SessionInvalid

    from .errors import DependencyUnavailable

    try:
        target = await gateway.validate(target_session_id)
    except (SessionInvalid, SessionExpired) as exc:
        # A lookup of the *target* session, not the caller's own authentication — this is
        # ordinary data, not Auth's raise-loudly carve-out (that applies to resolving the
        # caller, done once at `service.py`'s own boundary before this function is reached).
        return RevokeResult(error=E_NOT_FOUND, error_detail=str(exc))

    if target.user_id != acting_user_id:
        return RevokeResult(
            error=E_OWNERSHIP_DENIED,
            error_detail=f"session {target_session_id!r} does not belong to this account",
        )

    try:
        revoked = await gateway.revoke(target_session_id)
    except DependencyUnavailable as exc:
        return RevokeResult(error=E_DEPENDENCY_UNAVAILABLE, error_detail=str(exc))

    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["device_revoked"],
        acting_user_id,
        target_user_id=acting_user_id,
        reason="user-initiated device revocation",
        details={"session_id": target_session_id},
    )
    return RevokeResult(
        revoked=revoked,
        sessions_revoked=int(revoked),
        audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


async def revoke_all_devices(
    gateway: SessionGateway, audit: AuditGateway, user_id: str
) -> RevokeResult:
    """"Log out everywhere" — always scoped to the caller's own `user_id`, so there is no
    ownership check to perform: a user can only ever request this against themselves."""
    from .errors import DependencyUnavailable

    try:
        count = await gateway.revoke_all_for_user(user_id)
    except DependencyUnavailable as exc:
        return RevokeResult(error=E_DEPENDENCY_UNAVAILABLE, error_detail=str(exc))

    outcome = await audit.record(
        PROPOSED_AUDIT_OPERATIONS["all_devices_revoked"],
        user_id,
        target_user_id=user_id,
        reason="user-initiated log-out-everywhere",
        details={"sessions_revoked": count},
    )
    return RevokeResult(
        revoked=count > 0,
        sessions_revoked=count,
        audit_recorded=outcome.recorded,
        audit_error=outcome.error_detail if not outcome.recorded else "",
    )


__all__ = ["UNKNOWN_DEVICE_LABEL", "list_sessions", "revoke_all_devices", "revoke_device"]
