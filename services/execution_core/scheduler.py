"""Run scheduling: the two concurrency axes and the debounce coalescer (§5).

Two independent mechanisms live here because they answer two different questions. `RunScheduler`
answers *may this run start now* (§5.1). `RunCoalescer` answers *which run do these newly
arrived files belong to* (§5.2). Neither is a special case of the other, and merging them would
make the debounce ceiling a function of how busy the machine is — which is precisely the thing
§5.2 says it must not be.

**The clock is injected.** §5.2's ceiling defaults to 120 seconds, and a test that proves "a
continuous trickle of triggers never blocks the run forever" cannot be allowed to take two
minutes to say so — nor can it be allowed to prove it by sleeping less and hoping. A callable
returning the current time makes the ceiling test exact rather than approximate, and costs
nothing in production where the callable is `utcnow`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from .contracts import DebounceConfig, Run, RunState, utcnow
from .state_machine import accepts_new_files, transition

Clock = Callable[[], datetime]


class RunScheduler:
    """§5.1's two independent concurrency knobs.

    A run needs capacity on *both* axes to start. Per-user defaults to 1 and doubles as rate
    limiting (file 03); global protects the shared OCR/Inference hardware regardless of how many
    distinct users are asking at once — one busy user and eight idle ones must not be able to
    saturate the GPU between them any more than eight busy users can.

    **Acquisition order is fixed: global first, then per-user.** Not an aesthetic choice. Two
    coroutines taking the same two locks in opposite orders is the textbook deadlock, and the
    only defence is that every path through this class takes them in one order. The release path
    is the reverse, in a `finally`, so a cancelled or failing run never strands a slot — the
    stranded-reservation failure Health's own ledger needed a TTL sweep to survive.
    """

    def __init__(self, per_user_limit: int = 1, global_limit: int = 8) -> None:
        if per_user_limit < 1 or global_limit < 1:
            raise ValueError("concurrency limits must be at least 1")
        self._per_user_limit = per_user_limit
        self._global_limit = global_limit
        self._per_user_semaphores: dict[str, asyncio.Semaphore] = {}
        self._global_semaphore = asyncio.Semaphore(global_limit)
        self._in_flight: dict[str, int] = {}

    @property
    def per_user_limit(self) -> int:
        return self._per_user_limit

    @property
    def global_limit(self) -> int:
        return self._global_limit

    def in_flight_for(self, user_id: str) -> int:
        """How many of this user's runs currently hold a slot. Observability, not a gate."""
        return self._in_flight.get(user_id, 0)

    def _semaphore_for(self, user_id: str) -> asyncio.Semaphore:
        """This user's semaphore, created on first sight.

        Created lazily rather than pre-populated because the user set is unbounded and only
        known at runtime; a dict of every user who ever triggered a run is a slow leak, but a
        semaphore per *active* user is bounded by the global limit in practice.
        """
        existing = self._per_user_semaphores.get(user_id)
        if existing is None:
            existing = asyncio.Semaphore(self._per_user_limit)
            self._per_user_semaphores[user_id] = existing
        return existing

    @asynccontextmanager
    async def acquire(self, user_id: str):
        """Hold both axes for the duration of the block.

        Yields nothing useful — the value is the holding, not the object. Written as a context
        manager rather than an acquire/release pair so that an exception raised inside a run
        cannot skip the release; §5.1's sketch is an `AsyncContextManager` for the same reason.
        """
        await self._global_semaphore.acquire()
        user_semaphore = self._semaphore_for(user_id)
        try:
            await user_semaphore.acquire()
        except BaseException:
            self._global_semaphore.release()
            raise
        self._in_flight[user_id] = self._in_flight.get(user_id, 0) + 1
        try:
            yield self
        finally:
            remaining = self._in_flight.get(user_id, 1) - 1
            if remaining <= 0:
                self._in_flight.pop(user_id, None)
            else:
                self._in_flight[user_id] = remaining
            user_semaphore.release()
            self._global_semaphore.release()


@dataclass(frozen=True)
class TriggerOutcome:
    """What a trigger did (§5.2) — errors and decisions as data (`docs/PRINCIPLES.md` §4.1).

    `started_new_run` and `joined_existing` are separate booleans rather than one enum-shaped
    string because a caller usually wants only one of them, and the third case — a late file
    arriving after the ceiling forced `CLOSING`, which starts a *new* run — is both a new run
    and a rejection of the old one at once.
    """

    run: Run
    started_new_run: bool
    joined_existing: bool
    ceiling_reached: bool = False


