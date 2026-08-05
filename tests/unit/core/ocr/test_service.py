"""The `OcrServicer` gRPC surface (`ocr.proto`).

`nox -s forward_compat` deliberately installs a narrow dependency set that excludes grpcio
(no prebuilt wheel for 3.15 yet, `docs/MAINTENANCE.md` §8.1) — the same guard
`core/preprocessing/tests/test_service.py`'s own module docstring explains, applied here.
"""

from __future__ import annotations

import asyncio

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")

from core.ocr.engine_registry import OcrConfig  # noqa: E402
from core.ocr.service import OcrServicer, serve  # noqa: E402

from .conftest import FakeBlobStore, make_synthetic_pdf_with_text  # noqa: E402


@pytest.mark.slow
def test_read_through_the_servicer_directly():
    async def go():
        store = FakeBlobStore({"img1": make_synthetic_pdf_with_text("RECEIPT TOTAL 5.00")})
        config = OcrConfig(engines_enabled=frozenset())
        servicer = OcrServicer(store, config=config)
        from core.ocr.generated import ocr_pb2 as pb

        request = pb.OcrReadRequest(
            run_id="r1", user_id="u1", blob_ref="img1", engines=["text_layer"], timeout_ms=15000,
        )
        return await servicer.Read(request)

    response = asyncio.run(go())
    assert len(response.readings) == 1
    assert response.readings[0].error_code == ""
    assert "RECEIPT TOTAL 5.00" in response.merged_text


@pytest.mark.slow
def test_list_engines_reflects_the_real_registry():
    async def go():
        store = FakeBlobStore()
        servicer = OcrServicer(store, config=OcrConfig())
        from core.ocr.generated import ocr_pb2 as pb

        return await servicer.ListEngines(pb.ListEnginesRequest())

    response = asyncio.run(go())
    assert "text_layer" in response.available_engines


@pytest.mark.slow
def test_a_real_client_can_read_over_an_actual_grpc_connection():
    """No stub of the thing under test: a real `grpc.aio` server on a real loopback socket,
    a real client stub — the same end-to-end discipline `core/preprocessing/service.py`'s
    own real-connection test already established for this repo."""
    from core.ocr.generated import ocr_pb2, ocr_pb2_grpc

    async def go():
        address = "127.0.0.1:19711"
        store = FakeBlobStore({"img1": make_synthetic_pdf_with_text("RECEIPT TOTAL 9.99")})
        config = OcrConfig(engines_enabled=frozenset())
        server = await serve(address, blob_store=store, config=config)
        try:
            channel = grpc.aio.insecure_channel(address)
            stub = ocr_pb2_grpc.OcrServiceStub(channel)
            response = await stub.Read(
                ocr_pb2.OcrReadRequest(
                    run_id="r1", user_id="u1", blob_ref="img1", engines=["text_layer"],
                    timeout_ms=15000,
                )
            )
            await channel.close()
            return response
        finally:
            await server.stop(None)

    response = asyncio.run(go())
    assert "RECEIPT TOTAL 9.99" in response.merged_text
