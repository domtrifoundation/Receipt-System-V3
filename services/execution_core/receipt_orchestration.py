"""Builds the real `ReceiptWork` a receipt is actually processed with — the piece that
was missing entirely (`gateways.py`'s own module docstring has the full account of what
was confirmed live-missing and why). `matched`/`geod`/`inferred` are not registered here
yet; `pipeline.process_receipt` skips any stage with no registered function, so a receipt
reaches `WRITTEN` today with real OCR text captured and no vendor match, geocode, or
LLM-structured extraction. Extending this to those three stages is the identical pattern
already demonstrated for `preprocessed`/`ocrd`/`written`.
"""

from __future__ import annotations

from services.execution_core.contracts import CheckpointStore, ReceiptStage
from services.execution_core.gateways import GrpcOcrGateway, GrpcPersistenceGateway, GrpcPreprocessingGateway
from services.execution_core.pipeline import ReceiptWork

__all__ = ["build_receipt_work"]


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
    """

    async def preprocessed() -> str:
        response = await preprocessing.rasterize(run_id=run_id, user_id=user_id, source_blob_ref=source_blob_ref)
        if response.error_code:
            raise RuntimeError(f"preprocessing failed: {response.error_code}: {response.error_detail}")
        return response.image_blob_ref

    async def ocrd() -> str:
        if ocr_source == "source":
            blob_ref = source_blob_ref
        else:
            checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.PREPROCESSED)
            if checkpoint is None:
                raise RuntimeError("ocrd stage ran before preprocessed checkpoint existed")
            blob_ref = checkpoint.stage_output_ref
        response = await ocr.read(run_id=run_id, user_id=user_id, blob_ref=blob_ref, engines=ocr_engines)
        return response.merged_text

    async def written() -> str:
        from core.persistence.generated import persistence_pb2 as pb

        ocr_checkpoint = await store.get_checkpoint(receipt_id, ReceiptStage.OCRD)
        merged_text = ocr_checkpoint.stage_output_ref if ocr_checkpoint is not None else ""

        # Vendor name/amounts are unknown until Matching/Inference are wired (see this
        # module's own docstring) -- fields_json carries the real raw OCR text so nothing
        # is lost even though it isn't structured yet.
        import json
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        receipt = pb.ReceiptMessage(
            receipt_id=receipt_id, user_id=user_id,
            blob=pb.BlobRefMessage(logical_id=source_blob_ref),
            fields_json=json.dumps({"raw_ocr_text": merged_text}), schema_version=1,
            created_at=now_iso, updated_at=now_iso,
        )
        response = await persistence.save_receipt(receipt, actor="worker")
        if response.error_code:
            raise RuntimeError(f"save_receipt failed: {response.error_code}: {response.error_detail}")
        return response.receipt_id

    return ReceiptWork(
        receipt_id=receipt_id,
        stages={
            ReceiptStage.PREPROCESSED: preprocessed,
            ReceiptStage.OCRD: ocrd,
            ReceiptStage.WRITTEN: written,
        },
        content_hash=content_hash,
    )
