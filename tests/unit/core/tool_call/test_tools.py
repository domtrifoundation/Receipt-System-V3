"""The five tool modules under `tools/*.py` — every one was a 0-byte scaffold until this
session. These tests confirm the real, live-reachable behavior against real running
servicers built earlier this session (Persistence, Architect), plus the honest
unavailable-degrade path when nothing is listening — never a mock standing in for the
gRPC call itself."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

import grpc  # noqa: E402

from common.frozen_dict import FrozenDict  # noqa: E402
from core.tool_call.contracts import ToolContext  # noqa: E402
from core.tool_call.registry import ToolRegistry  # noqa: E402
from core.tool_call.tools import (  # noqa: E402
    geo_tools,
    persistence_write_tools,
    query_tools,
    settings_tools,
    vendor_tools,
)


def run(coro):
    return asyncio.run(coro)


CONTEXT = ToolContext(run_id="run-1", user_id="user-1", calling_api="inference_reconciliation")


# --------------------------------------------------------------- settings_tools (empty)

def test_settings_tools_registers_nothing_by_design():
    registry = ToolRegistry()

    settings_tools.register_settings_tools(registry)

    assert registry.all_specs() == ()


# --------------------------------------------------------------------------- geo_tools

def test_geocode_place_is_unavailable_when_geo_address_is_unreachable():
    assert geo_tools._is_geo_address_available("127.0.0.1:1") is False


def test_geocode_place_raises_a_real_error_when_unreachable():
    with pytest.raises(Exception):
        geo_tools.geocode_place(FrozenDict({"candidate_strings": ["123 Main St"]}), CONTEXT, address="127.0.0.1:1")


def test_register_geo_tools_registers_a_read_only_spec():
    registry = ToolRegistry()

    geo_tools.register_geo_tools(registry, address="127.0.0.1:1")

    entry = registry.get("geocode_place")
    assert entry is not None
    assert entry.spec.category.value == "read_only"
    assert entry.is_available() is False


# ------------------------------------------------------------------------ vendor_tools

def test_lookup_vendor_canon_finds_a_real_merged_corporation():
    async def scenario():
        server, port = await _serve_architect()
        try:
            from core.architect.generated import architect_pb2 as apb

            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                from core.architect.generated import architect_pb2_grpc as apb_grpc
                stub = apb_grpc.ArchitectServiceStub(channel)
                submitted = await stub.SubmitContribution(apb.ContributionRequest(
                    contributor="human:u1", target_entity_type="corporation", target_entity_id="",
                    proposed_change={"name": "Acme Corp", "corporate_tin": "123-456-789"},
                    staff_authored=True,
                ))
                assert submitted.contribution.merged is True

            result = await asyncio.to_thread(
                vendor_tools.lookup_vendor_canon,
                FrozenDict({"query": "Acme Corp"}), CONTEXT, address=f"127.0.0.1:{port}",
            )
            assert [r["name"] for r in result["records"]] == ["Acme Corp"]
        finally:
            await server.stop(None)

    run(scenario())


def test_remember_vendor_stages_a_real_contribution():
    async def scenario():
        server, port = await _serve_architect()
        try:
            result = await asyncio.to_thread(
                vendor_tools.remember_vendor,
                FrozenDict({"name": "New Vendor Inc.", "corporate_tin": "999-999-999"}),
                CONTEXT, address=f"127.0.0.1:{port}",
            )
            assert result["staff_review_status"] == "pending"
            assert result["merged"] is False
        finally:
            await server.stop(None)

    run(scenario())


async def _serve_architect():
    from core.architect.generated import architect_pb2_grpc
    from core.architect.service import ArchitectServicer

    server = grpc.aio.server()
    architect_pb2_grpc.add_ArchitectServiceServicer_to_server(ArchitectServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port


# --------------------------------------------------------------------------- query_tools

def test_persistence_query_is_unavailable_when_search_query_is_unreachable():
    assert query_tools._is_search_query_available("127.0.0.1:1") is False


# ---------------------------------------------------------- persistence_write_tools

def test_persistence_write_field_rejects_a_field_outside_the_allowlist():
    with pytest.raises(ValueError):
        persistence_write_tools.persistence_write_field(
            FrozenDict({"receipt_id": "r1", "field": "user_id", "new_value": "someone-else"}),
            CONTEXT,
        )


def test_persistence_write_field_writes_a_real_receipt_through_the_real_service(tmp_path: Path):
    async def scenario():
        server, port = await _serve_persistence(tmp_path)
        try:
            result = await asyncio.to_thread(
                persistence_write_tools.persistence_write_field,
                FrozenDict({"receipt_id": "r1", "field": "total_amount", "new_value": "42.00"}),
                CONTEXT, address=f"127.0.0.1:{port}",
            )
            assert result["historian_event_id"] != ""

            from core.persistence.generated import persistence_pb2 as ppb
            from core.persistence.generated import persistence_pb2_grpc as ppb_grpc

            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = ppb_grpc.PersistenceServiceStub(channel)
                confirm = await stub.GetReceipt(ppb.GetReceiptRequest(user_id="user-1", receipt_id="r1"))
                assert confirm.receipt.total_amount == "42.00"
        finally:
            await server.stop(None)

    run(scenario())


async def _serve_persistence(tmp_path):
    from core.persistence.generated import persistence_pb2 as ppb
    from core.persistence.generated import persistence_pb2_grpc as ppb_grpc
    from core.persistence.grpc_servicer import PersistenceGrpcServicer

    server = grpc.aio.server()
    ppb_grpc.add_PersistenceServiceServicer_to_server(PersistenceGrpcServicer(top_level=tmp_path), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
        stub = ppb_grpc.PersistenceServiceStub(channel)
        put = await stub.PutBlob(ppb.PutBlobRequest(user_id="user-1", original_bytes=b"hi", codec="original"))
        msg = ppb.ReceiptMessage(
            receipt_id="r1", user_id="user-1", blob=ppb.BlobRefMessage(logical_id=put.blob.logical_id),
            vendor_name="Acme", currency="PHP", total_amount="10.00",
            created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        )
        await stub.SaveReceipt(ppb.SaveReceiptRequest(receipt=msg, actor="human:user-1"))

    return server, port
