"""Shared fixtures for Ingestion's unit tests. Every fixture here is synthetic — small
in-memory images/PDFs built with real `cv2`/`fitz` calls — never a real receipt image,
matching every other API's own conftest this session."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from core.ingestion.contracts import BlobRef


def run(coro):
    return asyncio.run(coro)


class FakeBlobStore:
    def __init__(self, blobs: dict[str, bytes] | None = None) -> None:
        self.blobs = blobs or {}

    async def read_blob(self, ref: BlobRef) -> bytes:
        return self.blobs[ref.logical_id]

    async def write_blob(self, data: bytes) -> BlobRef:
        logical_id = str(uuid.uuid4())
        self.blobs[logical_id] = data
        return BlobRef(logical_id=logical_id)


@pytest.fixture
def blob_store() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture(autouse=True)
def _isolated_log_root(tmp_path, monkeypatch):
    """`IngestionServicer` now holds a real `LogWriter` for its own best-effort failure
    paths (a genuine, previously-missing observability fix — see `service.py`'s own
    docstring). Without this, every test in this package would write real files to this
    machine's own default log root (`core/logs/paths.py`'s `~/.resibo/logs` fallback)
    every time the suite runs."""
    monkeypatch.setenv("RESIBO_LOG_ROOT", str(tmp_path / "logs"))


def make_synthetic_pdf(pages: int = 1, text: str = "TEST RECEIPT") -> bytes:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=300)
        page.insert_text((20, 30), f"{text} {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def make_synthetic_jpeg(size: tuple[int, int] = (80, 80)) -> bytes:
    import cv2
    import numpy as np

    arr = np.random.randint(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", arr)
    assert ok
    return buf.tobytes()


def make_textured_strip(width: int = 900, height: int = 300, seed: int = 42):
    import cv2
    import numpy as np

    img = np.zeros((height, width, 3), dtype=np.uint8)
    rng = np.random.RandomState(seed)
    for _ in range(400):
        x, y = rng.randint(0, width), rng.randint(0, height)
        cv2.circle(
            img, (x, y), rng.randint(3, 10),
            (int(rng.randint(0, 255)), int(rng.randint(0, 255)), int(rng.randint(0, 255))), -1,
        )
    return img


class AlwaysCleanProvider:
    """A real `MalwareScanProvider` (Content Security's own Protocol) that always
    reports clean — used to stand up a real Content Security service in tests without
    needing ClamAV/VirusTotal configured."""

    name = "always-clean-test-provider"

    async def scan(self, content: bytes, *, blob_ref: str = ""):
        from core.content_security.contracts import ProviderScanResult, ScanOutcome

        return ProviderScanResult(provider_name=self.name, outcome=ScanOutcome.CLEAN)

    async def is_available(self) -> bool:
        return True
