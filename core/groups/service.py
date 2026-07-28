"""The `GroupsService` gRPC servicer (`v3-deepdive-41-groups.md` §9).

**Groups runs as its own process in the core service cluster** (`docs/PROCESS_TOPOLOGY.md`
§1-§2), entirely indifferent to whether any client is attached (`docs/PRINCIPLES.md` §1.7) —
Interface's TUI screen and Execution Core's own ingestion hook are both gRPC *clients* of
this service. Its data lives inside the same physical database file Auth's own process opens
(deep-dive §3, `store.py`'s own docstring), but that is a storage-placement decision, not a
process one: two independent processes hold two independent SQLite connections to one file
under WAL, the identical mechanism Persistence and Audit already use elsewhere.

The translation layer is deliberately thin, exactly as `core/logs/service.py` and
`core/audit/service.py` already are: every real decision — authorization, the audit hook, the
active-group bootstrap — belongs to `permission_gate.py`, `membership.py`, and
`effective_group.py`, so a future non-Python client and any in-process caller get identical
behaviour instead of three implementations that could drift.

**Every mutating and every group-scoped RPC is gated by `permission_gate.py` before anything
else runs.** None of them trust a `user_id`, role, or membership fact the request itself
asserts — the gate resolves the caller from `session_id` through Auth, never from the
request body (this package's own hard requirement, stated in its `CLAUDE.md`).
"""

from __future__ import annotations

from concurrent import futures

from .contracts import EffectiveGroupResult, Group, GroupMembership
from .effective_group import EffectiveGroupResolver
from .membership import AuditRecorder, GroupMembershipService
from .permission_gate import PermissionGate, SessionResolver
from .store import GroupsStore

DEFAULT_ADDRESS = "127.0.0.1:50062"


def _group_entry(pb, group: Group):
    return pb.GroupEntry(
        group_id=group.group_id, name=group.name, created_by=group.created_by,
        created_at=group.created_at.isoformat(),
    )


def _membership_entry(pb, membership: GroupMembership):
    return pb.MembershipEntry(
        group_id=membership.group_id, user_id=membership.user_id,
        is_group_manager=membership.is_group_manager,
        joined_at=membership.joined_at.isoformat(), added_by=membership.added_by,
    )


class GroupsServicer:
    """Implements `GroupsService`. Registered by name, so importing the generated stubs is
    `serve()`'s business and this class stays importable without them, matching
    `core/logs/service.py`'s own `LogsServicer`."""

    def __init__(
        self,
        store: GroupsStore,
        *,
        resolver: SessionResolver | None = None,
        audit: AuditRecorder | None = None,
    ) -> None:
        self._gate = PermissionGate(resolver, store=store)
        self._membership = GroupMembershipService(store, audit=audit)
        self._effective = EffectiveGroupResolver(store)

    async def CreateGroup(self, request, context):  # noqa: N802 - gRPC method naming
        from .generated import groups_pb2 as pb

        auth = await self._gate.authorize_admin(request.session_id)
        if not auth.allowed:
            return pb.GroupResponse(error_code=auth.error_code, error_detail=auth.error_detail)
        result = await self._membership.create_group(request.name, auth.user_id)
        if not result.ok or result.group is None:
            return pb.GroupResponse(error_code=result.error_code, error_detail=result.error_detail)
        return pb.GroupResponse(group=_group_entry(pb, result.group))

    async def AddGroupMember(self, request, context):
        from .generated import groups_pb2 as pb

        auth = await self._gate.authorize_admin(request.session_id)
        if not auth.allowed:
            return pb.MembershipResponse(
                error_code=auth.error_code, error_detail=auth.error_detail
            )
        result = await self._membership.add_member(
            request.group_id, request.user_id, auth.user_id,
            is_group_manager=request.is_group_manager,
        )
        if not result.ok or result.membership is None:
            return pb.MembershipResponse(
                error_code=result.error_code, error_detail=result.error_detail
            )
        return pb.MembershipResponse(membership=_membership_entry(pb, result.membership))

    async def RemoveGroupMember(self, request, context):
        from .generated import groups_pb2 as pb

        auth = await self._gate.authorize_admin(request.session_id)
        if not auth.allowed:
            return pb.RemoveMemberResponse(
                error_code=auth.error_code, error_detail=auth.error_detail
            )
        result = await self._membership.remove_member(request.group_id, request.user_id)
        return pb.RemoveMemberResponse(
            removed=result.ok, error_code=result.error_code, error_detail=result.error_detail
        )

    async def SetGroupManager(self, request, context):
        from .generated import groups_pb2 as pb

        # Owner/staff only (deep-dive §11) — the same admin gate as membership mutation,
        # not the narrower group-visibility one: flipping the flag is a system-wide
        # access-elevation decision, never something a group's own manager grants itself.
        auth = await self._gate.authorize_admin(request.session_id)
        if not auth.allowed:
            return pb.MembershipResponse(
                error_code=auth.error_code, error_detail=auth.error_detail
            )
        result = await self._membership.set_group_manager(
            request.group_id, request.user_id, request.is_group_manager,
            actor_user_id=auth.user_id, reason=request.reason or None,
        )
        if not result.ok or result.membership is None:
            return pb.MembershipResponse(
                error_code=result.error_code, error_detail=result.error_detail
            )
        return pb.MembershipResponse(membership=_membership_entry(pb, result.membership))

    async def GetEffectiveGroup(self, request, context):
        from .generated import groups_pb2 as pb

        subject = request.user_id or None  # empty on the wire means "myself"
        auth = await self._gate.authorize_effective_group(request.session_id, subject)
        if not auth.allowed:
            return pb.EffectiveGroupResponse(
                error_code=auth.error_code, error_detail=auth.error_detail
            )
        # `subject` was `None` for the ordinary "myself" case — resolved here against the
        # caller's own validated identity, never against anything else on the request.
        result: EffectiveGroupResult = await self._effective.get_effective_group(
            subject or auth.user_id or ""
        )
        if not result.ok:
            return pb.EffectiveGroupResponse(
                error_code=result.error_code, error_detail=result.error_detail
            )
        return pb.EffectiveGroupResponse(
            has_group=result.group_id is not None, group_id=result.group_id or ""
        )

    async def ListGroupMembers(self, request, context):
        from .generated import groups_pb2 as pb

        auth = await self._gate.authorize_group_visibility(request.session_id, request.group_id)
        if not auth.allowed:
            return pb.ListMembersResponse(
                error_code=auth.error_code, error_detail=auth.error_detail
            )
        result = await self._membership.list_members(request.group_id)
        if not result.ok:
            return pb.ListMembersResponse(
                error_code=result.error_code, error_detail=result.error_detail
            )
        return pb.ListMembersResponse(
            members=[_membership_entry(pb, m) for m in result.members]
        )


def serve(
    address: str = DEFAULT_ADDRESS,
    *,
    store: GroupsStore | None = None,
    resolver: SessionResolver | None = None,
    audit: AuditRecorder | None = None,
):
    """Start the service and return the running server so a caller can stop it.

    Pass a `:0` port to bind an ephemeral one — the actually-bound address is attached to the
    returned server as `bound_address`, matching every other Core API's own `serve()`.
    """
    import grpc

    from .generated import groups_pb2_grpc as pb_grpc

    store = store or GroupsStore()
    servicer = GroupsServicer(store, resolver=resolver, audit=audit)
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_GroupsServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"failed to bind {address}")
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    return server


__all__ = ["DEFAULT_ADDRESS", "GroupsServicer", "serve"]
