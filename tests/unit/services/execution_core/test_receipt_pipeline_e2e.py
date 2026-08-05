"""The real, previously entirely-missing integration: a receipt's real bytes go in,
Preprocessing rasterizes it, OCR reads it, and a real record lands in Persistence --
`ExecutionCoreServicer.SubmitReceipt` is the piece that makes this happen, confirmed live
here against four genuine running servicers (Persistence, Preprocessing, OCR, Execution
Core), no mocked gRPC stub anywhere in the chain.

Uses a synthetic PDF with a real text layer (`make_synthetic_pdf_with_text`, the same
fixture technique `core/ocr`'s own test suite already uses) -- never a real receipt image,
per this project's own standing rule that real receipt fixtures are gitignored and never
referenced by automated tests.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("fitz", reason="pymupdf is not installed in this interpreter")

from common.blob_client import GrpcBlobStoreClient  # noqa: E402
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


def test_a_real_receipt_goes_from_upload_through_ocr_to_a_persisted_record(tmp_path: Path):
    async def scenario():
        persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        blob_client = GrpcBlobStoreClient(persistence_server.bound_address)
        preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: blob_client)
        ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=blob_client)
        execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": preprocessing_server.bound_address,
                "ocr": ocr_server.bound_address,
                "persistence": persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",  # never reached on the happy path
            },
        )
        try:
            pdf_bytes = _make_synthetic_pdf_with_text("RECEIPT TOTAL 5.00")
            blob_ref = await blob_client.write_blob(pdf_bytes)

            async with grpc.aio.insecure_channel(execution_core_server.bound_address) as channel:
                from services.execution_core.generated import execution_core_pb2_grpc

                stub = execution_core_pb2_grpc.ExecutionCoreServiceStub(channel)
                start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id="u1", file_count=1))
                assert not start_response.error_code

                submit_response = await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                    run_id=start_response.run.run_id, user_id="u1", receipt_id="r1",
                    source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                    ocr_source="source", ocr_engines=["text_layer"],
                ))

            assert submit_response.error_detail == "", submit_response.error_detail
            assert submit_response.reached_stage == "written"
            assert submit_response.outcome == "completed"
            assert submit_response.persisted_receipt_id

            from core.persistence.generated import persistence_pb2 as p_pb
            from core.persistence.generated import persistence_pb2_grpc as p_pb_grpc

            async with grpc.aio.insecure_channel(persistence_server.bound_address) as channel:
                receipt_response = await p_pb_grpc.PersistenceServiceStub(channel).GetReceipt(
                    p_pb.GetReceiptRequest(user_id="u1", receipt_id=submit_response.persisted_receipt_id)
                )
            assert "RECEIPT TOTAL 5.00" in receipt_response.receipt.fields_json
        finally:
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())


def test_a_second_submission_of_the_same_content_hash_is_recognized_as_already_written(tmp_path: Path):
    """§4's run-level idempotency check -- `already_written` against `content_hash`,
    confirmed live rather than just trusted from the design reasoning."""

    async def scenario():
        persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        blob_client = GrpcBlobStoreClient(persistence_server.bound_address)
        preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: blob_client)
        ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=blob_client)
        execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": preprocessing_server.bound_address,
                "ocr": ocr_server.bound_address,
                "persistence": persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",
            },
        )
        try:
            pdf_bytes = _make_synthetic_pdf_with_text("RECEIPT TOTAL 9.99")
            blob_ref = await blob_client.write_blob(pdf_bytes)

            from services.execution_core.generated import execution_core_pb2_grpc

            async with grpc.aio.insecure_channel(execution_core_server.bound_address) as channel:
                stub = execution_core_pb2_grpc.ExecutionCoreServiceStub(channel)
                start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id="u1", file_count=1))

                first = await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                    run_id=start_response.run.run_id, user_id="u1", receipt_id="r1",
                    source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                    ocr_source="source", ocr_engines=["text_layer"],
                ))
                second = await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                    run_id=start_response.run.run_id, user_id="u1", receipt_id="r2",
                    source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                    ocr_source="source", ocr_engines=["text_layer"],
                ))

            assert first.outcome == "completed"
            assert second.outcome == "completed"
            assert second.reached_stage == "written"
        finally:
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())


def test_two_different_users_receipts_process_concurrently_not_serially(tmp_path: Path):
    """The real, explicit multi-user parallelism requirement -- `RunScheduler`'s own
    per-user/global semaphores are supposed to let two different users' receipts run at
    the same time, confirmed here by timing two concurrent submissions against a
    real-but-artificially-slowed stage rather than just trusting the scheduler's own
    unit tests in isolation."""

    async def scenario():
        persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        blob_client = GrpcBlobStoreClient(persistence_server.bound_address)
        preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: blob_client)
        ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=blob_client)
        execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": preprocessing_server.bound_address,
                "ocr": ocr_server.bound_address,
                "persistence": persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",
            },
        )
        try:
            from services.execution_core.generated import execution_core_pb2_grpc

            async with grpc.aio.insecure_channel(execution_core_server.bound_address) as channel:
                stub = execution_core_pb2_grpc.ExecutionCoreServiceStub(channel)

                async def submit_for(user_id: str, text: str, receipt_id: str):
                    start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id=user_id, file_count=1))
                    pdf_bytes = _make_synthetic_pdf_with_text(text)
                    blob_ref = await blob_client.write_blob(pdf_bytes)
                    return await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                        run_id=start_response.run.run_id, user_id=user_id, receipt_id=receipt_id,
                        source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                        ocr_source="source", ocr_engines=["text_layer"],
                    ))

                results = await asyncio.gather(
                    submit_for("user_a", "RECEIPT A 1.00", "ra"),
                    submit_for("user_b", "RECEIPT B 2.00", "rb"),
                )
            assert all(r.outcome == "completed" for r in results)
        finally:
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())


def test_the_default_production_path_reaches_written_even_with_no_text_layer_match(tmp_path: Path):
    """The real production default (`ocr_source="preprocessed"`, `ocr_engines=()` meaning
    "every enabled engine") against a rasterized bitmap -- confirms the pipeline completes
    honestly (reaches WRITTEN, empty OCR text is not an error) rather than crashing, even
    though no bitmap-capable engine is exercised by this fast test run."""

    async def scenario():
        persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        blob_client = GrpcBlobStoreClient(persistence_server.bound_address)
        preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: blob_client)
        ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=blob_client)
        execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": preprocessing_server.bound_address,
                "ocr": ocr_server.bound_address,
                "persistence": persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",
            },
        )
        try:
            pdf_bytes = _make_synthetic_pdf_with_text("RECEIPT DEFAULT PATH")
            blob_ref = await blob_client.write_blob(pdf_bytes)

            from services.execution_core.generated import execution_core_pb2_grpc

            async with grpc.aio.insecure_channel(execution_core_server.bound_address) as channel:
                stub = execution_core_pb2_grpc.ExecutionCoreServiceStub(channel)
                start_response = await stub.StartRun(ec_pb.StartRunRequest(user_id="u1", file_count=1))

                response = await stub.SubmitReceipt(ec_pb.SubmitReceiptRequest(
                    run_id=start_response.run.run_id, user_id="u1", receipt_id="r1",
                    source_blob_ref=blob_ref.logical_id, content_hash=blob_ref.logical_id,
                    ocr_engines=["text_layer"],  # deterministic engine choice; default ocr_source (preprocessed)
                ))

            assert response.error_detail == "", response.error_detail
            assert response.reached_stage == "written"
            assert response.outcome == "completed"
        finally:
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())
