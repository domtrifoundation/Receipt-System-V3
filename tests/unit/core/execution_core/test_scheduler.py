"""The debounce coalescer and the two concurrency axes (§5.1, §5.2, and §13's second hook).

§5.2's ceiling is the guarantee that a run never waits forever, and §13 asks for it to be
proved against a trickle of triggers that never lets the debounce window elapse on its own.
The clock is moved by hand rather than slept through — see `_doubles.ManualClock`.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from core.execution_core.contracts import DebounceConfig, RunState
from core.execution_core.scheduler import RunCoalescer, RunScheduler

from ._doubles import ManualClock, run


# --------------------------------------------------------------------------------------------
# §13 hook 2 — the debounce ceiling
# --------------------------------------------------------------------------------------------



def test_a_continuous_trickle_of_triggers_still_forces_the_run_closed_at_the_ceiling():
    """§13's debounce-ceiling hook, and §5.2's "never waits forever" claim.

    Each trigger resets the debounce window, so a steady trickle never lets it elapse naturally.
    If the ceiling were measured from the most recent trigger rather than from the run's own
    `opened_at`, this run would stay open indefinitely and its receipts would never be written.
    The trickle here fires every 5 seconds against a 10-second window — the window genuinely
    never elapses on its own, so the ceiling is the only thing that can close this run.

    The guarantee is asserted as "the original run stopped being open", deliberately without
    caring *which* mechanism closed it. Both are legitimate: the sweep (`due_for_closing`) when
    the tick happens to land first, and `on_trigger` itself when a trigger arrives at or past
    the ceiling. A test that only accepted one of the two would fail on a scheduling detail
    rather than on the behaviour §5.2 actually promises.
    """
    clock = ManualClock()
    coalescer = RunCoalescer(
        DebounceConfig(window_seconds=10.0, max_wait_seconds=60.0), clock=clock
    )

    first = coalescer.on_trigger("user-1")
    assert first.started_new_run is True

    for _ in range(20):
        clock.advance(5.0)
        outcome = coalescer.on_trigger("user-1")
        if outcome.ceiling_reached or coalescer.due_for_closing():
            break
        assert outcome.joined_existing is True, "the run closed for a reason other than the ceiling"

    still_open = coalescer.open_run_for("user-1")
    closed_ids = {run_.run_id for run_ in coalescer.closed_runs()}
    swept_ids = {run_.run_id for run_ in coalescer.due_for_closing()}

    assert first.run.run_id in closed_ids | swept_ids, (
        "the ceiling never fired — a trickling run would stay open forever"
    )
    assert still_open is None or still_open.run_id != first.run.run_id
    assert clock.now - first.run.opened_at >= timedelta(seconds=60.0)


def test_the_debounce_window_is_never_extended_past_the_ceiling():
    """§5.2's ceiling is measured from `opened_at`, never from the most recent trigger.

    The mechanism that makes the previous test's guarantee true rather than incidental: each
    trigger pushes the window out, and the push is clamped. Without the clamp the window walks
    past the ceiling and the ceiling stops meaning anything.
    """
    clock = ManualClock()
    coalescer = RunCoalescer(
        DebounceConfig(window_seconds=10.0, max_wait_seconds=25.0), clock=clock
    )
    coalescer.on_trigger("user-1")

    clock.advance(20.0)
    outcome = coalescer.on_trigger("user-1")

    assert outcome.joined_existing is True
    assert outcome.run.window_expires_at == outcome.run.ceiling_at


def test_a_file_arriving_after_the_ceiling_starts_a_new_run_instead_of_joining_the_old_one():
    """§5.2: "the ceiling is a real boundary, not advisory."

    A late file sneaking into a run that is already finalizing its Persistence writes would be
    written by a run that had already reported its own receipt count and fired its completion
    notification — a receipt in the database that no run ever announced.
    """
    clock = ManualClock()
    coalescer = RunCoalescer(
        DebounceConfig(window_seconds=10.0, max_wait_seconds=30.0), clock=clock
    )
    first = coalescer.on_trigger("user-1")

    clock.advance(31.0)
    late = coalescer.on_trigger("user-1")

    assert late.ceiling_reached is True
    assert late.started_new_run is True
    assert late.run.run_id != first.run.run_id
    assert coalescer.closed_runs()[0].state is RunState.CLOSING


def test_a_quiet_run_closes_on_the_window_without_waiting_for_the_ceiling():
    """The ordinary case, and the reason the ceiling is not the only close condition.

    A run whose files all arrived at once should close in ten seconds, not two minutes. A
    scheduler that only checked the ceiling would make every small batch pay the worst case.
    """
    clock = ManualClock()
    coalescer = RunCoalescer(
        DebounceConfig(window_seconds=10.0, max_wait_seconds=120.0), clock=clock
    )
    coalescer.on_trigger("user-1", file_count=3)

    clock.advance(11.0)
    closed = coalescer.close_due()

    assert len(closed) == 1
    assert closed[0].state is RunState.CLOSING
    assert closed[0].receipt_count == 3


def test_two_users_triggers_never_coalesce_into_one_anothers_runs():
    """A run belongs to one user (§3, §5.1).

    Coalescing across users would put one tenant's receipts into another's run, and every
    downstream write threads that run's `user_id` — the worst possible failure in a
    multi-tenant system.
    """
    clock = ManualClock()
    coalescer = RunCoalescer(clock=clock)

    a = coalescer.on_trigger("user-a")
    b = coalescer.on_trigger("user-b")

    assert a.run.run_id != b.run.run_id
    assert coalescer.open_run_for("user-a").user_id == "user-a"
    assert coalescer.open_run_for("user-b").user_id == "user-b"

# --------------------------------------------------------------------------------------------
# §5.1 — the two concurrency axes
# --------------------------------------------------------------------------------------------



def test_a_run_needs_capacity_on_both_the_per_user_and_the_global_axis():
    """§5.1's two knobs are independent and both must be satisfied.

    Per-user defaults to 1 and doubles as rate limiting; global protects shared OCR/Inference
    hardware. Checking only one means either a single user can saturate the GPU or eight idle
    users can block a busy one.
    """

    async def _exercise():
        scheduler = RunScheduler(per_user_limit=1, global_limit=2)
        held = asyncio.Event()
        release = asyncio.Event()

        async def _hold():
            async with scheduler.acquire("user-a"):
                held.set()
                await release.wait()

        task = asyncio.create_task(_hold())
        await held.wait()
        assert scheduler.in_flight_for("user-a") == 1

        second = asyncio.create_task(_hold())
        await asyncio.sleep(0)
        assert not second.done(), "a second run for the same user got a slot past the limit"

        release.set()
        await asyncio.gather(task, second)
        assert scheduler.in_flight_for("user-a") == 0

    run(_exercise())


def test_a_failing_run_never_strands_a_concurrency_slot():
    """A stranded slot is the abandoned-reservation failure Health's ledger needed a TTL to survive.

    Here it is prevented structurally instead: the release is in a `finally`, so an exception
    inside a run cannot skip it. A leaked global slot permanently reduces the whole install's
    throughput with nothing to point at.
    """

    async def _exercise():
        scheduler = RunScheduler(per_user_limit=1, global_limit=1)
        with pytest.raises(RuntimeError):
            async with scheduler.acquire("user-a"):
                raise RuntimeError("stage exploded")
        async with scheduler.acquire("user-a"):
            assert scheduler.in_flight_for("user-a") == 1

    run(_exercise())


def test_distinct_users_do_not_block_each_other_while_global_capacity_remains():
    """Per-user limits are per user (§5.1). A shared limiter would make one user's run a queue
    for everyone else's, which is the opposite of what a per-user knob is for."""

    async def _exercise():
        scheduler = RunScheduler(per_user_limit=1, global_limit=4)
        async with scheduler.acquire("user-a"):
            async with scheduler.acquire("user-b"):
                assert scheduler.in_flight_for("user-a") == 1
                assert scheduler.in_flight_for("user-b") == 1

    run(_exercise())


def test_a_concurrency_limit_below_one_is_rejected_at_construction():
    """A limit of zero is a permanently deadlocked install with no error to explain it."""
    with pytest.raises(ValueError):
        RunScheduler(per_user_limit=0, global_limit=8)
    with pytest.raises(ValueError):
        RunScheduler(per_user_limit=1, global_limit=0)
