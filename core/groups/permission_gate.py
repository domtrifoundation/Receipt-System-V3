"""`is_group_manager` checks and the fail-closed session gate (`v3-deepdive-41-groups.md`
§4.1, §7), consumed by `service.py` and, in-process, by Search/Query's own `search_group()`.

**The one hard requirement this file exists to satisfy**: every gated call resolves the
caller's role and identity from their *real, live session*, verified through Auth &
Tenancy — **never** a `user_id`/`role`/`group_id` the caller merely asserts in the request.
A request naming `is_group_manager=true` about itself is not evidence of anything; a session
Auth actually issued and has not revoked is. This is `docs/PRINCIPLES.md` §4.5's "structural
guarantee over a check-based one" applied as far as it can be applied here: Groups cannot make
session forgery structurally impossible the way a per-user folder boundary does, so the next
best thing is never trusting the caller for the one fact — identity — that a check-based
system is one bug away from getting wrong.

**Fails closed, deliberately, the one place in this package that is not graceful**
(`docs/PRINCIPLES.md` §4.2): an unresolvable session, a resolver that raises, or an ambiguous
membership state are all denied, never permitted. "Cannot tell" and "not permitted" must
produce the identical answer — the same posture `core/logs/query.py`'s own permission gate
documents in full.

**Persistent and structural doesn't mean never re-checked** (deep-dive §7). `is_group_manager`
is read from `store.py` on every call, with no caching layer anywhere in this file — a
membership removed a moment ago must already be reflected in the very next authorization
decision, which is the concrete property the deep-dive's own "live re-check" test names.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.auth.contracts import Role, Session

from .contracts import AuthorizationResult
from .errors import PermissionDenied, SessionUnresolvable, code_for
from .store import GroupsStore, in_thread

#: Roles with system-wide visibility already, independent of any group (§4.1) — Groups grants
#: them nothing new, it just never needs to gate them out of their own existing privileges.
_SYSTEM_WIDE_ROLES = (Role.OWNER, Role.STAFF)


@runtime_checkable
class SessionResolver(Protocol):
    """The one adapter seam onto Auth (`docs/PRINCIPLES.md` §1.3).

    Deliberately not an import of `core.auth.service` or a gRPC stub: this package holds no
    opinion about *how* a session is validated, only about what it is allowed to do once
    resolved. Keeping it a Protocol also means this gate is testable without standing up an
    Auth process, the same reason `core/logs/query.py`'s own `AccessChecker` is one.
    """

    async def resolve(self, session_id: str) -> Session | None:
        """The session Auth actually issued for `session_id`, or `None` for anything that is
        not a live, valid session right now — expired, revoked, unknown, or Auth itself
        unreachable. All four collapse to the identical `None` on purpose: this method must
        never raise, because a caller that forgets to catch an exception here is exactly the
        failure `docs/PRINCIPLES.md` §4.2 exists to close off by construction instead."""


class DenyAllSessions:
    """The fail-closed default (`docs/PRINCIPLES.md` §4.2), not a placeholder to be swapped
    for something permissive. A Groups process running before it is wired to a real Auth
    client serves no gated call at all rather than guessing — the correct behaviour, not a
    degraded one, the same posture `core/logs/query.py`'s own `DenyCrossUser` takes."""

    async def resolve(self, session_id: str) -> Session | None:
        return None


