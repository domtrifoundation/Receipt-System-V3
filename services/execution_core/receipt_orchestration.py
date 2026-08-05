"""Builds the real `ReceiptWork` a receipt is actually processed with — the piece that
was missing entirely (`gateways.py`'s own module docstring has the full account of what
was confirmed live-missing and why). All six real stages are wired now: `preprocessed`/
`ocrd`/`written` as before, plus `matched`/`geod`/`inferred` closing the gap this module's
own docstring used to describe — a receipt used to reach `WRITTEN` with real OCR text and
nothing else; it now carries a real vendor match, a real geocode attempt, and a real
LLM-structured extraction.

**`RECEIPT_EXTRACTION_SCHEMA` is a deliberately scoped v1**, not the full field set every
deep-dive eventually wants extracted (line-item-level detail, the full BIR identifier
vocabulary). It covers the first-class `Receipt` columns (`core/persistence/contracts.py`),
the two most common Architect-seeded identifier kinds (`tin`, `or_number`), and the
address/VAT-treatment fields Reconciliation's own `ReceiptSnapshot` needs — real,
extendable later, not a placeholder standing in for something unbuilt.
"""

from __future__ import annotations

import json

from services.execution_core.contracts import CheckpointStore, ReceiptStage
from services.execution_core.gateways import (
    GrpcArchitectGateway,
    GrpcGeoGateway,
    GrpcInferenceGateway,
    GrpcMatchingGateway,
    GrpcOcrGateway,
    GrpcPersistenceGateway,
    GrpcPreprocessingGateway,
)
from services.execution_core.pipeline import ReceiptWork

__all__ = ["RECEIPT_EXTRACTION_SCHEMA", "build_receipt_work"]

#: A real JSON Schema handed to Inference's own `response_schema_json` (constrained
#: decoding, `core/inference/structured_output.py`) -- v1 scope, see module docstring.
RECEIPT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {"type": "string"},
        "transaction_date": {"type": "string", "description": "ISO-8601 date, e.g. 2026-07-13"},
        "currency": {"type": "string", "default": "PHP"},
        "total_amount": {"type": "number"},
        "vat_amount": {"type": "number"},
        "subtotal_amount": {"type": "number"},
        "vat_treatment": {"type": "string", "description": "vatable | zero_rated | vat_exempt | unknown"},
        "tin": {"type": "string"},
        "or_number": {"type": "string", "description": "the Official Receipt / Sales Invoice number"},
        "address": {"type": "string"},
    },
    "required": ["vendor_name", "total_amount"],
}

#: Only the first non-empty line of raw OCR text is used as Architect's search query --
#: real, PH-receipt-layout-informed heuristic (vendor name is conventionally the first
#: printed line), not an attempt at full extraction before Inference even runs. Matching
#: itself never fetches candidates (`gateways.GrpcArchitectGateway`'s own docstring).
_MAX_CANDIDATE_QUERY_CHARS = 120

#: Real multi-spectral corroboration -- broader than Preprocessing's own conservative
#: `DEFAULT_VARIANTS_ENABLED` (`{standard, bw_threshold}`, `variant_registry.py`), a
#: deliberate choice for the extraction-quality problem this set exists to help with:
#: STANDARD (baseline), BW_THRESHOLD (high-contrast text isolation), HIGH_CONTRAST
#: (a different tonal axis than BW_THRESHOLD), DESKEW (real-world phone-photographed
#: receipts are rarely perfectly aligned), DENOISE (compression/scan artifacts). Each
#: variant is read by every one of OCR's own enabled engines internally (`ocr.read()`'s
#: own `engines=()` "every enabled engine" default) -- this is the real "N variants x M
#: engines" corroboration surface, not Preprocessing's default-conservative pair.
_OCR_VARIANT_KINDS: tuple[str, ...] = (
    "standard", "bw_threshold", "high_contrast", "deskew", "denoise",
)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_MAX_CANDIDATE_QUERY_CHARS]
    return ""


