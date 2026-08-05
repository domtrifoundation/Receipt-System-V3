"""`GrpcPersistenceWriteGateway` — a real read-modify-write client against Persistence's
now-real gRPC surface (`core/persistence/grpc_servicer.py`), closing the functional gap
`UnavailablePersistenceWriteGateway` documented honestly (`persistence.proto` still has
no dedicated field-level `ApplyEdit` RPC; this composes `GetReceipt`/`SaveReceipt`
instead, the same "general primitives compose" posture
`core/accounting_sync/persistence_client.py` already takes)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

import grpc  # noqa: E402

from core.persistence.generated import persistence_pb2 as ppb  # noqa: E402
from core.persistence.generated import persistence_pb2_grpc as ppb_grpc  # noqa: E402
from core.persistence.grpc_servicer import PersistenceGrpcServicer  # noqa: E402
from core.review_flagging.gateways import GrpcPersistenceWriteGateway  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def _serve_persistence(tmp_path):
    server = grpc.aio.server()
    ppb_grpc.add_PersistenceServiceServicer_to_server(
        PersistenceGrpcServicer(top_level=tmp_path), server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port


async def _seed_receipt(port, receipt_id="r1", user_id="u1"):
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
        stub = ppb_grpc.PersistenceServiceStub(channel)
        put = await stub.PutBlob(ppb.PutBlobRequest(user_id=user_id, original_bytes=b"hi", codec="original"))
        msg = ppb.ReceiptMessage(
            receipt_id=receipt_id, user_id=user_id, blob=ppb.BlobRefMessage(logical_id=put.blob.logical_id),
            vendor_name="Acme", currency="PHP", total_amount="55.00",
            created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        )
        await stub.SaveReceipt(ppb.SaveReceiptRequest(receipt=msg, actor="human:u1"))


def test_apply_edit_patches_a_first_class_field(tmp_path):
    async def scenario():
        server, port = await _serve_persistence(tmp_path)
        try:
            await _seed_receipt(port)
            gateway = GrpcPersistenceWriteGateway(address=f"127.0.0.1:{port}")

            result = await gateway.apply_edit("u1", "r1", "total_amount", "99.99", "staff-1")

            assert result.ok is True
            assert result.historian_event_id != ""

            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = ppb_grpc.PersistenceServiceStub(channel)
                confirm = await stub.GetReceipt(ppb.GetReceiptRequest(user_id="u1", receipt_id="r1"))
                assert confirm.receipt.total_amount == "99.99"
        finally:
            await server.stop(None)

    run(scenario())


def test_apply_edit_patches_a_non_first_class_field_into_receipt_fields(tmp_path):
    async def scenario():
        server, port = await _serve_persistence(tmp_path)
        try:
            await _seed_receipt(port)
            gateway = GrpcPersistenceWriteGateway(address=f"127.0.0.1:{port}")

            result = await gateway.apply_edit("u1", "r1", "vendor_tin", "123-456-789", "staff-1")

            assert result.ok is True

            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = ppb_grpc.PersistenceServiceStub(channel)
                confirm = await stub.GetReceipt(ppb.GetReceiptRequest(user_id="u1", receipt_id="r1"))
                fields = json.loads(confirm.receipt.fields_json)
                assert fields["vendor_tin"] == "123-456-789"
        finally:
            await server.stop(None)

    run(scenario())


def test_apply_edit_reports_receipt_not_found_for_an_unknown_receipt(tmp_path):
    async def scenario():
        server, port = await _serve_persistence(tmp_path)
        try:
            gateway = GrpcPersistenceWriteGateway(address=f"127.0.0.1:{port}")

            result = await gateway.apply_edit("u1", "does-not-exist", "total_amount", "1.00", "staff-1")

            assert result.ok is False
            assert result.error_code == "receipt_not_found"
        finally:
            await server.stop(None)

    run(scenario())


def test_apply_edit_against_an_unreachable_service_reports_persistence_unavailable():
    gateway = GrpcPersistenceWriteGateway(address="127.0.0.1:1", timeout_seconds=0.5)

    result = run(gateway.apply_edit("u1", "r1", "total_amount", "1.00", "staff-1"))

    assert result.ok is False
    assert result.error_code == "PERSISTENCE_UNAVAILABLE"
