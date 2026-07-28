"""Per-stage raw-result → `NarrativeEvent` (`v3-deepdive-29-historian.md` §5).

**Why these live in one module rather than inside each pipeline API.** "Every step gets a
narrative entry" naturally decays into N different APIs each independently remembering (or
forgetting) to call Historian. The fix is a chokepoint that already exists for an unrelated
reason: Execution Core's `run_stage()` checkpoint wrapper already has every stage's call and
output flowing through it for resumable-retry purposes, so extending it to also emit a
narrative event covers every stage by construction. OCR, Matching, Geo and Inference never
need to know this track exists — they stay focused on their own domain logic, and the
summarization logic stays reviewable in one small module.

**The verbosity rule is enforced here, not merely documented.** `NarrativeEvent.detail` is
webapp-displayable, and Logs deliberately is not. Raw OCR text, full prompts, full model
responses and detailed timing belong to Logs. `_quantized()` below rejects a payload that
looks like Logs-resolution content, which is the concrete enforcement the verbosity-leak
regression test checks (§13 there).

Every summarizer takes a plain `Mapping` of the stage's own result rather than importing
OCR's / Matching's / Inference's contract types. That is deliberate: this module must not
create an import edge from Persistence into every pipeline API, and `run_stage()` already
holds the real typed result at the call site.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from common.frozen_dict import FrozenDict

from ...contracts import utcnow
from ..contracts import NarrativeEvent, NarrativeStage
from ..errors import NarrativeVerbosityRejected

#: Keys a stage result may carry that are unambiguously Logs' territory. A summarizer that
#: copies one of these into `detail` is the drift §1's hard rule exists to prevent.
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "raw_text",
        "full_text",
        "text",
        "ocr_text",
        "prompt",
        "full_prompt",
        "response",
        "raw_response",
        "completion",
        "messages",
        "regions",
        "stack_trace",
        "timings",
    }
)

#: A quantized fact is short. This is a blunt length ceiling on any single string value in
#: `detail`, deliberately generous enough for a vendor name or a flag reason and nowhere
#: near enough for a receipt's extracted text.
_MAX_DETAIL_STRING = 200


def _quantized(detail: Mapping[str, Any]) -> FrozenDict:
    """Validate and freeze one `detail` payload.

    Checked as `Mapping`, never as `dict` — the 3.15 builtin `frozendict` is not a `dict`
    subclass and an `isinstance(x, dict)` gate here would silently take the wrong branch
    (`docs/PRINCIPLES.md` §2.1).
    """
    if not isinstance(detail, Mapping):
        raise NarrativeVerbosityRejected(f"detail must be a Mapping, got {type(detail)!r}")
    for key, value in detail.items():
        if key in _FORBIDDEN_DETAIL_KEYS:
            raise NarrativeVerbosityRejected(
                f"'{key}' is Logs-resolution content and must not enter the narrative track"
            )
        if isinstance(value, str) and len(value) > _MAX_DETAIL_STRING:
            raise NarrativeVerbosityRejected(
                f"'{key}' is {len(value)} chars — the narrative track is quantized"
            )
    return FrozenDict(dict(detail))


def _event(
    receipt_id: str,
    run_id: str,
    stage: NarrativeStage,
    summary: str,
    detail: Mapping[str, Any],
    triggered_by: str,
) -> NarrativeEvent:
    return NarrativeEvent(
        event_id=uuid.uuid4().hex,
        receipt_id=receipt_id,
        run_id=run_id,
        stage=stage,
        summary=summary,
        detail=_quantized(detail),
        triggered_by=triggered_by,
        occurred_at=utcnow(),
    )


def _pct(value: Any) -> str:
    """Confidence rendered the way the user-facing example states it — a whole percent."""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "unknown"


# --------------------------------------------------------------- summarizers
def summarize_run_started(receipt_id, run_id, result, triggered_by="initial_scan"):
    stage = (
        NarrativeStage.RESCAN_STARTED
        if triggered_by != "initial_scan"
        else NarrativeStage.RUN_STARTED
    )
    verb = "Rescan" if stage is NarrativeStage.RESCAN_STARTED else "Scan"
    return (
        _event(
            receipt_id, run_id, stage, f"{verb} started on run {run_id}",
            {"run_id": run_id}, triggered_by,
        ),
    )


def summarize_ingested(receipt_id, run_id, result, triggered_by="initial_scan"):
    channel = result.get("channel", "unknown")
    return (
        _event(
            receipt_id, run_id, NarrativeStage.INGESTED,
            f"Ingested via {channel}", {"channel": channel}, triggered_by,
        ),
    )


def summarize_preprocessed(receipt_id, run_id, result, triggered_by="initial_scan"):
    variants = tuple(result.get("variants", ()))
    return (
        _event(
            receipt_id, run_id, NarrativeStage.PREPROCESSED,
            "Preprocessing: " + (", ".join(variants) if variants else "no variants"),
            {"variant_count": len(variants), "variants": list(variants)}, triggered_by,
        ),
    )


def summarize_ocr(receipt_id, run_id, result, triggered_by="initial_scan"):
    """One `OCR_ENGINE_RESULT` per engine reading, plus one `OCR_CORROBORATED`.

    Per-engine rather than one merged line because seeing that engine X read at one
    confidence and engine Y at another is the specific thing this track exists to surface.
    `mean_confidence` is read straight off `EngineReading` — computed once by the engine's
    own wrapper, never re-averaged from `regions` here (§5.1), which is also why `regions`
    is on the forbidden-keys list.
    """
    events = []
    for reading in result.get("readings", ()):
        engine = reading.get("engine", "unknown")
        conf = reading.get("mean_confidence")
        rendered = _pct(conf) if conf is not None else "no confidence signal"
        events.append(
            _event(
                receipt_id, run_id, NarrativeStage.OCR_ENGINE_RESULT,
                f"OCR ({engine}) read this receipt at {rendered}",
                {"engine": engine, "mean_confidence": conf}, triggered_by,
            )
        )
    agreement = result.get("agreement", "unknown")
    events.append(
        _event(
            receipt_id, run_id, NarrativeStage.OCR_CORROBORATED,
            f"OCR corroborated: {agreement} agreement, "
            f"{_pct(result.get('confidence'))} confidence",
            {
                "agreement": agreement,
                "confidence": result.get("confidence"),
                "engine_count": len(tuple(result.get("readings", ()))),
            },
            triggered_by,
        )
    )
    return tuple(events)


def summarize_matched(receipt_id, run_id, result, triggered_by="initial_scan"):
    vendor = result.get("vendor_name", "no match")
    candidates = result.get("candidate_count", 0)
    return (
        _event(
            receipt_id, run_id, NarrativeStage.MATCHED,
            f"Matched to {vendor} — {_pct(result.get('score'))} confidence, "
            f"{candidates} candidates considered",
            {
                "vendor_id": result.get("vendor_id"),
                "score": result.get("score"),
                "candidate_count": candidates,
            },
            triggered_by,
        ),
    )


def summarize_geod(receipt_id, run_id, result, triggered_by="initial_scan"):
    confirmed = bool(result.get("confirmed"))
    summary = (
        f"Address confirmed at {result.get('locality', 'the matched location')}"
        if confirmed
        else "Address/vendor mismatch flagged"
    )
    return (
        _event(
            receipt_id, run_id, NarrativeStage.GEOD, summary,
            {"confirmed": confirmed, "provider": result.get("provider")}, triggered_by,
        ),
    )


def summarize_inference(receipt_id, run_id, result, triggered_by="initial_scan"):
    failure = result.get("validation_failure")
    summary = (
        f"Extracted {result.get('field_count', 0)} fields, schema-valid"
        if not failure
        else f"Extraction validation failed: {failure}"
    )
    return (
        _event(
            receipt_id, run_id, NarrativeStage.INFERENCE_DELIBERATED, summary,
            {
                "field_count": result.get("field_count", 0),
                "schema_valid": not failure,
                "retry_path": result.get("retry_path", ""),
            },
            triggered_by,
        ),
    )


def summarize_flagged(receipt_id, run_id, result, triggered_by="initial_scan"):
    reason = result.get("flag_type", "unspecified")
    return (
        _event(
            receipt_id, run_id, NarrativeStage.FLAGGED,
            f"Flagged for review: {reason}",
            {"flag_type": reason, "flag_id": result.get("flag_id", "")}, triggered_by,
        ),
    )


def summarize_written(receipt_id, run_id, result, triggered_by="initial_scan"):
    return (
        _event(
            receipt_id, run_id, NarrativeStage.WRITTEN,
            "Written to canonical record",
            {"historian_event_id": result.get("historian_event_id", "")}, triggered_by,
        ),
    )


def summarize_user_correction(receipt_id, run_id, result, triggered_by="initial_scan"):
    """A human edit is already a data-change event; this keeps the *unified* timeline from
    having a silent gap where one track has an entry and the other does not (§7)."""
    field = result.get("field", "a field")
    return (
        _event(
            receipt_id, run_id, NarrativeStage.WRITTEN,
            f"User corrected {field}", {"field": field}, triggered_by,
        ),
    )


#: Stage name → summarizer. A module-level lookup table, so `FrozenDict`
#: (`docs/PRINCIPLES.md` §2.1.1) — it is a constant, not a registry anything mutates.
SUMMARIZERS = FrozenDict(
    {
        "run_started": summarize_run_started,
        "ingested": summarize_ingested,
        "preprocessed": summarize_preprocessed,
        "ocr": summarize_ocr,
        "matched": summarize_matched,
        "geo": summarize_geod,
        "inference": summarize_inference,
        "flagged": summarize_flagged,
        "written": summarize_written,
        "user_correction": summarize_user_correction,
    }
)


def summarize(
    stage_name: str,
    receipt_id: str,
    run_id: str,
    result: Mapping[str, Any],
    triggered_by: str = "initial_scan",
) -> tuple[NarrativeEvent, ...]:
    """Dispatch for `run_stage()`'s own `_emit_narrative` call.

    An unknown stage degrades to no events rather than raising — a pipeline stage that has
    not grown a summarizer yet must not be able to fail a run (`docs/PRINCIPLES.md` §4.4).
    That gap is caught by the full-pipeline narrative coverage test, which is the right
    place for it, rather than by breaking production.
    """
    fn = SUMMARIZERS.get(stage_name)
    if fn is None:
        return ()
    return fn(receipt_id, run_id, result, triggered_by)


__all__ = ["SUMMARIZERS", "summarize"]