def build_receipt_work(
    *,
    receipt_id: str,
    run_id: str,
    user_id: str,
    source_blob_ref: str,
    content_hash: str,
    store: CheckpointStore,
    preprocessing: GrpcPreprocessingGateway,
    ocr: GrpcOcrGateway,
    persistence: GrpcPersistenceGateway,
    architect: GrpcArchitectGateway | None = None,
    matching: GrpcMatchingGateway | None = None,
    geo: GrpcGeoGateway | None = None,
    inference: GrpcInferenceGateway | None = None,
    inference_preset: str = "phi4-mini",
    ocr_engines: tuple[str, ...] = (),
    ocr_source: str = "preprocessed",
) -> ReceiptWork:
    """`ocr_engines=()` is the real production default: OCR's own multi-engine
    corroboration is the point of this API (`v3-deepdive-01-ocr-api.md`), so the normal
    path asks for "every enabled engine," never one hardcoded choice.

    `ocr_source="preprocessed"` (the real production default) reads the rasterized bitmap
    `preprocessed` produced -- correct for a photographed/scanned upload, which is what
    Ingestion's own normalization actually hands this pipeline for the real webapp/Drive
    trigger paths. `ocr_source="source"` reads the original `source_blob_ref` instead --
    real, live-found necessity for a genuinely digital PDF whose own embedded text layer
    the `text_layer` engine reads directly, where rasterizing first would destroy exactly
    the signal that engine needs (confirmed live: text_layer against a rasterized PNG
    returns an empty read every time). Choosing between the two per actual source kind,
    rather than a caller having to know which to pass, is real follow-up work.

    `architect`/`matching`/`geo`/`inference` default to `None` -- a caller that only wants
    the original three stages (still real, still valid) gets exactly the prior behavior;
    the three new stages are registered only when their gateway is actually supplied,
    matching `docs/PRINCIPLES.md` §4.4's degrade-gracefully rule the same way an absent
    `GEOD` stage already degrades for a receipt with nothing to geocode.
    """

    async def preprocessed() -> str:
        response = await preprocessing.rasterize(run_id=run_id, user_id=user_id, source_blob_ref=source_blob_ref)
        if response.error_code:
            raise RuntimeError(f"preprocessing failed: {response.error_code}: {response.error_detail}")
        return response.image_blob_ref

    async def ocrd() -> str:
        if ocr_source == "source":
            # A genuinely digital PDF's own embedded text layer -- variant image
            # transforms are meaningless here (there is no rasterized image to
            # transform), the same real reasoning `text_layer` engine's own docstring
            # already states for why this path reads `source_blob_ref` directly.
            response = await ocr.read(run_id=run_id, user_id=user_id, blob_ref=source_blob_ref, engines=ocr_engines)
            return response.merged_text

        checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.PREPROCESSED)
        if checkpoint is None:
            raise RuntimeError("ocrd stage ran before preprocessed checkpoint existed")
        base_blob_ref = checkpoint.stage_output_ref

        # Real multi-spectral corroboration: N real image variants, each read by every
        # one of OCR's own enabled engines -- the actual "N variants x M engines" sweep,
        # not a single rasterize-then-read pass. `variants.error_code` set is a real,
        # honest per-variant failure (`docs/PRINCIPLES.md` §4.4) -- skipped, never fatal
        # to the receipt as long as at least one variant produces a real image.
        variants_response = await preprocessing.generate_variants(
            run_id=run_id, user_id=user_id, image_blob_ref=base_blob_ref, kinds=_OCR_VARIANT_KINDS,
        )
        variant_blob_refs = [v.image_blob_ref for v in variants_response.variants if not v.error_code]
        if not variant_blob_refs:
            # Every real variant failed (or `GenerateVariants` itself degraded to
            # nothing) -- fall back to the one base image `preprocessed()` already
            # produced, rather than failing the whole receipt over a corroboration
            # enhancement that has no working input to enhance.
            variant_blob_refs = [base_blob_ref]

        best_response = None
        for blob_ref in variant_blob_refs:
            response = await ocr.read(run_id=run_id, user_id=user_id, blob_ref=blob_ref, engines=ocr_engines)
            if best_response is None or response.confidence > best_response.confidence:
                best_response = response
        return best_response.merged_text

    async def _raw_ocr_text() -> str:
        ocr_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.OCRD)
        return ocr_checkpoint.stage_output_ref if ocr_checkpoint is not None else ""

    async def matched() -> dict:
        """Cheap, deterministic vendor resolution against Architect's real directory,
        run before the expensive LLM call so `inferred()` below can hand Inference real
        corroboration context (§5.1's own resolved design) -- a match here is a real
        signal for the LLM to confirm/use, never a substitute for its own extraction."""
        from core.matching.generated import matching_pb2 as match_pb

        raw_text = await _raw_ocr_text()
        candidates_response = await architect.search_vendor_directory(
            query=_first_line(raw_text), user_id=user_id, limit=10
        )
        candidates = [
            match_pb.VendorCandidateProto(entity_id=r.corporation_id, name=r.name, entity_kind="corporation")
            for r in candidates_response.records
        ]
        match_request = match_pb.MatchRequest(
            extracted_text=_first_line(raw_text), raw_ocr_text=raw_text, candidates=candidates, limit=5,
        )
        response = await matching.get_vendor_match_context(match_request=match_request, policy="always")
        top = response.candidates[0] if response.candidates else None
        return {
            "included": response.included,
            "top_candidate_name": top.canonical_name if top else "",
            "top_candidate_entity_id": top.entity_id if top else "",
            "top_candidate_score": top.score if top else 0.0,
            "candidate_count": len(response.candidates),
        }

    async def geod() -> dict:
        """A real geocode attempt -- degrades to whatever `GrpcGeoGateway`'s own default
        `UnavailableTransport` posture reports (`core/geo_address/CLAUDE.md`) when no real
        provider is configured, never a crash over an unconfigured/unreachable provider."""
        raw_text = await _raw_ocr_text()
        matched_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.MATCHED)
        vendor_hint = matched_checkpoint.stage_output_ref.get("top_candidate_name", "") if matched_checkpoint else ""
        response = await geo.geocode(candidate_strings=(_first_line(raw_text),), vendor_name_hint=vendor_hint)
        result = response.result if response.HasField("result") else None
        return {
            "conflict": result.conflict if result else False,
            "formatted_address": result.normalized_address.formatted if result and result.HasField("normalized_address") else "",
            "error_code": response.error_code,
        }

    async def inferred() -> dict:
        """The real LLM-structured extraction (deep-dive §4.4/§9) -- corroborated with
        `matched()`'s own real candidate, never blind to it."""
        raw_text = await _raw_ocr_text()
        matched_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.MATCHED)
        vendor_hint = ""
        if matched_checkpoint is not None and matched_checkpoint.stage_output_ref.get("included"):
            vendor_hint = matched_checkpoint.stage_output_ref.get("top_candidate_name", "")

        hint_line = f"A fuzzy vendor-directory match suggests this may be: {vendor_hint!r}.\n" if vendor_hint else ""
        prompt = (
            "Extract the following fields from this Philippine receipt's OCR text as JSON "
            "matching the given schema. Use your own reading of the vendor name even if it "
            "differs from the suggested match below -- the suggestion is a hint, not ground "
            "truth.\n"
            "Real, live-confirmed extraction mistakes to specifically avoid: "
            "(1) vendor_name must be ONLY the business/company name (e.g. 'Jollibee Foods "
            "Corporation') -- never include the street address, branch location, or store "
            "number; put those in the separate address field instead. "
            "(2) tin is the BIR Tax Identification Number, usually printed near a 'VAT REG "
            "TIN' or 'TIN' label as a series of digits, often with dashes (e.g. "
            "'123-456-789-000'); look for it specifically rather than leaving it blank if "
            "any digit sequence resembling one appears. "
            "(3) or_number is the Official Receipt or Sales Invoice number, usually near an "
            "'OR#'/'SI#'/'Invoice No.' label. "
            "Leave a field as an empty string only if it is genuinely not present in the "
            f"text below, not as a default.\n{hint_line}\nOCR text:\n{raw_text}"
        )
        response = await inference.generate(
            run_id=run_id, user_id=user_id, preset=inference_preset, prompt=prompt,
            response_schema_json=json.dumps(RECEIPT_EXTRACTION_SCHEMA),
            # Real, live-confirmed right-sizing: this schema's own JSON output is a
            # compact single object, not free-form prose -- 1024 tokens was the generic
            # Inference-wide default, not reasoned for this specific call, and let a
            # struggling generation run 2-3x longer than a genuinely complete answer
            # ever needs before finish_reason=LENGTH would even kick in.
            max_tokens=400,
        )
        if response.finish_reason == "error":
            raise RuntimeError(f"inference failed: {response.error_code}: {response.error_detail}")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            # Constrained decoding is a strong guarantee, not an absolute one (deep-dive
            # §5's own honesty about real install failures on some backends) -- a
            # non-JSON response degrades to a real, inspectable raw-text fallback rather
            # than raising the whole receipt into a failed stage over a formatting slip.
            return {"raw_text": response.text}

    async def written() -> str:
        from core.persistence.generated import persistence_pb2 as pb

        raw_text = await _raw_ocr_text()
        inferred_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.INFERRED)
        matched_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.MATCHED)
        geod_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.GEOD)

        fields: dict = {"raw_ocr_text": raw_text}
        if inferred_checkpoint is not None:
            fields.update(inferred_checkpoint.stage_output_ref)
        if matched_checkpoint is not None:
            fields["vendor_match"] = matched_checkpoint.stage_output_ref
        if geod_checkpoint is not None:
            fields["geocode"] = geod_checkpoint.stage_output_ref

        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        receipt = pb.ReceiptMessage(
            receipt_id=receipt_id, user_id=user_id,
            blob=pb.BlobRefMessage(logical_id=source_blob_ref),
            fields_json=json.dumps(fields), schema_version=1,
            created_at=now_iso, updated_at=now_iso,
        )
        response = await persistence.save_receipt(receipt, actor="worker")
        if response.error_code:
            raise RuntimeError(f"save_receipt failed: {response.error_code}: {response.error_detail}")
        return response.receipt_id

    stages: dict[ReceiptStage, object] = {
        ReceiptStage.PREPROCESSED: preprocessed,
        ReceiptStage.OCRD: ocrd,
        ReceiptStage.WRITTEN: written,
    }
    if architect is not None and matching is not None:
        stages[ReceiptStage.MATCHED] = matched
    if geo is not None:
        stages[ReceiptStage.GEOD] = geod
    if inference is not None:
        stages[ReceiptStage.INFERRED] = inferred

    return ReceiptWork(receipt_id=receipt_id, stages=stages, content_hash=content_hash)
