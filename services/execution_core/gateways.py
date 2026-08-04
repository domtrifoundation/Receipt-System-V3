"""Real gRPC-backed collaborators for `pipeline.Pipeline` — the actual missing piece
between "every stage's own API works in isolation" and "a real uploaded receipt goes
through OCR and comes out the other side as a persisted record." Confirmed live before
this file existed: `ExecutionCoreService.StartRun` only ever tracked run metadata
(debounce coalescing, state), and nothing anywhere constructed a real `ReceiptWork` with
real stage closures — `pipeline.process_run` was real, tested, orchestration logic that
nothing in the running system ever called.

**Honest, stated scope for this pass**: real gRPC gateways exist here for Preprocessing,
OCR, and Persistence — enough to rasterize a source blob, OCR it, and save a receipt
record carrying the raw OCR text. `receipt_orchestration.build_receipt_work()` wires only
the `preprocessed`/`ocrd`/`written` stages; `matched`/`geod`/`inferred` are left
unregistered, and `pipeline.process_receipt` already skips any stage with no registered
function (`fn = work.stages.get(stage); if fn is None: continue`), so a receipt reaches
`WRITTEN` with real OCR text captured but no vendor match, no geocoded address, and no
LLM-structured field extraction yet. Wiring those three is the identical mechanical
pattern demonstrated here, applied to Matching/Geo/Inference.

**`CheckpointStore`/`AttemptCounter` are in-memory only, not yet durable via Persistence**
— a real, honestly-stated gap: `persistence.proto` has no checkpoint-storage RPC at all
today, so there is nothing to build a real gRPC-backed implementation against yet. These
in-memory versions are real and correct *within one running process's lifetime* (a
receipt genuinely won't be reprocessed twice in the same run), they just don't survive a
restart. `ReviewFlagger` **is** real and gRPC-backed — Review/Flagging's `CreateFlag` RPC
already exists and this is a direct, unmodified adapter to it.
"""

from __future__ import annotations

from services.execution_core.contracts import ReceiptStage, StageCheckpoint

__all__ = [
    "GrpcOcrGateway",
    "GrpcPersistenceGateway",
    "GrpcPreprocessingGateway",
    "GrpcReviewFlagger",
    "InMemoryAttemptCounter",
    "InMemoryCheckpointStore",
]


class InMemoryCheckpointStore:
    """Real within one process's lifetime — see the module docstring for why this isn't
    yet backed by Persistence."""

    def __init__(self) -> None:
        self._by_receipt_stage: dict[tuple[str, str], StageCheckpoint] = {}
        self._by_content_hash: dict[str, StageCheckpoint] = {}

    async def get_checkpoint(self, receipt_id: str, stage: ReceiptStage) -> StageCheckpoint | None:
        return self._by_receipt_stage.get((receipt_id, stage.value))

    async def write_checkpoint(self, checkpoint: StageCheckpoint) -> None:
        self._by_receipt_stage[(checkpoint.receipt_id, checkpoint.stage.value)] = checkpoint
        if checkpoint.content_hash:
            self._by_content_hash[checkpoint.content_hash] = checkpoint

    async def find_written_by_content_hash(self, content_hash: str) -> StageCheckpoint | None:
        found = self._by_content_hash.get(content_hash)
        if found is not None and found.stage is ReceiptStage.WRITTEN:
            return found
        return None


class InMemoryAttemptCounter:
    """Real within one process's lifetime — see the module docstring."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._escalated: set[tuple[str, str]] = set()

    async def get_attempt_count(self, receipt_id: str, stage: ReceiptStage) -> int:
        return self._counts.get((receipt_id, stage.value), 0)

    async def increment_attempt_count(self, receipt_id: str, stage: ReceiptStage) -> int:
        key = (receipt_id, stage.value)
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def already_escalated(self, receipt_id: str, stage: ReceiptStage) -> bool:
        return (receipt_id, stage.value) in self._escalated

    async def mark_escalated(self, receipt_id: str, stage: ReceiptStage) -> None:
        self._escalated.add((receipt_id, stage.value))


class GrpcReviewFlagger:
    """A direct, unmodified adapter to Review/Flagging's real `CreateFlag` RPC — the one
    collaborator in this file that needed no new backend work at all."""

    def __init__(self, address: str) -> None:
        self._address = address

    async def create_flag(self, receipt_id: str, flag_type: str, details=None) -> None:
        import grpc

        from core.review_flagging.generated import review_flagging_pb2 as pb
        from core.review_flagging.generated import review_flagging_pb2_grpc as pb_grpc

        payload = {str(k): str(v) for k, v in (details or {}).items()}
        async with grpc.aio.insecure_channel(self._address) as channel:
            await pb_grpc.ReviewFlaggingServiceStub(channel).CreateFlag(
                pb.CreateFlagRequest(flag_type=flag_type, receipt_id=receipt_id, created_by="execution_core", payload=payload)
            )


class GrpcPreprocessingGateway:
    def __init__(self, address: str) -> None:
        self._address = address

    async def rasterize(self, *, run_id: str, user_id: str, source_blob_ref: str, page_index: int = 0, scale: float = 2.5):
        import grpc

        from core.preprocessing.generated import preprocessing_pb2 as pb
        from core.preprocessing.generated import preprocessing_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._address) as channel:
            return await pb_grpc.PreprocessingServiceStub(channel).Rasterize(pb.RasterizeRequest(
                run_id=run_id, user_id=user_id, source_blob_ref=source_blob_ref, page_index=page_index, scale=scale,
            ))


class GrpcOcrGateway:
    def __init__(self, address: str) -> None:
        self._address = address

    async def read(self, *, run_id: str, user_id: str, blob_ref: str, engines: tuple[str, ...] = (), timeout_ms: int = 30000):
        import grpc

        from core.ocr.generated import ocr_pb2 as pb
        from core.ocr.generated import ocr_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._address) as channel:
            return await pb_grpc.OcrServiceStub(channel).Read(pb.OcrReadRequest(
                run_id=run_id, user_id=user_id, blob_ref=blob_ref, engines=list(engines), timeout_ms=timeout_ms,
            ))


class GrpcPersistenceGateway:
    def __init__(self, address: str) -> None:
        self._address = address

    async def save_receipt(self, receipt_message, *, actor: str = "worker"):
        import grpc

        from core.persistence.generated import persistence_pb2 as pb
        from core.persistence.generated import persistence_pb2_grpc as pb_grpc

        async with grpc.aio.insecure_channel(self._address) as channel:
            return await pb_grpc.PersistenceServiceStub(channel).SaveReceipt(
                pb.SaveReceiptRequest(receipt=receipt_message, actor=actor)
            )
