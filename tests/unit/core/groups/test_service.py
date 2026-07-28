"""`GroupsServicer` — the gRPC translation layer (`v3-deepdive-41-groups.md` §9).

Thin by design, exactly as `core/logs/service.py` and `core/health/service.py` are: every
real decision lives in `permission_gate.py`, `membership.py`, and `effective_group.py`, so
these tests mostly assert the servicer faithfully wires the wire request into the right
authorization call and passes the result back — plus the one property that would be easy to
break silently: the surface really is exactly the six RPCs the deep-dive's §9 names, no more.
"""

from __future__ import annotations

import pytest

from core.groups.service import DEFAULT_ADDRESS, GroupsServicer
from core.groups.store import GroupsStore

from .conftest import FakeSessionResolver, make_session, run
from core.auth.contracts import Role

pb = pytest.importorskip(
    "core.groups.generated.groups_pb2",
    reason="grpcio/protobuf has no wheel on this interpreter yet (docs/MAINTENANCE.md §3)",
)


@pytest.fixture
def resolver() -> FakeSessionResolver:
    r = FakeSessionResolver()
    r.add(make_session("owner_1", Role.OWNER, "sess_owner"))
    r.add(make_session("staff_1", Role.STAFF, "sess_staff"))
    r.add(make_session("client_1", Role.CLIENT, "sess_client"))
    return r


@pytest.fixture
def audit_calls():
    return []


@pytest.fixture
def servicer(store: GroupsStore, resolver: FakeSessionResolver, audit_calls):
    async def fake_audit(operation, actor_user_id, **kwargs):
        audit_calls.append((operation, actor_user_id, kwargs))

    return GroupsServicer(store, resolver=resolver, audit=fake_audit)


def test_create_group_by_owner_succeeds(servicer: GroupsServicer):
    response = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )

    assert response.group.name == "Team A"
    assert response.group.group_id
    assert response.error_code == ""


def test_create_group_by_client_is_denied_as_data_not_a_raise(servicer: GroupsServicer):
    response = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_client", name="Team A"), None)
    )

    assert response.group.group_id == ""
    assert response.error_code == "PERMISSION_DENIED"


def test_add_and_remove_member_round_trip(servicer: GroupsServicer):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id

    added = run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )
    assert added.membership.user_id == "client_1"

    removed = run(
        servicer.RemoveGroupMember(
            pb.RemoveMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )
    assert removed.removed is True


def test_add_member_by_client_is_denied(servicer: GroupsServicer):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id

    response = run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_client", group_id=gid, user_id="client_1"),
            None,
        )
    )

    assert response.error_code == "PERMISSION_DENIED"


def test_set_group_manager_records_an_audit_entry(servicer: GroupsServicer, audit_calls):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id
    run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )

    response = run(
        servicer.SetGroupManager(
            pb.SetManagerRequest(
                session_id="sess_owner", group_id=gid, user_id="client_1",
                is_group_manager=True, reason="promoted",
            ),
            None,
        )
    )

    assert response.membership.is_group_manager is True
    assert len(audit_calls) == 1
    assert audit_calls[0][0] == "is_group_manager_toggle"


def test_set_group_manager_by_staff_is_allowed_by_client_is_not(servicer: GroupsServicer):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id
    run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )

    denied = run(
        servicer.SetGroupManager(
            pb.SetManagerRequest(
                session_id="sess_client", group_id=gid, user_id="client_1",
                is_group_manager=True,
            ),
            None,
        )
    )
    assert denied.error_code == "PERMISSION_DENIED"

    allowed = run(
        servicer.SetGroupManager(
            pb.SetManagerRequest(
                session_id="sess_staff", group_id=gid, user_id="client_1",
                is_group_manager=True,
            ),
            None,
        )
    )
    assert allowed.membership.is_group_manager is True


def test_get_effective_group_defaults_to_the_caller_themself(servicer: GroupsServicer):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id
    run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )

    response = run(
        servicer.GetEffectiveGroup(pb.EffectiveGroupRequest(session_id="sess_client"), None)
    )

    assert response.has_group is True
    assert response.group_id == gid


def test_get_effective_group_for_a_user_in_no_group_reports_has_group_false(
    servicer: GroupsServicer,
):
    response = run(
        servicer.GetEffectiveGroup(pb.EffectiveGroupRequest(session_id="sess_client"), None)
    )

    assert response.has_group is False
    assert response.group_id == ""
    assert response.error_code == ""


def test_get_effective_group_for_another_user_requires_owner_or_staff(
    servicer: GroupsServicer,
):
    denied = run(
        servicer.GetEffectiveGroup(
            pb.EffectiveGroupRequest(session_id="sess_client", user_id="someone_else"), None
        )
    )
    assert denied.error_code == "PERMISSION_DENIED"

    allowed = run(
        servicer.GetEffectiveGroup(
            pb.EffectiveGroupRequest(session_id="sess_owner", user_id="client_1"), None
        )
    )
    assert allowed.error_code == ""


def test_list_group_members_is_gated_the_same_as_visibility(servicer: GroupsServicer):
    created = run(
        servicer.CreateGroup(pb.CreateGroupRequest(session_id="sess_owner", name="Team A"), None)
    )
    gid = created.group.group_id
    run(
        servicer.AddGroupMember(
            pb.AddMemberRequest(session_id="sess_owner", group_id=gid, user_id="client_1"),
            None,
        )
    )

    denied = run(
        servicer.ListGroupMembers(
            pb.ListMembersRequest(session_id="sess_client", group_id=gid), None
        )
    )
    assert denied.error_code == "PERMISSION_DENIED"

    allowed = run(
        servicer.ListGroupMembers(
            pb.ListMembersRequest(session_id="sess_owner", group_id=gid), None
        )
    )
    assert [m.user_id for m in allowed.members] == ["client_1"]


def test_the_grpc_surface_is_exactly_the_six_rpcs_the_deep_dive_names():
    """§9, asserted against the generated descriptor rather than the Python class, so an
    added or removed RPC fails here even before anyone implements or removes it."""
    from core.groups.generated import groups_pb2_grpc as pb_grpc

    methods = [m for m in dir(pb_grpc.GroupsServiceServicer) if not m.startswith("_")]

    assert sorted(methods) == [
        "AddGroupMember",
        "CreateGroup",
        "GetEffectiveGroup",
        "ListGroupMembers",
        "RemoveGroupMember",
        "SetGroupManager",
    ]


def test_module_stays_importable_without_touching_grpc_at_import_time():
    """`core/logs/service.py`'s own discipline, matched here: the generated stubs are
    imported lazily inside methods and inside `serve()`, so this package stays importable on
    an interpreter with no `grpcio` wheel yet."""
    import core.groups.service as service_module

    assert hasattr(service_module, "GroupsServicer")
    assert DEFAULT_ADDRESS.startswith("127.0.0.1:")
