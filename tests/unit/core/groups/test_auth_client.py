"""`GrpcSessionResolver` — the real Auth adapter `service.py`'s own `__main__` was
missing entirely (confirmed by direct inspection: it called `serve(addr)` with no
resolver, so `PermissionGate` silently defaulted to `DenyAllSessions()` and the real
deployed Groups service denied every gated call it ever received). Live-tested against a
genuine running `AuthServicer`, never a mocked gRPC stub.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.auth.assembly import build_servicer  # noqa: E402
from core.auth.service import serve as auth_serve  # noqa: E402
from core.groups.auth_client import GrpcSessionResolver  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_resolves_a_real_implicit_owner_session_in_single_tenant_mode(tmp_path):
    async def scenario():
        servicer = build_servicer({"tenancy_mode": "single"})
        server = await auth_serve(servicer, "127.0.0.1:0")
        try:
            resolver = GrpcSessionResolver(server.bound_address)
            session = await resolver.resolve("")
            assert session is not None
            assert session.role.value == "owner"
        finally:
            await server.stop(None)

    run(scenario())


def test_resolves_none_for_an_unknown_session_in_multi_tenant_mode(tmp_path):
    async def scenario():
        servicer = build_servicer({"tenancy_mode": "multi"})
        server = await auth_serve(servicer, "127.0.0.1:0")
        try:
            resolver = GrpcSessionResolver(server.bound_address)
            session = await resolver.resolve("never-issued")
            assert session is None
        finally:
            await server.stop(None)

    run(scenario())


def test_resolves_none_when_auth_is_unreachable():
    async def scenario():
        resolver = GrpcSessionResolver("127.0.0.1:1")
        session = await resolver.resolve("anything")
        assert session is None

    run(scenario())


def test_create_group_actually_succeeds_end_to_end_with_the_real_resolver_wired(tmp_path):
    """The real, end-to-end confirmation of the fix: before this, a real running Groups
    service (constructed the same way its own __main__ does) denied every gated call --
    CreateGroup included -- because nothing ever gave it a real resolver."""
    from core.groups.service import serve as groups_serve
    from core.groups.generated import groups_pb2 as g_pb
    from core.groups.generated import groups_pb2_grpc as g_pb_grpc

    async def scenario():
        auth_servicer = build_servicer({"tenancy_mode": "single"})
        auth_server = await auth_serve(auth_servicer, "127.0.0.1:0")
        groups_server = groups_serve("127.0.0.1:0", resolver=GrpcSessionResolver(auth_server.bound_address))
        await groups_server.start()
        try:
            async with grpc.aio.insecure_channel(groups_server.bound_address) as channel:
                response = await g_pb_grpc.GroupsServiceStub(channel).CreateGroup(
                    g_pb.CreateGroupRequest(session_id="", name="Test Group")
                )
            assert response.error_code == "", response.error_code
            assert response.group.name == "Test Group"
        finally:
            await auth_server.stop(None)
            await groups_server.stop(None)

    run(scenario())
