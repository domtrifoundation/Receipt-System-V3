"""The full-pipeline coverage and verbosity-leak hooks (Historian's own §13).

The verbosity-leak test is the concrete enforcement of §1's hard "quantized, never
Logs-resolution" rule. It matters because the narrative track is webapp-displayable and Logs
deliberately is not — a summarizer copying raw OCR text or a full prompt into `detail` both
bloats the canonical database and leaks server-internal detail to a remote audience.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.persistence.historian.contracts import NarrativeStage
from core.persistence.historian.errors import NarrativeVerbosityRejected
from core.persistence.historian.narrative.summarizers import SUMMARIZERS, summarize

_PIPELINE = (
    ("run_started", {}),
    ("ingested", {"channel": "drive"}),
    ("preprocessed", {"variants": ("standard", "high-contrast")}),
    (
        "ocr",
        {
            "readings": (
                {"engine": "tesseract", "mean_confidence": 0.87},
                {"engine": "rapidocr", "mean_confidence": 0.91},
            ),
            "agreement": "unanimous",
            "confidence": 0.91,
        },
    ),
    ("matched", {"vendor_name": "ABC Corp", "score": 0.94, "candidate_count": 7}),
    ("geo", {"confirmed": True, "locality": "Makati"}),
    ("inference", {"field_count": 9}),
    ("flagged", {"flag_type": "low_confidence"}),
    ("written", {"historian_event_id": "abc123"}),
)


def test_every_pipeline_stage_produces_at_least_one_event():
    for stage_name, result in _PIPELINE:
        events = summarize(stage_name, "rc1", "run-1", result)
        assert events, f"stage '{stage_name}' emitted no narrative event"


def test_ocr_emits_one_event_per_engine_plus_the_corroborated_outcome():
    """The specific thing this track exists to surface: engine X read at one confidence,
    engine Y at another — a single merged line would erase exactly that."""
    events = summarize("ocr", "rc1", "run-1", dict(_PIPELINE[3][1]))
    per_engine = [e for e in events if e.stage is NarrativeStage.OCR_ENGINE_RESULT]
    corroborated = [e for e in events if e.stage is NarrativeStage.OCR_CORROBORATED]
    assert len(per_engine) == 2
    assert len(corroborated) == 1
    assert "Tesseract" in per_engine[0].summary or "tesseract" in per_engine[0].summary
    assert "87%" in per_engine[0].summary
    assert "91%" in per_engine[1].summary


def test_an_engine_with_no_confidence_signal_is_stated_not_faked():
    events = summarize(
        "ocr",
        "rc1",
        "run-1",
        {"readings": ({"engine": "windows_ocr", "mean_confidence": None},),
         "agreement": "single", "confidence": None},
    )
    assert "no confidence signal" in events[0].summary


def test_detail_is_always_a_frozen_dict_mapping():
    for stage_name, result in _PIPELINE:
        for event in summarize(stage_name, "rc1", "run-1", result):
            assert isinstance(event.detail, FrozenDict)
            assert isinstance(event.detail, Mapping)


@pytest.mark.parametrize(
    "leak",
    [
        {"raw_text": "OFFICIAL RECEIPT ..."},
        {"prompt": "You are a receipt extraction model ..."},
        {"response": "{...}"},
        {"regions": [{"confidence": 0.9}]},
        {"timings": {"ocr_ms": 812}},
    ],
)
def test_logs_resolution_content_is_rejected_outright(leak):
    from core.persistence.historian.narrative.summarizers import _quantized

    with pytest.raises(NarrativeVerbosityRejected):
        _quantized(leak)


def test_an_overlong_string_is_rejected_even_under_an_innocuous_key():
    """The key-name blocklist alone is not enough — a leak can arrive under any name."""
    from core.persistence.historian.narrative.summarizers import _quantized

    with pytest.raises(NarrativeVerbosityRejected):
        _quantized({"note": "x" * 500})


def test_a_short_quantized_payload_passes():
    from core.persistence.historian.narrative.summarizers import _quantized

    payload = _quantized({"engine": "tesseract", "mean_confidence": 0.87})
    assert payload["engine"] == "tesseract"


def test_an_unknown_stage_degrades_to_no_events_rather_than_raising():
    """A stage that has not grown a summarizer yet must never fail a run."""
    assert summarize("a_stage_nobody_wrote_yet", "rc1", "run-1", {}) == ()


def test_a_rescan_marks_its_own_start_and_carries_the_reason():
    events = summarize(
        "run_started", "rc1", "run-2", {}, "system_rescan:reconciliation_escalation"
    )
    assert events[0].stage is NarrativeStage.RESCAN_STARTED
    assert events[0].triggered_by == "system_rescan:reconciliation_escalation"


def test_summarizer_table_is_a_frozen_dict():
    assert isinstance(SUMMARIZERS, FrozenDict)
