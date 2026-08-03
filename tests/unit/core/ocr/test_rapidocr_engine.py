"""`RapidOcrEngine` (deep-dive §4.3) — real ONNX Runtime inference, not mocked. Confirmed
live during development that the first call after process start pays a real one-time
model-load cost (~13s on the development machine) that a cached, reused `RapidOCR()`
instance avoids on every call after — `rapidocr_engine.py`'s own module docstring documents
this; these tests are marked `slow` accordingly.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "rapidocr_onnxruntime", reason="rapidocr-onnxruntime has no prebuilt wheel for this interpreter yet"
)

from core.ocr.engines.rapidocr_engine import RapidOcrEngine  # noqa: E402

from .conftest import make_text_png, run  # noqa: E402


@pytest.mark.slow
def test_is_available():
    engine = RapidOcrEngine()
    assert run(engine.is_available()) is True


@pytest.mark.slow
def test_reads_real_rendered_text_with_regions():
    engine = RapidOcrEngine()
    image = make_text_png("HELLO RECEIPT")
    reading = run(engine.read(image))
    assert reading.error is None
    assert len(reading.regions) > 0
    assert reading.mean_confidence is not None
    for region in reading.regions:
        # TextRegion.box is normalized 0-1 against image dimensions (contracts.py §3).
        assert 0.0 <= region.box[0] <= 1.0
        assert 0.0 <= region.box[1] <= 1.0
