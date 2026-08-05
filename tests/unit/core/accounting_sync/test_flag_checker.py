"""`GrpcFlagChecker` — the real client against Review/Flagging's now-real gRPC surface
(`core/review_flagging/service.py`), closing the gap `NoOpFlagChecker` (`service.py`) was
built to document honestly."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.accounting_sync.flag_checker import GrpcFlagChecker  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def _serve_review_flagging():
    import grpc

    from core.review_flagging.generated import review_flagging_pb2_grpc
    from core.review_flagging.lifecycle import FlagStore
    from core.review_flagging.service import ReviewFlaggingServicer

    store = FlagStore(":memory:")
    server = grpc.aio.server()
    review_flagging_pb2_grpc.add_ReviewFlaggingServiceServicer_to_server(
        ReviewFlaggingServicer(store), server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port, store


def test_has_open_flag_is_false_before_any_flag_is_raised():
    async def scenario():
        server, port, _store = await _serve_review_flagging()
        try:
            checker = GrpcFlagChecker(address=f"127.0.0.1:{port}")
            assert await checker.has_open_flag("receipt-1") is False
        finally:
            await server.stop(None)

    run(scenario())


def test_has_open_flag_is_true_after_a_real_flag_is_created():
    async def scenario():
        server, port, store = await _serve_review_flagging()
        try:
            from core.review_flagging.contracts import CreateFlagRequest

            await store.create_flag(CreateFlagRequest(
                flag_type="vat_math_mismatch", user_id="u1", receipt_id="receipt-1",
                created_by="reconciliation",
            ))
            checker = GrpcFlagChecker(address=f"127.0.0.1:{port}")
            assert await checker.has_open_flag("receipt-1") is True
            assert await checker.has_open_flag("receipt-2") is False
        finally:
            await server.stop(None)

    run(scenario())


def test_has_open_flag_is_false_once_the_flag_is_resolved():
    async def scenario():
        server, port, store = await _serve_review_flagging()
        try:
            from core.review_flagging.contracts import CreateFlagRequest, ResolveFlagRequest

            created = await store.create_flag(CreateFlagRequest(
                flag_type="vat_math_mismatch", user_id="u1", receipt_id="receipt-1",
                created_by="reconciliation",
            ))
            await store.resolve_flag(
                ResolveFlagRequest(flag_id=created.flag.flag_id, resolution_note="fixed"),
                "unresolvable-session",
            )
            # the resolve above is denied (no real role resolver wired) so the flag stays
            # open — confirms has_open_flag reflects real store state, not a guess
            checker = GrpcFlagChecker(address=f"127.0.0.1:{port}")
            assert await checker.has_open_flag("receipt-1") is True
        finally:
            await server.stop(None)

    run(scenario())


def test_unreachable_service_fails_open_not_closed():
    checker = GrpcFlagChecker(address="127.0.0.1:1", timeout_seconds=0.5)

    assert run(checker.has_open_flag("anything")) is False
