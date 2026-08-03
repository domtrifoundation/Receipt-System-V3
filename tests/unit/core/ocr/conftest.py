"""Shared fixtures for OCR's unit tests.

Real receipt fixtures (`tests/fixtures/real_receipts/`) are never referenced from this
automated suite — gitignored, sourced only from real scans the user supplies, and used for
manual/live validation only, matching the same rule Preprocessing API's own conftest
states. Everything here is synthetic: a small in-memory PNG built with real `cv2`/`numpy`
calls, and a synthetic PDF built with PyMuPDF's own drawing API.
"""

from __future__ import annotations

import asyncio

import pytest

from core.ocr.contracts import BlobRef


def run(coro):
    return asyncio.run(coro)


class FakeBlobStore:
    """An in-memory `BlobStoreGateway` — real enough to prove `engine_registry.py`'s own
    read-blob call shape without needing a real Persistence connection."""

    def __init__(self, blobs: dict[str, bytes] | None = None) -> None:
        self.blobs = blobs or {}

    async def read_blob(self, ref: BlobRef) -> bytes:
        return self.blobs[ref.logical_id]


@pytest.fixture
def blob_store() -> FakeBlobStore:
    return FakeBlobStore()


def make_text_png(text: str = "SAMPLE RECEIPT", size: tuple[int, int] = (240, 120)) -> bytes:
    """A synthetic PNG with real rendered text — enough for Tesseract/RapidOCR to have
    something genuine to read in a slow/live test, without touching a real receipt scan."""
    import cv2
    import numpy as np

    width, height = size
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.putText(image, text, (10, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def make_synthetic_pdf_with_text(text: str = "RECEIPT TOTAL 123.45") -> bytes:
    """A genuine one-page PDF with a real text layer, built with PyMuPDF's own drawing
    API — exercises `text_layer_engine.py`'s real extraction path."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text((20, 30), text)
    data = doc.tobytes()
    doc.close()
    return data
