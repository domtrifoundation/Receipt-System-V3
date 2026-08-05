"""The full six-stage real pipeline -- `preprocessed` -> `ocrd` -> `matched` -> `geod` ->
`inferred` -> `written` -- against seven genuine running servicers (Persistence,
Preprocessing, OCR, Architect, Matching, Geo/Address, Inference, Execution Core), closing
the exact gap `services/execution_core/gateways.py`'s own module docstring used to
describe: `matched`/`geod`/`inferred` reaching `WRITTEN` with nothing registered for them.

Inference runs against a real `InferenceServicer` with a fake worker (`_FakeWorker`,
mirroring `core/inference/tests/unit/core/inference/test_service.py`'s own established
pattern) -- no real model weights in a unit test, matching this repo's own "fakes only for
genuinely external/network-touching seams" convention; a real model is what Phase 1's own
live run against real receipts (not this test) exercises. Geo/Address runs with its real
default `UnavailableTransport` -- degrading `geod()` to a real, honest "no provider
configured" result rather than a crash is itself part of what this test proves.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("fitz", reason="pymupdf is not installed in this interpreter")

from common.blob_client import GrpcBlobStoreClient  # noqa: E402
from core.architect.service import serve as architect_serve  # noqa: E402
from core.geo_address.service import serve as geo_serve  # noqa: E402
from core.inference.contracts import FinishReason, GenerationResult  # noqa: E402
from core.inference.model_registry import InferenceConfig  # noqa: E402
from core.inference.service import InferenceServicer  # noqa: E402
from core.matching.service import serve as matching_serve  # noqa: E402
from core.ocr.service import serve as ocr_serve  # noqa: E402
from core.persistence.grpc_servicer import serve as persistence_serve  # noqa: E402
from core.preprocessing.service import serve as preprocessing_serve  # noqa: E402
from services.execution_core.generated import execution_core_pb2 as ec_pb  # noqa: E402
from services.execution_core.service import serve as execution_core_serve  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_synthetic_pdf_with_text(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text((20, 30), text)
    data = doc.tobytes()
    doc.close()
    return data


class _FakeExtractionWorker:
    """Returns a real, schema-valid structured extraction -- proving `inferred()`'s own
    `response_schema_json` round-trip and `json.loads(response.text)` parse, without a
    real model."""

    def __init__(self, preset_name: str) -> None:
        self.preset_name = preset_name

    async def load(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True

    async def submit(self, request, grammar_schema, images=(), on_retry=None):
        payload = {"vendor_name": "Test Vendor Corp", "total_amount": 123.45, "currency": "PHP"}
        return GenerationResult(
            text=json.dumps(payload), tool_call=None, finish_reason=FinishReason.STOP,
            schema_valid=True, device="cpu", duration_ms=1,
        )

    async def shutdown(self) -> None:
        pass


async def _serve_inference_with_fake_worker(address: str):
    server = grpc.aio.server()
    from core.inference.generated import inference_pb2_grpc

    config = InferenceConfig(presets_enabled=frozenset({"phi4-mini"}))
    servicer = InferenceServicer(config, worker_factory=lambda name: _FakeExtractionWorker(name))
    inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"
    await server.start()
    return server


def test_a_real_receipt_reaches_written_with_a_real_vendor_match_geocode_and_structured_extraction(
    tmp_path: Path,
):
    async def scenario():
        persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        blob_client = GrpcBlobStoreClient(persistence_server.bound_address)
        preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: blob_client)
        ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=blob_client)
        architect_server = await architect_serve(f"127.0.0.1:{_free_port()}")
        matching_server = matching_serve(f"127.0.0.1:{_free_port()}")  # not async, unlike its siblings
        geo_server = geo_serve(f"127.0.0.1:{_free_port()}")  # not async either
        inference_server = await _serve_inference_with_fake_worker(f"127.0.0.1:{_free_port()}")
        execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": preprocessing_server.bound_address,
                "ocr": ocr_server.bound_address,
                "persistence": persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",  # never reached on the happy path
                "architect": architect_server.bound_address,
                "matching": matching_server.bound_address,
                "geo_address": geo_server.bound_address,
                "inference": inference_server.bound_address,
            },
        )
        try:
            pdf_bytes = _make_synthetic_pdf_with_text("SOME STORE\nRECEIPT TOTAL 5.00")
            blob_ref = await blob_client.write_blob(pdf_bytes)

            from services.execution_core.generated import execution_core_pb2_grpc

            async with grpc.aio.insecure_channel(execution_core_server.bound_address) as channel:
                stub = execution_core_pb2_grpc.ExecutionCoreServiceStub(channel)
                start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id="u1", file_count=1))

                submit_response = await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                    run_id=start_response.run.run_id, user_id="u1", receipt_id="r1",
                    source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                    ocr_source="source", ocr_engines=["text_layer"],
                ))

            assert submit_response.error_detail == "", submit_response.error_detail
            assert submit_response.reached_stage == "written"
            assert submit_response.outcome == "completed"

            from core.persistence.generated import persistence_pb2 as p_pb
            from core.persistence.generated import persistence_pb2_grpc as p_pb_grpc

            async with grpc.aio.insecure_channel(persistence_server.bound_address) as channel:
                receipt_response = await p_pb_grpc.PersistenceServiceStub(channel).GetReceipt(
                    p_pb.GetReceiptRequest(user_id="u1", receipt_id=submit_response.persisted_receipt_id)
                )

            fields = json.loads(receipt_response.receipt.fields_json)
            # The real, fake-worker-provided structured extraction landed in the persisted record.
            assert fields["vendor_name"] == "Test Vendor Corp"
            assert fields["total_amount"] == 123.45
            # Matching genuinely ran (an empty Architect directory still returns a real,
            # honest "no candidates" result, not an absence of the key at all).
            assert "vendor_match" in fields
            assert fields["vendor_match"]["candidate_count"] == 0
            # Geo genuinely ran too, degrading to an honest unconfigured-provider result
            # rather than being skipped or crashing.
            assert "geocode" in fields
            assert "RECEIPT TOTAL 5.00" in fields["raw_ocr_text"]
        finally:
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await architect_server.stop(None)
            matching_server.stop(None)  # sync server, sync stop -- see construction above
            geo_server.stop(None)  # sync server, sync stop
            await inference_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())
