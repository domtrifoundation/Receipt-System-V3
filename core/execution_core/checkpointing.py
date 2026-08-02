"""Per-stage checkpointing (§6) and run-level idempotency (§4).

§6 calls this "the one genuinely novel technique this session's decision record already
identified", and the motivating V2 behaviour is concrete: V2 retried a whole receipt from
scratch on any failure, throwing away completed expensive steps — especially LLM inference —
every time. `run_stage` is the fix, and it is deliberately a technique rather than a framework
dependency, the same borrowing-the-idea-without-the-operational-weight choice Tool Call made
against LangChain.

**This wrapper is also Historian's narrative emission chokepoint**, and §6 is explicit that this
is reuse by design rather than coincidence. Every pipeline stage's call and output already flow
through here for checkpointing, so extending it to emit narrative gives structural coverage —
OCR, Preprocessing, Inference, Matching and Geo/Address each stay focused on their own domain
and none of them has to remember to call Historian. Coverage that depends on N different APIs'
discipline is coverage that eventually has a hole in it.

Two asymmetries in here are the whole point and are easy to "clean up" into bugs:

* **A checkpoint write failure is fatal to the attempt; a narrative emission failure is not.**
  An uncheckpointed success is indistinguishable from a failure on the next pass, so swallowing
  it means silently redoing the expensive work this file exists to protect. A missing narrative
  line is a gap in a human-readable record — degrade gracefully (`docs/PRINCIPLES.md` §4.4),
  never fail a paid-for OCR run over a log entry.
* **A resumed stage does not re-emit narrative.** It did not happen again. Re-emitting would
  make Historian's record show a receipt being OCR'd twice because the process crashed after,
  which is a false account of what occurred.
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    CheckpointStore,
    HistorianNarrator,
    ReceiptStage,
    StageCallable,
    StageCheckpoint,
    TERMINAL_STAGE,
    utcnow,
)
from .errors import CheckpointWriteFailed


async def already_written(store: CheckpointStore, content_hash: str) -> bool:
    """§4's run-level idempotency check: are these exact bytes already fully in the system?

    **Two distinct concerns, tracked separately and never conflated** (§4). Blob-level dedup —
    same SHA-256, same blob — is Persistence's concern and is about storage. This is the other
    one: has this content already been processed all the way into a database row. A receipt can
    be blob-deduped and still need processing; one that has a `WRITTEN` checkpoint needs
    neither.

    Keyed on content hash rather than mtime, which V2's own `_file_fingerprint()` validated the
    hard way: cloud sync (Drive/OneDrive/Dropbox) touches mtime on bytes that did not change, so
    an mtime-keyed check reprocesses receipts that are already complete — and an empty hash is
    not a match against everything, it is simply not a question that can be answered.
    """
    if not content_hash:
        return False
    existing = await store.find_written_by_content_hash(content_hash)
    return existing is not None and existing.stage is TERMINAL_STAGE


async def run_stage(
    *,
    store: CheckpointStore,
    run_id: str,
    receipt_id: str,
    stage: ReceiptStage,
    fn: StageCallable,
    narrator: HistorianNarrator | None = None,
    content_hash: str = "",
) -> tuple[Any, bool]:
    """Run one stage, or return what it already produced.

    Returns `(output, resumed)`. The second element is not decoration: `retry_policy.py` reports
    `RESUMED` distinctly from `COMPLETED`, and a caller that cannot tell them apart cannot prove
    §6's claim — that a retry after a crash resumes from the last completed stage — because from
    the outside both look like "the stage produced a value".

    A retry lands here, finds the `OCRD` checkpoint present and the `MATCHED` one absent, and
    resumes at `MATCHED`. OCR corroboration and Inference generation are never redone.
    """
    existing = await store.get_checkpoint(receipt_id, stage)
    if existing is not None:
        return existing.stage_output_ref, True

    result = await fn()

    checkpoint = StageCheckpoint(
        receipt_id=receipt_id,
        run_id=run_id,
        stage=stage,
        completed_at=utcnow(),
        stage_output_ref=result,
        content_hash=content_hash,
    )
    try:
        await store.write_checkpoint(checkpoint)
    except Exception as exc:  # noqa: BLE001 - deliberately re-raised as this package's own type
        raise CheckpointWriteFailed(
            f"{stage.value} completed for {receipt_id} but its checkpoint could not be written: "
            f"{exc}"
        ) from exc

    if narrator is not None:
        try:
            await narrator.emit_narrative(run_id, receipt_id, stage, result)
        except Exception:  # noqa: BLE001 - see this module's docstring
            pass

    return result, False


async def completed_stages(
    store: CheckpointStore, receipt_id: str, stages: tuple[ReceiptStage, ...]
) -> tuple[ReceiptStage, ...]:
    """Which of `stages` this receipt has already finished.

    Used by `pipeline.py` for reporting and by tests to state the resume point exactly. Asks the
    store per stage rather than assuming a prefix: a checkpoint set with a hole in it is a real
    state (a stage's write failed while a later one succeeded on an earlier attempt), and
    treating the first miss as the resume point would silently skip everything after it.
    """
    found: list[ReceiptStage] = []
    for stage in stages:
        if await store.get_checkpoint(receipt_id, stage) is not None:
            found.append(stage)
    return tuple(found)


__all__ = ["already_written", "completed_stages", "run_stage"]
