"""Role checks raise, step-up is un-bypassable, and a role change always revokes sessions.

The revocation test is the §11 hook stated as "a role change that doesn't call
`revoke_all_for_user()` should fail a check, not just be a documented convention". The
enforcement mechanism chosen was the required-parameter form: `change_user_role()` cannot be
called without supplying the revoker. The last test in this file is the other half — it
asserts no second role-change path has appeared in the package.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from core.auth.contracts import Role, utcnow
from core.auth.errors import RoleInsufficient, SessionExpired, SessionInvalid, StepUpRequired
from core.auth.roles.role_check import (
    STEP_UP_MAX_AGE,
    change_user_role,
    has_role,
    require_active,
    require_at_least,
    require_role,
    require_step_up,
)
from core.auth.session.session_store import SessionStore

from ..conftest import run

PACKAGE_ROOT = Path(__file__).resolve().parents[5] / "core" / "auth"


@pytest.fixture
def sessions(db):
    return SessionStore(db, ttl_hours=720)


def _session(role: Role = Role.CLIENT, **overrides):
    now = utcnow()
    from core.auth.contracts import Session

    base = dict(
        session_id="s", user_id="u", role=role, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=1),
    )
    base.update(overrides)
    return Session(**base)


def test_require_role_raises_rather_than_returning_an_error():
    with pytest.raises(RoleInsufficient) as caught:
        require_role(_session(Role.CLIENT), Role.OWNER, Role.STAFF)
    assert caught.value.held is Role.CLIENT
    assert require_role(_session(Role.OWNER), Role.OWNER).role is Role.OWNER


def test_has_role_is_the_non_raising_form():
    assert has_role(_session(Role.STAFF), Role.STAFF, Role.OWNER)
    assert not has_role(_session(Role.CLIENT), Role.STAFF)


def test_require_at_least_uses_the_rank_ordering():
    assert require_at_least(_session(Role.OWNER), Role.STAFF)
    with pytest.raises(RoleInsufficient):
        require_at_least(_session(Role.CLIENT), Role.STAFF)


def test_require_active_rejects_revoked_and_expired_sessions():
    with pytest.raises(SessionInvalid):
        require_active(_session(revoked_at=utcnow()))
    with pytest.raises(SessionExpired):
        require_active(_session(expires_at=utcnow() - timedelta(seconds=1)))


def test_step_up_is_required_when_never_satisfied():
    with pytest.raises(StepUpRequired):
        require_step_up(_session(Role.OWNER), "disable two-factor")


def test_step_up_goes_stale():
    stale = _session(Role.OWNER, step_up_at=utcnow() - STEP_UP_MAX_AGE - timedelta(seconds=1))
    with pytest.raises(StepUpRequired):
        require_step_up(stale, "disable two-factor")
    fresh = _session(Role.OWNER, step_up_at=utcnow())
    assert require_step_up(fresh, "disable two-factor") is fresh


def test_role_change_revokes_every_live_session(sessions, directory, client_user):
    first = run(sessions.create(client_user.user_id, Role.CLIENT))
    second = run(sessions.create(client_user.user_id, Role.CLIENT))
    revoked = run(change_user_role(
        client_user.user_id, Role.STAFF,
        directory=directory, session_revoker=sessions.revoke_all_for_user,
    ))
    assert revoked == 2
    assert directory.get(client_user.user_id).role is Role.STAFF
    for issued in (first, second):
        with pytest.raises(SessionInvalid):
            run(sessions.validate(issued.session.session_id))


def test_role_change_cannot_be_called_without_a_revoker(directory, client_user):
    """The enforcement mechanism itself: the revoker is a required keyword argument, so
    there is no signature that changes a role and leaves sessions alone."""
    with pytest.raises(TypeError):
        run(change_user_role(client_user.user_id, Role.STAFF, directory=directory))


def test_set_role_has_exactly_one_caller_in_the_package():
    """The raw write must stay reachable only through `change_user_role`. A second caller
    would be a second role-change path that skips revocation — the exact drift §5.3 warns
    about, caught here rather than in a bug report."""
    callers = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "generated" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set_role"
            ):
                callers.append(path.name)
    assert callers == ["role_check.py"], f"unexpected set_role callers: {callers}"
