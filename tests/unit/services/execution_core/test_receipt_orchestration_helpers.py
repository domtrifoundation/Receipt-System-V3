"""Pure-function coverage for `receipt_orchestration.py`'s own real helpers -- no gRPC,
no `onnxruntime_genai`, real direct tests of the logic that decides what an LLM prompt
actually contains.
"""

from __future__ import annotations

from services.execution_core.receipt_orchestration import (
    _MAX_READINGS_FOR_LLM,
    _first_line,
    _select_distinct_readings,
)


def _reading(text: str, confidence: float, variant: str = "standard") -> dict:
    return {"variant": variant, "text": text, "confidence": confidence, "agreement": "unanimous"}


def test_first_line_skips_blank_lines():
    assert _first_line("\n\n  JOLLIBEE FOODS CORP  \nSecond line") == "JOLLIBEE FOODS CORP"


def test_first_line_returns_empty_for_all_blank_text():
    assert _first_line("\n\n   \n") == ""


def test_select_distinct_readings_keeps_genuinely_different_readings():
    readings = [
        _reading("JOLLIBEE FOODS CORP\nTOTAL 645.00", 0.95, "standard"),
        _reading("MERCURY DRUG\nTOTAL 167.00", 0.80, "bw_threshold"),
    ]
    selected = _select_distinct_readings(readings)
    assert len(selected) == 2
    assert selected[0]["confidence"] == 0.95  # highest-confidence first


def test_select_distinct_readings_drops_near_duplicates():
    """OCR noise on a handful of characters -- real disagreement is kept, this is not."""
    readings = [
        _reading("JOLLIBEE FOODS CORPORATION\nTOTAL 645.00\nTIN 123-456-789", 0.95),
        _reading("JOLLIBEE FOODS CORPORATI0N\nTOTAL 645.00\nTIN 123-456-789", 0.60),
    ]
    selected = _select_distinct_readings(readings)
    assert len(selected) == 1
    assert selected[0]["confidence"] == 0.95


def test_select_distinct_readings_caps_at_the_real_limit():
    readings = [_reading(f"totally different receipt text number {i} " * 5, 0.5 + i * 0.01) for i in range(10)]
    selected = _select_distinct_readings(readings)
    assert len(selected) == _MAX_READINGS_FOR_LLM


def test_select_distinct_readings_handles_empty_input():
    assert _select_distinct_readings([]) == []
