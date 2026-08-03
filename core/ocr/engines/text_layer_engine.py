"""Tier 0 — PDF embedded-text extraction, not OCR at all (deep-dive §4.1).

Two libraries deliberately, not one: PyMuPDF's plain text dump is fast and a good sanity
cross-check; pdfplumber's table extraction catches tabular amounts PyMuPDF's flat dump
sometimes runs together. Both are cheap enough to always run together on PDF input. An
image input (no PDF structure at all) is a no-op — empty text, no error, since "this isn't
a PDF" is the ordinary case for the majority of this API's callers, not a failure.

A PDF with no text layer (the scanned-image-wrapped-in-PDF case) also returns empty text,
not an error — this is the expected, common case that triggers falling through to tier 1
(deep-dive §4.1's own stated failure mode).
"""

from __future__ import annotations

import time

from ..contracts import EngineName, EngineReading
from .base import timed_reading

__all__ = ["TextLayerEngine"]


class TextLayerEngine:
    """`OcrEngine` for the PDF text layer. Takes PDF bytes directly — unlike every other
    engine here, its input was never rasterized by Preprocessing API, since reading the
    text layer is the alternative to rasterizing at all."""

    @property
    def engine(self) -> EngineName:
        return EngineName.TEXT_LAYER

    async def is_available(self) -> bool:
        try:
            import fitz  # noqa: F401, PLC0415
        except ImportError:
            return False
        try:
            import pdfplumber  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def read(self, image_bytes: bytes) -> EngineReading:
        start = time.monotonic()
        try:
            import fitz  # noqa: PLC0415
        except ImportError:
            return timed_reading(start, self.engine, "")

        try:
            doc = fitz.open(stream=image_bytes, filetype="pdf")
        except Exception:  # noqa: BLE001 - not a PDF at all is a no-op, not a crash
            return timed_reading(start, self.engine, "")

        try:
            fitz_text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

        table_text = self._pdfplumber_tables(image_bytes)
        merged = fitz_text if not table_text else f"{fitz_text}\n{table_text}"
        return timed_reading(start, self.engine, merged.strip())

    @staticmethod
    def _pdfplumber_tables(pdf_bytes: bytes) -> str:
        """Table-cell extraction only — plain running text already comes from PyMuPDF's
        own faster dump above; asking pdfplumber for that too would just duplicate it."""
        import io

        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError:
            return ""

        rows: list[str] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        for row in table:
                            rows.append(" ".join(cell or "" for cell in row))
        except Exception:  # noqa: BLE001 - a malformed table region is a no-op, not a crash
            return ""
        return "\n".join(rows)
