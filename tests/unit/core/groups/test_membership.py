"""`GroupMembershipService` — create/add/remove/manager-toggle (`v3-deepdive-41-groups.md`
§3-§4, §11).

This module does not decide *who* may call it — `permission_gate.py` does, exercised
separately in `test_permission_gate.py`. These tests exercise "given the call is authorized,
what actually happens", including §11's own resolved open question: flipping
`is_group_manager` produces an Audit entry, and a missing or failing Audit recorder degrades
rather than undoing the toggle that already happened (`docs/PRINCIPLES.md` §4.4).
"""

from __future__ import annotations

import pytest

from core.groups.membership import GROUP_MANAGER_TOGGLE_OPERATION, GroupMembershipService

from .conftest import run


# --------------------------------------------------------------------- groups


def test_create_group_succeeds_with_a_real_name(membership: GroupMembershipService):
    result = run(membership.create_group("Team A", "owner_1"))

    assert result.ok
    assert result.group.name == "Team A"
    assert result.group.created_by == "owner_1"
    assert result.group.group_id


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_group_rejects_an_empty_name(membership: GroupMembershipService, name):
    result = run(membership.create_group(name, "owner_1"))

    assert not result.ok
    assert result.error_code == "INVALID_GROUP_NAME"


def test_create_group_strips_surrounding_whitespace(membership: GroupMembershipService):
    result = run(membership.create_group("  Team A  ", "owner_1"))

    assert result.group.name == "Team A"


# ---------------------------------------------------------------- membership


def test_add_member_to_an_unknown_group_is_an_error(membership: GroupMembershipService):
    result = run(membership.add_member("grp_missing", "client_1", "owner_1"))

    assert not result.ok
    assert result.error_code == "GROUP_NOT_FOUND"


def test_add_member_succeeds_and_records_who_added_them(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group

    result = run(membership.add_member(group.group_id, "client_1", "owner_1"))

    assert result.ok
    assert result.membership.user_id == "client_1"
    assert result.membership.added_by == "owner_1"
    assert result.membership.is_group_manager is False


def test_adding_the_same_member_twice_is_rejected_not_silently_merged(
    membership: GroupMembershipService,
):
    """`docs/PRINCIPLES.md` §4.3: a second `AddGroupMember` for the same pair is a genuine
    question about who actually granted this visibility, never silently resolved by keeping
    whichever value happened to be first."""
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))

    result = run(membership.add_member(group.group_id, "client_1", "staff_1"))

    assert not result.ok
    assert result.error_code == "ALREADY_A_MEMBER"


def test_remove_member_who_never_joined_is_an_error(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group

    result = run(membership.remove_member(group.group_id, "never_added"))

    assert not result.ok
    assert result.error_code == "NOT_A_MEMBER"


def test_remove_member_succeeds_for_a_real_membership(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))

    result = run(membership.remove_member(group.group_id, "client_1"))

    assert result.ok
    listed = run(membership.list_members(group.group_id))
    assert listed.members == ()


# ------------------------------------------------------------------- listing


def test_list_members_of_an_unknown_group_is_an_error(membership: GroupMembershipService):
    result = run(membership.list_members("grp_missing"))

    assert not result.ok
    assert result.error_code == "GROUP_NOT_FOUND"


def test_list_members_of_a_real_empty_group_is_not_an_error(
    membership: GroupMembershipService,
):
    group = run(membership.create_group("Team A", "owner_1")).group

    result = run(membership.list_members(group.group_id))

    assert result.ok
    assert result.members == ()


def test_list_members_reflects_every_current_member(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))
    run(membership.add_member(group.group_id, "client_2", "owner_1"))

    result = run(membership.list_members(group.group_id))

    assert {m.user_id for m in result.members} == {"client_1", "client_2"}


# ------------------------------------------------------- is_group_manager toggle, §11


