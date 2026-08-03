"""`TextLayerEngine` (deep-dive §4.1) — tier 0, not OCR at all.

Real PyMuPDF/pdfplumber calls against a synthetic, genuinely-generated PDF (`conftest.py`'s
`make_synthetic_pdf_with_text`) — no mocking of the libraries themselves, just no real
receipt scan involved.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fitz", reason="pymupdf has no prebuilt wheel for this interpreter yet")
pytest.importorskip("pdfplumber", reason="pdfplumber has no prebuilt wheel for this interpreter yet")

from core.ocr.engines.text_layer_engine import TextLayerEngine  # noqa: E402

from .conftest import make_synthetic_pdf_with_text, run  # noqa: E402


def test_is_available_when_both_libraries_are_installed():
    engine = TextLayerEngine()
    assert run(engine.is_available()) is True


def test_reads_a_real_pdf_text_layer():
    engine = TextLayerEngine()
    pdf_bytes = make_synthetic_pdf_with_text("RECEIPT TOTAL 123.45")
    reading = run(engine.read(pdf_bytes))
    assert reading.error is None
    assert "RECEIPT TOTAL 123.45" in reading.text


def test_non_pdf_input_is_a_no_op_not_an_error():
    engine = TextLayerEngine()
    reading = run(engine.read(b"this is not a pdf at all"))
    assert reading.error is None
    assert reading.text == ""
