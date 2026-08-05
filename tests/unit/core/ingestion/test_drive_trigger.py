"""The real Google Drive-triggered processing path (webhook push + fallback poll) --
closes a genuine gap: `pending_events`/`list_new_files()` used to produce real data that
nothing downstream ever consumed into an actual receipt.

A fake `GoogleDriveSource` stands in for the real one -- the same "swappable adapter,
tested via a fake conforming to the same Protocol" pattern this API's own test suite
already uses for Drive (real Drive credentials/`google-api-python-client` genuinely
don't exist in this environment, confirmed elsewhere in this suite). Everything
downstream of that one seam -- normalization, Content Security, Execution Core,
Preprocessing, OCR, Persistence -- is real and live, no other mock anywhere.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from pathlib import Path

import pytest

grpc = pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("fitz", reason="pymupdf is not installed in this interpreter")

from common.blob_client import GrpcBlobStoreClient  # noqa: E402
from core.content_security.providers.base import ProviderRegistry  # noqa: E402
from core.content_security.service import serve as cs_serve  # noqa: E402
from core.ingestion.content_security_client import ContentSecurityClient  # noqa: E402
from core.ingestion.contracts import SourceFile, SourceKind  # noqa: E402
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


@dataclass
class FakeDriveSource:
    """Real `GoogleDriveSource` Protocol shape, fake data -- see this module's own
    docstring for why real Drive credentials aren't available in this environment."""

    blob_store: object
    files: dict = field(default_factory=dict)  # file_id -> pdf bytes

    async def is_available(self) -> bool:
        return True

    async def list_new_files(self) -> tuple[dict, ...]:
        return tuple({"id": file_id, "name": file_id, "mimeType": "application/pdf"} for file_id in self.files)

    async def download(self, run_id: str, user_id: str, file_id: str, filename: str, mime_type: str) -> SourceFile:
        raw_ref = await self.blob_store.write_blob(self.files[file_id])
        return SourceFile(
            run_id=run_id, user_id=user_id, source=SourceKind.GOOGLE_DRIVE,
            raw_blob_ref=raw_ref, original_filename=filename, declared_mime_type=mime_type,
        )


class _Servers:
    def __init__(self):
        self.cs_server = None
        self.persistence_server = None
        self.preprocessing_server = None
        self.ocr_server = None
        self.execution_core_server = None

    async def start(self, tmp_path: Path):
        cs_address = f"127.0.0.1:{_free_port()}"
        cs_registry = ProviderRegistry()
        cs_registry.register(AlwaysCleanProvider())
        self.cs_server = cs_serve(cs_address, registry=cs_registry)
        self.content_security = ContentSecurityClient(cs_address)

        self.persistence_server = await persistence_serve(f"127.0.0.1:{_free_port()}", top_level=tmp_path)
        self.blob_client = GrpcBlobStoreClient(self.persistence_server.bound_address)
        self.preprocessing_server = await preprocessing_serve(f"127.0.0.1:{_free_port()}", blob_store_factory=lambda: self.blob_client)
        self.ocr_server = await ocr_serve(f"127.0.0.1:{_free_port()}", blob_store=self.blob_client)
        self.execution_core_server = await execution_core_serve(
            f"127.0.0.1:{_free_port()}",
            addresses={
                "preprocessing": self.preprocessing_server.bound_address,
                "ocr": self.ocr_server.bound_address,
                "persistence": self.persistence_server.bound_address,
                "review_flagging": "127.0.0.1:1",
            },
        )

    async def stop(self):
        self.cs_server.stop(None)
        await self.persistence_server.stop(None)
        await self.preprocessing_server.stop(None)
        await self.ocr_server.stop(None)
        await self.execution_core_server.stop(None)


async def _receipt_count(persistence_bound_address: str, user_id: str) -> int:
    from core.persistence.generated import persistence_pb2 as p_pb
    from core.persistence.generated import persistence_pb2_grpc as p_pb_grpc

    async with grpc.aio.insecure_channel(persistence_bound_address) as channel:
        response = await p_pb_grpc.PersistenceServiceStub(channel).ListReceipts(
            p_pb.ListReceiptsRequest(user_id=user_id, limit=10)
        )
    return len(response.receipts)


def test_handle_drive_webhook_downloads_normalizes_and_submits_the_real_event(tmp_path: Path):
    async def scenario():
        servers = _Servers()
        await servers.start(tmp_path)
        try:
            servicer = IngestionServicer(
                servers.blob_client, content_security=servers.content_security,
                execution_core_address=servers.execution_core_server.bound_address,
            )
            fake_drive = FakeDriveSource(blob_store=servers.blob_client, files={"file1": make_synthetic_pdf(text="DRIVE RECEIPT")})
            servicer._registry._sources[SourceKind.GOOGLE_DRIVE] = fake_drive

            from core.ingestion.webhook_manager.contracts import ChangeEvent, WebhookProvider

            events = (ChangeEvent(provider=WebhookProvider.GOOGLE_DRIVE, file_id="file1", change_type="added"),)
            await servicer._process_drive_events(events)

            assert await _receipt_count(servers.persistence_server.bound_address, "local") == 1
        finally:
            await servers.stop()

    run(scenario())


def test_poll_drive_fallback_processes_every_listed_file(tmp_path: Path):
    async def scenario():
        servers = _Servers()
        await servers.start(tmp_path)
        try:
            servicer = IngestionServicer(
                servers.blob_client, content_security=servers.content_security,
                execution_core_address=servers.execution_core_server.bound_address,
            )
            fake_drive = FakeDriveSource(
                blob_store=servers.blob_client,
                files={"file1": make_synthetic_pdf(text="POLL A"), "file2": make_synthetic_pdf(text="POLL B")},
            )
            servicer._registry._sources[SourceKind.GOOGLE_DRIVE] = fake_drive

            from core.ingestion.generated import ingestion_pb2 as pb

            response = await servicer.PollDriveFallback(pb.PollDriveFallbackRequest())

            assert response.accepted is True
            assert await _receipt_count(servers.persistence_server.bound_address, "local") == 2
        finally:
            await servers.stop()

    run(scenario())


def test_removed_change_events_are_skipped_not_processed(tmp_path: Path):
    async def scenario():
        servers = _Servers()
        await servers.start(tmp_path)
        try:
            servicer = IngestionServicer(
                servers.blob_client, content_security=servers.content_security,
                execution_core_address=servers.execution_core_server.bound_address,
            )
            fake_drive = FakeDriveSource(blob_store=servers.blob_client, files={"file1": make_synthetic_pdf()})
            servicer._registry._sources[SourceKind.GOOGLE_DRIVE] = fake_drive

            from core.ingestion.webhook_manager.contracts import ChangeEvent, WebhookProvider

            events = (ChangeEvent(provider=WebhookProvider.GOOGLE_DRIVE, file_id="file1", change_type="removed"),)
            await servicer._process_drive_events(events)

            assert await _receipt_count(servers.persistence_server.bound_address, "local") == 0
        finally:
            await servers.stop()

    run(scenario())