class PermissionGate:
    """Every gated entry point Groups exposes goes through exactly one of these three
    methods. `service.py` never re-derives a role or membership check of its own."""

    def __init__(self, resolver: SessionResolver | None = None, *, store: GroupsStore) -> None:
        self._resolver: SessionResolver = resolver or DenyAllSessions()
        self._store = store

    async def _resolve(self, session_id: str) -> Session | None:
        """Wraps the resolver so a misbehaving implementation that raises instead of
        returning `None` still denies rather than crashing the caller — belt and braces on
        top of the Protocol's own documented contract, not a substitute for it."""
        try:
            return await self._resolver.resolve(session_id)
        except Exception:  # noqa: BLE001 - "cannot tell" must deny, never propagate
            return None

    # -------------------------------------------------------------- system-wide
    async def authorize_admin(self, session_id: str) -> AuthorizationResult:
        """Owner/staff only: `CreateGroup`, `AddGroupMember`, `RemoveGroupMember`, and
        `SetGroupManager` (§11's own resolution — flipping `is_group_manager` is owner/staff
        only). These are organizational-structure actions, not something any group's own
        manager may do about their own group; §4.1 grants managers *visibility*, never
        membership-mutation authority."""
        session = await self._resolve(session_id)
        if session is None:
            exc = SessionUnresolvable("no active session for this caller")
            return AuthorizationResult(allowed=False, error_code=code_for(exc), error_detail=str(exc))
        if session.role not in _SYSTEM_WIDE_ROLES:
            exc = PermissionDenied(f"role {session.role.value!r} is not owner/staff")
            return AuthorizationResult(
                allowed=False, user_id=session.user_id, error_code=code_for(exc),
                error_detail=str(exc),
            )
        return AuthorizationResult(allowed=True, user_id=session.user_id)

    # ------------------------------------------------------------ group-scoped
    async def authorize_group_visibility(
        self, session_id: str, group_id: str
    ) -> AuthorizationResult:
        """§4.1/§7's rule for `ListGroupMembers` and Search/Query's own `search_group()`:
        instance owner/staff, or *that specific group's* own `is_group_manager` member —
        never system-wide, never another group's manager."""
        session = await self._resolve(session_id)
        if session is None:
            exc = SessionUnresolvable("no active session for this caller")
            return AuthorizationResult(allowed=False, error_code=code_for(exc), error_detail=str(exc))
        if session.role in _SYSTEM_WIDE_ROLES:
            return AuthorizationResult(allowed=True, user_id=session.user_id)
        if await self.is_group_manager(group_id, session.user_id):
            return AuthorizationResult(allowed=True, user_id=session.user_id)
        exc = PermissionDenied(
            f"{session.user_id!r} is not owner/staff and is not {group_id!r}'s own manager"
        )
        return AuthorizationResult(
            allowed=False, user_id=session.user_id, error_code=code_for(exc),
            error_detail=str(exc),
        )

    async def is_group_manager(self, group_id: str, user_id: str) -> bool:
        """The live, uncached fact Search/Query's own `search_group()` consumes directly once
        *it* has already resolved its own caller's session through Auth — this method takes a
        plain `user_id` rather than a session on purpose, since re-deriving a second session
        resolution here for a caller that already did one would be the "who decides vs. who
        stores" boundary blurred in the wrong direction."""
        membership = await in_thread(self._store.get_membership, group_id, user_id)
        return membership is not None and membership.is_group_manager

    # ----------------------------------------------------------------- self-scoped
    async def authorize_effective_group(
        self, session_id: str, subject_user_id: str | None
    ) -> AuthorizationResult:
        """§5's ingestion-time hook: a caller may ask for their own effective group, resolved
        from their own session, never an asserted `user_id` for anyone else — unless they are
        owner/staff, the same cross-user shape break-glass and Logs both already use.

        `subject_user_id=None` means "myself" — the wire request's own empty-string default
        (`groups.proto`'s `EffectiveGroupRequest.user_id`) — resolved against the *session's*
        user, never a client-suppliable default. `AuthorizationResult.user_id` is always the
        caller's own resolved identity on success; when `subject_user_id` was `None`, that is
        also the subject to query, so `service.py` needs no second round trip to learn it.
        """
        session = await self._resolve(session_id)
        if session is None:
            exc = SessionUnresolvable("no active session for this caller")
            return AuthorizationResult(allowed=False, error_code=code_for(exc), error_detail=str(exc))
        resolved_subject = subject_user_id or session.user_id
        if session.role in _SYSTEM_WIDE_ROLES or session.user_id == resolved_subject:
            return AuthorizationResult(allowed=True, user_id=session.user_id)
        exc = PermissionDenied(
            f"{session.user_id!r} may not read {resolved_subject!r}'s effective group"
        )
        return AuthorizationResult(
            allowed=False, user_id=session.user_id, error_code=code_for(exc),
            error_detail=str(exc),
        )


__all__ = ["DenyAllSessions", "PermissionGate", "SessionResolver"]
