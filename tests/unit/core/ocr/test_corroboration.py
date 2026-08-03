"""`corroboration.py`'s tiered agreement logic (deep-dive §7.3), in isolation from any real
engine — every reading here is a plain constructed `EngineReading`.
"""

from __future__ import annotations

from core.ocr.contracts import AgreementLevel, EngineName, EngineReading, OcrError, OcrErrorCode
from core.ocr.corroboration import merge_readings, normalize_text


def _reading(engine: EngineName, text: str, mean_confidence: float | None = None) -> EngineReading:
    return EngineReading(engine=engine, text=text, duration_ms=10, mean_confidence=mean_confidence)


def _failed(engine: EngineName) -> EngineReading:
    return EngineReading.failure(engine, OcrError(OcrErrorCode.ENGINE_CRASHED, "boom"))


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  hello   world  \n\n") == "hello world"


def test_no_valid_readings_is_none_agreement():
    result = merge_readings((_failed(EngineName.TESSERACT), _failed(EngineName.RAPIDOCR)))
    assert result.agreement == AgreementLevel.NONE
    assert result.merged_text == ""
    assert result.confidence == 0.0
    assert len(result.readings) == 2


def test_single_valid_reading_is_single_source():
    readings = (_reading(EngineName.TESSERACT, "TOTAL 123.45", mean_confidence=0.8), _failed(EngineName.RAPIDOCR))
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.SINGLE_SOURCE
    assert result.confidence == 0.8
    assert "TOTAL 123.45" in result.merged_text


def test_single_valid_reading_with_no_confidence_signal_uses_fallback():
    readings = (_reading(EngineName.WINDOWS_OCR, "TOTAL 123.45", mean_confidence=None),)
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.SINGLE_SOURCE
    assert 0.0 < result.confidence < 1.0


def test_unanimous_agreement_when_every_pair_matches():
    readings = (
        _reading(EngineName.TESSERACT, "TOTAL 123.45", mean_confidence=0.7),
        _reading(EngineName.RAPIDOCR, "TOTAL 123.45", mean_confidence=0.9),
        _reading(EngineName.WINDOWS_OCR, "TOTAL 123.45"),
    )
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.UNANIMOUS
    assert result.confidence > 0.9
    # Tie-break prefers the highest mean_confidence among the agreeing set.
    assert "123.45" in result.merged_text


def test_majority_agreement_with_one_outlier():
    readings = (
        _reading(EngineName.TESSERACT, "TOTAL 123.45", mean_confidence=0.7),
        _reading(EngineName.RAPIDOCR, "TOTAL 123.45", mean_confidence=0.9),
        _reading(EngineName.PADDLEOCR, "completely unrelated garbled text zzz"),
    )
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.MAJORITY
    assert "123.45" in result.merged_text
    assert 0.0 < result.confidence < 1.0


def test_genuine_split_with_no_majority():
    readings = (
        _reading(EngineName.TESSERACT, "aaaa bbbb cccc"),
        _reading(EngineName.RAPIDOCR, "dddd eeee ffff"),
        _reading(EngineName.PADDLEOCR, "gggg hhhh iiii"),
    )
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.SPLIT
    assert result.confidence == 0.2


def test_empty_and_short_readings_are_treated_as_insane_not_valid():
    readings = (_reading(EngineName.TESSERACT, ""), _reading(EngineName.RAPIDOCR, "a"))
    result = merge_readings(readings)
    assert result.agreement == AgreementLevel.NONE


def test_every_requested_engine_appears_in_readings_even_on_failure():
    """Deep-dive §3's own design choice: never silently drop a requested unit of work."""
    readings = (
        _reading(EngineName.TESSERACT, "TOTAL 123.45"),
        _failed(EngineName.PADDLEOCR),
    )
    result = merge_readings(readings)
    engines_seen = {r.engine for r in result.readings}
    assert engines_seen == {EngineName.TESSERACT, EngineName.PADDLEOCR}
