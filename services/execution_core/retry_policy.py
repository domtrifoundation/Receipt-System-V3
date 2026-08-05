"""Bounded retry with escalation (§7).

V2's version of this was a `.failed_attempts.json` sidecar plus a quarantine-after-max-attempts
move into a `failed/` folder. §7 replaces the folder move — which does not fit the folderless,
content-addressable blob model at all — with escalation to a Review/Flagging flag
(`processing_failed_repeatedly`), so a human resolves it rather than a loop retrying forever.

**One correction to §7's own sketch, made deliberately and recorded here rather than silently.**
That sketch reads:

    if attempts >= max_attempts:
        await review_flagging.create_flag(...)
        return None

which creates a *new flag on every subsequent call*. §7's own stated motivating bug is "one bad
scan produced 57 identical warnings in a single session" — the sketch reintroduces exactly that
bug in the code written to fix it, just with flags instead of warnings. The escalation is
therefore latched: `AttemptCounter.mark_escalated` records it, `already_escalated` is checked
first, and a receipt that has given up produces one flag no matter how many times it is swept.

The second correction is the return type. §7's sketch returns `None` on escalation, which no
caller can tell apart from a stage whose genuine output is `None` — and the two demand opposite
handling. `StageAttempt` carries the outcome as data (`docs/PRINCIPLES.md` §4.1) so the
distinction survives the return.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

from .checkpointing import run_stage
from .contracts import (
    AttemptCounter,
    CheckpointStore,
    HistorianNarrator,
    ReceiptStage,
    ReviewFlagger,
    StageAttempt,
    StageCallable,
    StageOutcome,
)
from .errors import CheckpointWriteFailed

#: The flag type §7 names. A module-level constant because Review/Flagging's own queue filters
#: on it — a typo here would produce flags nobody is looking for, which is indistinguishable
#: from no flag at all.
PROCESSING_FAILED_FLAG: str = "processing_failed_repeatedly"


async def attempt_stage(
    *,
    store: CheckpointStore,
    counter: AttemptCounter,
    flagger: ReviewFlagger,
    run_id: str,
    receipt_id: str,
    stage: ReceiptStage,
    fn: StageCallable,
    max_attempts: int = 3,
    narrator: HistorianNarrator | None = None,
    content_hash: str = "",
) -> StageAttempt:
    """One bounded attempt at one stage, escalating instead of retrying forever (§7).

    The order of operations matters and is not interchangeable:

    1. **Cap check first.** A receipt at its cap does no work at all, which is the point — the
       expensive stages are exactly the ones you must not run again on a receipt that has
       already failed three times.
    2. **Escalation is latched.** One flag per receipt-stage, ever. See the module docstring.
    3. **The counter increments on failure, not on entry.** Incrementing on entry would count a
       cancelled or resumed pass as a failed attempt, and three interrupted runs would escalate
       a receipt that never actually failed once.
    """
    if await counter.get_attempt_count(receipt_id, stage) >= max_attempts:
        attempts = await counter.get_attempt_count(receipt_id, stage)
        if not await counter.already_escalated(receipt_id, stage):
            await flagger.create_flag(
                receipt_id,
                PROCESSING_FAILED_FLAG,
                FrozenDict({"stage": stage.value, "attempts": attempts, "run_id": run_id}),
            )
            await counter.mark_escalated(receipt_id, stage)
        return StageAttempt(
            stage=stage,
            outcome=StageOutcome.ESCALATED,
            attempts=attempts,
            error=f"{stage.value} failed {attempts} times; escalated to review",
        )

    try:
        value, resumed = await run_stage(
            store=store,
            run_id=run_id,
            receipt_id=receipt_id,
            stage=stage,
            fn=fn,
            narrator=narrator,
            content_hash=content_hash,
        )
    except CheckpointWriteFailed as exc:
        attempts = await counter.increment_attempt_count(receipt_id, stage)
        return StageAttempt(
            stage=stage, outcome=StageOutcome.FAILED, attempts=attempts, error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - the stage's own failure, turned into data (§4.1)
        attempts = await counter.increment_attempt_count(receipt_id, stage)
        return StageAttempt(
            stage=stage,
            outcome=StageOutcome.FAILED,
            attempts=attempts,
            error=f"{type(exc).__name__}: {exc}",
        )

    return StageAttempt(
        stage=stage,
        outcome=StageOutcome.RESUMED if resumed else StageOutcome.COMPLETED,
        value=value,
        attempts=await counter.get_attempt_count(receipt_id, stage),
    )


__all__ = ["PROCESSING_FAILED_FLAG", "attempt_stage"]