class RunCoalescer:
    """§5.2's debounce-with-max-wait.

    The mechanism in one sentence: each trigger pushes the window out, and the ceiling — measured
    from the run's own `opened_at`, never from the most recent trigger — pulls it closed anyway.
    Measuring the ceiling from the latest trigger instead is the bug this design exists to
    prevent: a continuous trickle of arrivals would keep a run open forever and its receipts
    would never be written.

    **This lives in Execution Core, not in Ingestion's Webhook Subscription Manager.** That
    component only ever emits "new file available" (file 01); deciding how raw events batch into
    an actual run is this API's own boundary, and putting it in Ingestion would give every
    ingestion source its own opinion about batching.
    """

    def __init__(
        self,
        config: DebounceConfig | None = None,
        *,
        clock: Clock = utcnow,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config or DebounceConfig()
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._open_runs: dict[str, Run] = {}
        self._closed_runs: list[Run] = []

    @property
    def config(self) -> DebounceConfig:
        return self._config

    def open_run_for(self, user_id: str) -> Run | None:
        """This user's currently-open run, if any."""
        return self._open_runs.get(user_id)

    def on_trigger(self, user_id: str, file_count: int = 1) -> TriggerOutcome:
        """Route newly-arrived files into a run, opening one if needed.

        Three cases, and the third is the one §5.2 is emphatic about:

        1. No open run — open one, start the window and stamp the ceiling.
        2. An open run whose ceiling has not passed — extend the window, but never past the
           ceiling.
        3. An open run whose ceiling *has* passed — force it to `CLOSING` and start a **new**
           run for these files. §5.2: "the ceiling is a real boundary, not advisory."

        Deliberately synchronous. There is no I/O here — it is arithmetic on timestamps and a
        dict update — and making it `async` would invite a caller to believe it awaits something.
        """
        now = self._clock()
        existing = self._open_runs.get(user_id)

        if existing is None or not accepts_new_files(existing):
            return TriggerOutcome(
                run=self._open_new_run(user_id, now, file_count),
                started_new_run=True,
                joined_existing=False,
            )

        ceiling = existing.ceiling_at
        if ceiling is not None and now >= ceiling:
            closed = transition(existing, RunState.CLOSING)
            self._open_runs.pop(user_id, None)
            self._closed_runs.append(closed.run)
            return TriggerOutcome(
                run=self._open_new_run(user_id, now, file_count),
                started_new_run=True,
                joined_existing=False,
                ceiling_reached=True,
            )

        extended = now + timedelta(seconds=self._config.window_seconds)
        if ceiling is not None and extended > ceiling:
            extended = ceiling
        joined = Run(
            run_id=existing.run_id,
            user_id=existing.user_id,
            state=existing.state,
            opened_at=existing.opened_at,
            closing_started_at=existing.closing_started_at,
            receipt_count=existing.receipt_count + file_count,
            window_expires_at=extended,
            ceiling_at=existing.ceiling_at,
        )
        self._open_runs[user_id] = joined
        return TriggerOutcome(run=joined, started_new_run=False, joined_existing=True)

    def _open_new_run(self, user_id: str, now: datetime, file_count: int) -> Run:
        run = Run(
            run_id=self._id_factory(),
            user_id=user_id,
            state=RunState.OPEN,
            opened_at=now,
            receipt_count=file_count,
            window_expires_at=now + timedelta(seconds=self._config.window_seconds),
            ceiling_at=now + timedelta(seconds=self._config.max_wait_seconds),
        )
        self._open_runs[user_id] = run
        return run

    def due_for_closing(self) -> tuple[Run, ...]:
        """Every open run that should now transition to `CLOSING`.

        Two independent reasons qualify a run, and both are checked because either alone leaves
        a real hole: the debounce window elapsing (the quiet case — no new files arrived) and the
        ceiling being reached (the trickle case — files keep arriving and never stop). A
        scheduler that only checked the window would hold a trickling run open indefinitely,
        which is the exact failure §5.2's ceiling exists to prevent.
        """
        now = self._clock()
        due: list[Run] = []
        for run in self._open_runs.values():
            window_elapsed = run.window_expires_at is not None and now >= run.window_expires_at
            ceiling_hit = run.ceiling_at is not None and now >= run.ceiling_at
            if window_elapsed or ceiling_hit:
                due.append(run)
        return tuple(due)

    def close(self, run: Run) -> Run:
        """Transition a run into `CLOSING` and stop routing new files to it."""
        result = transition(run, RunState.CLOSING)
        self._open_runs.pop(run.user_id, None)
        self._closed_runs.append(result.run)
        return result.run

    def close_due(self) -> tuple[Run, ...]:
        """Close everything `due_for_closing` reports, and return what was closed."""
        return tuple(self.close(run) for run in self.due_for_closing())

    def closed_runs(self) -> tuple[Run, ...]:
        """Runs this coalescer has moved into `CLOSING`, in the order it closed them."""
        return tuple(self._closed_runs)


__all__ = ["Clock", "RunCoalescer", "RunScheduler", "TriggerOutcome"]
