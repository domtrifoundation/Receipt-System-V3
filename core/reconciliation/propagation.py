"""§3 — correction propagation, with §8's resolved atomicity mechanism.

When Architect's registry data changes — a vendor's TIN gets fixed, a branch gets merged — every
receipt already in the canonical database that references that entity needs the correction
applied. §3 has Reconciliation subscribing to those change events (Historian's event stream,
filtered to Architect's tables) rather than polling.

**§8 resolves atomicity by reuse, and the reuse is the whole point.** Its words: bulk propagation
"reuses Execution Core's own `run_stage()`/checkpoint mechanism directly — each receipt in a
propagation batch gets its own checkpoint record, so an interrupted batch resumes from the last
successfully-propagated receipt rather than restarting or silently skipping ones already done.
**The same mechanism, not a second implementation of 'resume after a crash.'**"

That function arrives here injected rather than imported. `contracts.py` is the only module other
packages import from (`docs/PRINCIPLES.md` §1.1), and a direct import of
`services.execution_core.checkpointing` would both breach that and make this package unimportable
wherever Execution Core is not installed (§1.3). What §1.9 actually demands is that the function
*be* the identical one — which is a property of the wiring, pinned by a test asserting object
identity, not a property this file can assert about itself.

**A conflict is never silently overridden** (`docs/PRINCIPLES.md` §4.3). If Persistence reports
that a receipt's current value disagrees with what the correction assumes it was replacing, that
receipt is recorded in `PropagationJob.conflicts` and left alone for a human. The alternative —
a bulk sweep quietly overwriting a value someone had already corrected by hand — is the exact
shape §4.3 exists to forbid, and at bulk-propagation scale it would do it to thousands of rows
before anyone noticed.

**Corrections go through Persistence's normal write path**, per §3, so each one is automatically
Historian-logged with `actor: "worker"` and stays distinguishable from a human's direct edit. A
bulk-update shortcut would be faster and would make every propagated correction look like
someone had typed it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from common.frozen_dict import FrozenDict

from .contracts import PropagationJob, ReceiptWriter
from .metrics import ReconciliationMetricsCollector

#: The checkpoint "stage" every propagation records under. One stage rather than a per-entity
#: name so a resumed batch asks a single question per receipt — "has this receipt already had
#: this job applied" — rather than needing to reconstruct which stage name a crashed run chose.
PROPAGATION_STAGE = "propagated"

#: The signature of Execution Core's `run_stage` as this module uses it: it takes the work as a
#: keyword-only callable and returns `(value, resumed)`. Injected, never imported — see the
#: module docstring.
StageRunner = Callable[..., Awaitable[tuple[Any, bool]]]


async def propagate_correction(
    *,
    entity_type: str,
    entity_id: str,
    change: FrozenDict,
    receipt_ids: tuple[str, ...],
    writer: ReceiptWriter,
    stage_runner: StageRunner | None = None,
    checkpoint_store: Any = None,
    stage: Any = PROPAGATION_STAGE,
    job_id: str = "",
    metrics: ReconciliationMetricsCollector | None = None,
) -> PropagationJob:
    """Apply `change` to every receipt in `receipt_ids`, resumably.

    Registered as a Background Workers job, class `CPU_PROCESS` when the affected-receipt count
    makes finding and updating them genuine CPU-bound work (§3, and file 02's own table names
    bulk propagation sweeps as a real no-GIL/multiprocessing candidate). **This function does not
    schedule itself** — §1 is explicit that Reconciliation never runs "as a competing scheduler";
    Background Workers owns dispatch, and this is the callable it dispatches.

    When `stage_runner` and `checkpoint_store` are supplied, each receipt's write is wrapped in
    Execution Core's own checkpoint mechanism and an interrupted batch resumes. When they are
    not, the propagation still runs correctly but without resume — reported honestly through
    `receipts_resumed` staying at zero rather than by pretending checkpointing happened.
    """
    collector = metrics or ReconciliationMetricsCollector()
    resolved_job_id = job_id or uuid.uuid4().hex

    propagated = 0
    resumed = 0
    conflicts: list[str] = []
    failure = ""

    for receipt_id in receipt_ids:

        async def _apply(receipt_id: str = receipt_id) -> tuple[bool, str]:
            return await writer.apply_correction(receipt_id, change)

        try:
            if stage_runner is not None and checkpoint_store is not None:
                outcome, was_resumed = await stage_runner(
                    store=checkpoint_store,
                    run_id=resolved_job_id,
                    receipt_id=receipt_id,
                    stage=stage,
                    fn=_apply,
                )
            else:
                outcome, was_resumed = await _apply(), False
        except Exception as exc:  # noqa: BLE001 - errors are data (§4.1)
            failure = f"propagation halted at {receipt_id}: {type(exc).__name__}: {exc}"
            break

        applied, conflict_detail = _unpack(outcome)

        if was_resumed:
            resumed += 1
            propagated += 1
            collector.record_propagation_resumed()
            continue

        if not applied:
            conflicts.append(receipt_id)
            collector.record_propagation_conflict()
            continue

        propagated += 1
        collector.record_propagation_applied()

    return PropagationJob(
        job_id=resolved_job_id,
        entity_type=entity_type,
        entity_id=entity_id,
        change=change,
        receipts_total=len(receipt_ids),
        receipts_propagated=propagated,
        receipts_resumed=resumed,
        conflicts=tuple(conflicts),
        error=failure,
    )


def _unpack(outcome: Any) -> tuple[bool, str]:
    """Read a writer's `(applied, conflict_detail)` back out.

    Tolerant of a resumed checkpoint replaying its stored value in whatever shape it was
    persisted in — a JSON round-trip turns a tuple into a list, and a resume that then read the
    result as "not applied" would re-apply a correction that had already landed.
    """
    if isinstance(outcome, tuple) and len(outcome) == 2:
        return bool(outcome[0]), str(outcome[1])
    if isinstance(outcome, list) and len(outcome) == 2:
        return bool(outcome[0]), str(outcome[1])
    return bool(outcome), ""


__all__ = ["PROPAGATION_STAGE", "StageRunner", "propagate_correction"]
