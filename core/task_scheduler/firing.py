"""§5/§10's misfire policy — whether a task is due *right now*, made a checkable value.

**Not in the deep-dive's §2 package layout.** §5 fixes a real bug (a sleeping dispatcher
cannot poll its own schedule) with a Provider Registry of *wake* mechanisms
(`triggers/base.py`), but something still has to decide, once a wake happens, whether the
task is actually due — and §10 resolves that decision with a specific, non-obvious answer:
"waits for the next scheduled occurrence, never catches up immediately." That is a real
policy with a real edge case (how late is still "on time"?), not a one-line check, and three
different triggers all need the identical answer to it — one function here is what stops
`InAppTimerTrigger`, `SupervisorWakeTrigger`, and `OSNativeSchedulerTrigger` from each
implementing a slightly different opinion about lateness.

**The concrete failure mode this exists to prevent, stated in full.** An earlier, simpler
design would have each trigger ask "is `next_after(cron, last_fired)` before `now`?" and fire
if so. That is exactly wrong for a dispatcher that just woke from an extended sleep: if the
scheduled moment was hours or days ago, that check still says "yes, fire" — and if the
dispatcher had *also* missed several earlier occurrences while asleep, a naive loop firing
"every occurrence between last_fired and now" would fire a burst of catch-up runs the moment
the process wakes, competing for resources exactly when the system is already recovering from
downtime. §10 rejects that outcome by name. `evaluate()` below is what a naive per-occurrence
loop would have to get right and does not, by construction: it only ever asks about the *one*
most recent occurrence, and a check arriving after that occurrence's own grace window has
elapsed treats it as permanently missed rather than something to make up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .contracts import FireDecision
from .cron import next_after

#: How late a check may run and still count as "on time" for the occurrence it was checking.
#: Not zero: a real wake mechanism (an in-process timer tick, Supervisor's own wake grant) has
#: some jitter of its own, and a check evaluated a few seconds after the exact scheduled
#: minute must not be treated as a missed run over that jitter alone. Not large either — this
#: is the boundary between "on time" and "the whole reason §10 exists", so it stays a small,
#: fixed default rather than something a caller is invited to widen away the guarantee with.
DEFAULT_GRACE = timedelta(minutes=1)


def evaluate(
    cron_expression: str,
    last_evaluated_at: datetime,
    now: datetime,
    *,
    grace: timedelta = DEFAULT_GRACE,
) -> FireDecision:
    """Should a task last evaluated at `last_evaluated_at` fire when checked at `now`?

    `last_evaluated_at` is not "the last time it fired" in general — it is "the last
    occurrence this function has already accounted for" (fired, or explicitly marked
    missed), and every candidate this call considers is computed **strictly after** it. That
    is what makes repeated calls safe from a cold start: the very first call for a brand-new
    task passes the task's own `created_at`, and every subsequent call passes whatever
    `next_check_after` the previous call returned — including the fire case, where
    `next_check_after` is the occurrence that *just* fired, not a future one, precisely so
    the next call searches strictly past it instead of finding the same occurrence due all
    over again. The occurrence space is partitioned into non-overlapping windows this way:
    nothing double-counted, and nothing skipped except a genuinely late check
    (`missed=True` below).

    Three outcomes, and only three:
    - **Not yet due** (`scheduled > now`): nothing fires; check again no earlier than
      `scheduled` itself.
    - **Due, and checked within `grace`** (`now - scheduled <= grace`): fires now; the next
      call should be evaluated relative to this same `scheduled` moment, since it is the one
      that just fired.
    - **Missed** (`now - scheduled > grace`): does **not** fire — §10's own resolved answer —
      and skips straight to the next future occurrence after `now`, never the one that was
      missed. Reported as `missed=True` so a caller may choose to log it, but it is not an
      error: an extended outage losing one occurrence is the intended behaviour, not a bug.
    """
    scheduled = next_after(cron_expression, last_evaluated_at)
    if scheduled > now:
        return FireDecision(should_fire=False, next_check_after=scheduled)
    if now - scheduled <= grace:
        return FireDecision(should_fire=True, next_check_after=scheduled)
    following = next_after(cron_expression, now)
    return FireDecision(should_fire=False, next_check_after=following, missed=True)


__all__ = ["DEFAULT_GRACE", "evaluate"]
