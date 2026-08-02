"""Role-claim verification, and the one safe way to change a user's role.

Auth's job is producing a trustworthy role claim on a session; acting on it is each
consumer's own job (deep-dive §6.1). This module is the shared helper both sides use, so
"is this session allowed here" reads identically in Gateway and in any Core API rather than
being re-expressed slightly differently in each.

**Role checks raise.** They are the second half of `docs/PRINCIPLES.md` §4.1's carve-out for
this API: a caller that forgets to check a returned `.error` on a role decision has granted
access it should not have.

**`change_user_role()` takes the session revoker as a required argument.** That is the
concrete enforcement the deep-dive's §11 asks for, in preference to a documented
convention. `Session.role` is a snapshot taken at creation (§5.3), so a demotion that does
not revoke the user's live sessions has not actually demoted anyone until they happen to log
in again — which for a staff member whose access is being *pulled* is precisely the window
that must not exist. Making the revoker a parameter means a caller cannot reach this
function without supplying the thing that closes it.

`UserDirectory.set_role()` is the raw write and is deliberately not public API. If a second
role-change path ever appears, it is a bug — `tests/unit/core/auth/roles/` asserts there is
only this one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from common.frozen_dict import FrozenDict

from ..contracts import Role, Session, utcnow
from ..errors import RoleInsufficient, SessionExpired, SessionInvalid, StepUpRequired
from ..store import UserDirectory

#: Ordering for "at least this role". Module-level constant, therefore `FrozenDict`
#: (`docs/PRINCIPLES.md` §2.1.1). Ranking is a convenience for the common
#: "staff-or-above" case; the explicit-set form (`require_role`) stays the primary API,
#: because most real checks are "one of these", not "at least this".
ROLE_RANK: FrozenDict = FrozenDict({Role.CLIENT: 0, Role.STAFF: 1, Role.OWNER: 2})

#: How long a step-up re-authentication stays fresh. Short on purpose: the point of §4.5 is
#: that the human was present *for this action*, not that they were present at some point
#: today. Not config today — a config key that could be raised to a day would quietly undo
#: the guarantee, and no real need to tune it has been established.
STEP_UP_MAX_AGE = timedelta(minutes=5)

SessionRevoker = Callable[[str], Awaitable[int]]


def has_role(session: Session, *allowed: Role) -> bool:
    """Non-raising form, for building a UI that hides what a user cannot do."""
    return session.role in allowed


def require_role(session: Session, *allowed: Role) -> Session:
    """Raise unless the session's role is one of `allowed`. Returns the session so this can
    be used inline at the top of a handler."""
    if not allowed:
        raise ValueError("require_role needs at least one permitted role")
    if session.role not in allowed:
        raise RoleInsufficient(session.role, allowed)
    return session


def require_at_least(session: Session, minimum: Role) -> Session:
    if ROLE_RANK[session.role] < ROLE_RANK[minimum]:
        raise RoleInsufficient(session.role, (minimum,))
    return session


def require_active(session: Session, now: datetime | None = None) -> Session:
    """Liveness restated at the point of use.

    `SessionStore.validate()` already does this at the transport edge. Repeating it here is
    deliberate rather than redundant: a `Session` object can outlive the request that
    fetched it (cached in a handler, passed down a call chain), and a role check performed
    against a session that expired in the meantime should fail.
    """
    now = now or utcnow()
    if session.revoked_at is not None:
        raise SessionInvalid("session was revoked")
    if session.expires_at <= now:
        raise SessionExpired("session expired")
    return session


def require_step_up(
    session: Session, action: str, max_age: timedelta = STEP_UP_MAX_AGE,
    now: datetime | None = None,
) -> Session:
    """Gate a sensitive action on a fresh re-authentication (deep-dive §4.5).

    The freshness check is against a server-side timestamp written only by
    `SessionStore.mark_step_up()`, which in turn is only reachable by redeeming a
    `ChallengePurpose.STEP_UP` challenge. That chain is what makes this un-bypassable by a
    direct API call that skips the UI prompt — the property §11's own bypass test exists to
    verify.

    The challenge is always one of the four passwordless methods. There is no password to
    "confirm with" here, and adding one would defeat the entire point of §4 — a design that
    got login right and then reintroduced a memorized secret at the confirmation step would
    have missed it exactly.
    """
    now = now or utcnow()
    if session.step_up_at is None or (now - session.step_up_at) > max_age:
        raise StepUpRequired(f"{action} requires fresh re-authentication")
    return session


async def change_user_role(
    user_id: str,
    new_role: Role,
    *,
    directory: UserDirectory,
    session_revoker: SessionRevoker,
) -> int:
    """Change a role and revoke that user's sessions, in that order, always.

    Returns the number of sessions revoked. The order matters: writing the new role first
    means a session created in the race window carries the *new* role, whereas revoking
    first would leave a window where a fresh session could still pick up the old one.
    """
    directory.set_role(user_id, new_role)
    return await session_revoker(user_id)


__all__ = [
    "ROLE_RANK", "STEP_UP_MAX_AGE", "SessionRevoker", "change_user_role", "has_role",
    "require_active", "require_at_least", "require_role", "require_step_up",
]
