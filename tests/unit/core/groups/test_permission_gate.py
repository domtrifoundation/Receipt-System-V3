"""`PermissionGate` — the fail-closed session gate (`v3-deepdive-41-groups.md` §4.1, §7).

This is the one file in this package that is deliberately *not* graceful
(`docs/PRINCIPLES.md` §4.2): every test here is either a genuine grant or a denial, and there
is no third outcome. §7's own testing hook — "a live re-check test confirms a `search_group()`
call made immediately after a membership removal correctly loses access" — is
`test_revoking_manager_status_denies_the_very_next_call` below.
"""

from __future__ import annotations

from core.groups.membership import GroupMembershipService
from core.groups.permission_gate import PermissionGate
from core.groups.store import GroupsStore

from .conftest import RaisingResolver, run


# ------------------------------------------------------------------- admin gate


def test_owner_is_authorized_for_admin_actions(gate: PermissionGate, owner_session):
    result = run(gate.authorize_admin(owner_session.session_id))

    assert result.allowed
    assert result.user_id == "owner_1"


def test_staff_is_authorized_for_admin_actions(gate: PermissionGate, staff_session):
    result = run(gate.authorize_admin(staff_session.session_id))

    assert result.allowed


def test_client_is_denied_admin_actions(gate: PermissionGate, client_session):
    result = run(gate.authorize_admin(client_session.session_id))

    assert not result.allowed
    assert result.error_code == "PERMISSION_DENIED"
    assert result.user_id == "client_1"  # the session still resolved; only the role failed


def test_an_unresolvable_session_is_denied_never_permitted(gate: PermissionGate):
    """§4.2: an unknown session is `None` from the resolver, and that must deny — there is no
    default-permit branch anywhere in this gate."""
    result = run(gate.authorize_admin("no-such-session"))

    assert not result.allowed
    assert result.error_code == "SESSION_UNRESOLVABLE"
    assert result.user_id is None


def test_a_resolver_that_raises_is_treated_as_unresolvable_not_a_crash(store: GroupsStore):
    """"Cannot tell" and "not permitted" must produce the identical answer
    (`docs/PRINCIPLES.md` §4.2) — a transport failure talking to Auth must never let a call
    through, and must never propagate as an exception across this API's own boundary either."""
    gate = PermissionGate(RaisingResolver(), store=store)

    result = run(gate.authorize_admin("anything"))

    assert not result.allowed
    assert result.error_code == "SESSION_UNRESOLVABLE"


def test_no_resolver_at_all_denies_everything_by_default(store: GroupsStore):
    """The fail-closed default (`DenyAllSessions`), not a placeholder to be swapped for
    something permissive — a Groups process wired up with no real Auth client yet must serve
    no gated call at all, the correct behaviour rather than a degraded one."""
    gate = PermissionGate(store=store)

    result = run(gate.authorize_admin("anything"))

    assert not result.allowed
    assert result.error_code == "SESSION_UNRESOLVABLE"


# ------------------------------------------------------------ group visibility, §4.1/§7


def test_owner_sees_any_group_without_being_a_member(gate: PermissionGate, owner_session):
    result = run(gate.authorize_group_visibility(owner_session.session_id, "grp_never_joined"))

    assert result.allowed


def test_an_ordinary_member_without_manager_status_is_denied_visibility(
    gate: PermissionGate, client_session, membership: GroupMembershipService,
):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))  # not a manager

    result = run(gate.authorize_group_visibility(client_session.session_id, group.group_id))

    assert not result.allowed
    assert result.error_code == "PERMISSION_DENIED"


def test_a_non_member_is_denied_visibility(gate: PermissionGate, client_session):
    result = run(gate.authorize_group_visibility(client_session.session_id, "grp_1"))

    assert not result.allowed


def test_the_groups_own_manager_is_granted_visibility(
    gate: PermissionGate, client_session, membership: GroupMembershipService,
):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(
        membership.add_member(
            group.group_id, "client_1", "owner_1", is_group_manager=True
        )
    )

    result = run(gate.authorize_group_visibility(client_session.session_id, group.group_id))

    assert result.allowed


def test_a_manager_of_one_group_is_not_granted_visibility_into_another(
    gate: PermissionGate, client_session, membership: GroupMembershipService,
):
    """§4.1: "not the whole instance, not other groups" — the concrete boundary test."""
    own_group = run(membership.create_group("Team A", "owner_1")).group
    other_group = run(membership.create_group("Team B", "owner_1")).group
    run(
        membership.add_member(
            own_group.group_id, "client_1", "owner_1", is_group_manager=True
        )
    )

    result = run(
        gate.authorize_group_visibility(client_session.session_id, other_group.group_id)
    )

    assert not result.allowed


def test_revoking_manager_status_denies_the_very_next_call(
    gate: PermissionGate, client_session, membership: GroupMembershipService,
):
    """The deep-dive's own §7 named testing hook, verbatim: a `search_group`-shaped call made
    immediately after a membership change must already see the new state. No caching layer,
    no expiry timer — "persistent and structural doesn't mean never re-checked"."""
    group = run(membership.create_group("Team A", "owner_1")).group
    run(
        membership.add_member(
            group.group_id, "client_1", "owner_1", is_group_manager=True
        )
    )
    before = run(gate.authorize_group_visibility(client_session.session_id, group.group_id))
    assert before.allowed

    run(
        membership.set_group_manager(
            group.group_id, "client_1", False, actor_user_id="owner_1"
        )
    )
    after = run(gate.authorize_group_visibility(client_session.session_id, group.group_id))

    assert not after.allowed


def test_is_group_manager_reflects_live_state_directly(
    gate: PermissionGate, membership: GroupMembershipService,
):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))

    assert run(gate.is_group_manager(group.group_id, "client_1")) is False

    run(
        membership.set_group_manager(
            group.group_id, "client_1", True, actor_user_id="owner_1"
        )
    )

    assert run(gate.is_group_manager(group.group_id, "client_1")) is True


def test_is_group_manager_is_false_for_a_user_who_was_never_a_member(gate: PermissionGate):
    assert run(gate.is_group_manager("grp_1", "nobody")) is False


# --------------------------------------------------------------- effective-group self-scope


def test_a_caller_may_read_their_own_effective_group(gate: PermissionGate, client_session):
    result = run(
        gate.authorize_effective_group(client_session.session_id, "client_1")
    )

    assert result.allowed


def test_an_empty_subject_means_myself(gate: PermissionGate, client_session):
    result = run(gate.authorize_effective_group(client_session.session_id, None))

    assert result.allowed
    assert result.user_id == "client_1"


def test_a_client_may_not_read_someone_elses_effective_group(
    gate: PermissionGate, client_session,
):
    result = run(
        gate.authorize_effective_group(client_session.session_id, "someone_else")
    )

    assert not result.allowed
    assert result.error_code == "PERMISSION_DENIED"


def test_owner_may_read_anyones_effective_group(gate: PermissionGate, owner_session):
    result = run(
        gate.authorize_effective_group(owner_session.session_id, "some_client")
    )

    assert result.allowed