def test_set_group_manager_on_a_non_member_is_an_error(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group

    result = run(
        membership.set_group_manager(
            group.group_id, "never_added", True, actor_user_id="owner_1"
        )
    )

    assert not result.ok
    assert result.error_code == "NOT_A_MEMBER"


def test_set_group_manager_flips_the_flag(membership: GroupMembershipService):
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))

    result = run(
        membership.set_group_manager(
            group.group_id, "client_1", True, actor_user_id="owner_1", reason="promoted"
        )
    )

    assert result.ok
    assert result.membership.is_group_manager is True


def test_set_group_manager_with_no_audit_recorder_still_succeeds(
    membership: GroupMembershipService,
):
    """Audit is injected, never hard-imported (the same `AuditSink` shape
    `core/auth/break_glass/grant.py` uses) — a Groups process with no recorder wired up yet
    must still be able to toggle the flag; the row itself is durable evidence either way."""
    group = run(membership.create_group("Team A", "owner_1")).group
    run(membership.add_member(group.group_id, "client_1", "owner_1"))

    result = run(
        membership.set_group_manager(
            group.group_id, "client_1", True, actor_user_id="owner_1"
        )
    )

    assert result.ok


def test_set_group_manager_records_an_audit_entry_with_the_canonical_operation_name(store):
    """§11's own resolved open question, made concrete: the audit hook receives exactly the
    operation name `core.audit.contracts.PRIVILEGED_ACTIONS["is_group_manager_toggle"]` maps
    to `ActionType.GROUP_MANAGER_TOGGLED`, so the two packages' own vocabularies agree without
    either importing the other."""
    calls = []

    async def fake_audit(operation, actor_user_id, **kwargs):
        calls.append((operation, actor_user_id, kwargs))

    service = GroupMembershipService(store, audit=fake_audit)
    group = run(service.create_group("Team A", "owner_1")).group
    run(service.add_member(group.group_id, "client_1", "owner_1"))

    run(
        service.set_group_manager(
            group.group_id, "client_1", True, actor_user_id="owner_1", reason="promoted",
        )
    )

    assert len(calls) == 1
    operation, actor, kwargs = calls[0]
    assert operation == GROUP_MANAGER_TOGGLE_OPERATION == "is_group_manager_toggle"
    assert actor == "owner_1"
    assert kwargs["target_user_id"] == "client_1"
    assert kwargs["reason"] == "promoted"
    assert kwargs["details"]["group_id"] == group.group_id
    assert kwargs["details"]["is_group_manager"] is True


def test_a_failing_audit_recorder_does_not_undo_or_fail_the_toggle(store):
    """`docs/PRINCIPLES.md` §4.4: a degraded audit *notification* is not a reason to fail the
    privileged action that already happened, nor to roll it back — the membership row is
    itself durable evidence of the change."""

    async def broken_audit(*args, **kwargs):
        raise ConnectionError("Audit API is unreachable in this test")

    service = GroupMembershipService(store, audit=broken_audit)
    group = run(service.create_group("Team A", "owner_1")).group
    run(service.add_member(group.group_id, "client_1", "owner_1"))

    result = run(
        service.set_group_manager(
            group.group_id, "client_1", True, actor_user_id="owner_1"
        )
    )

    assert result.ok
    assert result.membership.is_group_manager is True


def test_audit_is_never_called_when_the_toggle_itself_fails(store):
    """A non-member naming a toggle target is not a privileged action that happened — nothing
    should be recorded for an operation that was rejected outright."""
    calls = []

    async def fake_audit(operation, actor_user_id, **kwargs):
        calls.append((operation, actor_user_id, kwargs))

    service = GroupMembershipService(store, audit=fake_audit)
    group = run(service.create_group("Team A", "owner_1")).group

    result = run(
        service.set_group_manager(
            group.group_id, "never_added", True, actor_user_id="owner_1"
        )
    )

    assert not result.ok
    assert calls == []
