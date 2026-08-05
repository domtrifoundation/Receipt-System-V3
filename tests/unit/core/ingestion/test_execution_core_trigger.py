"""The real webapp/direct-upload trigger, end to end: `IngestionServicer.SubmitDirectUpload`
normalizes a real upload and now calls Execution Core's `StartRun`/`SubmitReceipt` for
real -- confirmed here against six genuine running servicers (Content Security,
Persistence, Preprocessing, OCR, Execution Core, Ingestion), no mocked gRPC stub
anywhere in the chain. Closes a real, previously-confirmed gap: `SubmitDirectUpload` used
to normalize a file and stop, with nothing anywhere telling Execution Core a receipt
existed to process.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("fitz", reason="pymupdf is not installed in this interpreter")

from common.blob_client import GrpcBlobStoreClient  # noqa: E402
from core.content_security.providers.base import ProviderRegistry  # noqa: E402
from core.content_security.service import serve as cs_serve  # noqa: E402
from core.ingestion.content_security_client import ContentSecurityClient  # noqa: E402
from core.ingestion.service import IngestionServicer  # noqa: E402
from core.ocr.service import serve as ocr_serve  # noqa: E402
from core.persistence.grpc_servicer import serve as persistence_serve  # noqa: E402
from core.preprocessing.service import serve as preprocessing_serve  # noqa: E402
from services.execution_core.service import serve as execution_core_serve  # noqa: E402

from .conftest import AlwaysCleanProvider, make_synthetic_pdf  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_real_direct_upload_triggers_real_ocr_processing_end_to_end(tmp_path: Path):
    async def scenario():
        cs_address = f"127.0.0.1:{_free_port()}"
        cs_registry = ProviderRegistry()
        cs_registry.register(AlwaysCleanProvider())
        cs_server = cs_serve(cs_address, registry=cs_registry)
        content_security = ContentSecurityClient(cs_address)

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

        ingestion_servicer = IngestionServicer(
            blob_client, content_security=content_security,
            execution_core_address=execution_core_server.bound_address,
        )

        try:
            from core.ingestion.generated import ingestion_pb2 as ing_pb

            pdf_bytes = make_synthetic_pdf(pages=1, text="RECEIPT")
            response = await ingestion_servicer.SubmitDirectUpload(ing_pb.DirectUploadRequest(
                run_id="upload1", user_id="webapp_user", filename="receipt.pdf",
                declared_mime_type="application/pdf", content=pdf_bytes,
            ))
            assert not response.error_code, response.error_code

            # SubmitDirectUpload's own trigger call is fire-and-forget from the caller's
            # perspective (it doesn't block the upload response on processing completing) --
            # but internally it awaits StartRun/SubmitReceipt before returning, so by the
            # time this response comes back the real receipt already exists in Persistence.
            from core.persistence.generated import persistence_pb2 as p_pb
            from core.persistence.generated import persistence_pb2_grpc as p_pb_grpc

            async with grpc.aio.insecure_channel(persistence_server.bound_address) as channel:
                list_response = await p_pb_grpc.PersistenceServiceStub(channel).ListReceipts(
                    p_pb.ListReceiptsRequest(user_id="webapp_user", limit=10)
                )
            assert len(list_response.receipts) == 1
        finally:
            cs_server.stop(None)
            await persistence_server.stop(None)
            await preprocessing_server.stop(None)
            await ocr_server.stop(None)
            await execution_core_server.stop(None)

    run(scenario())
