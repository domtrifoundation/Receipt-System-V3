"""Firing, misfire policy and the trigger registry (§5, §9, §10).

§10's resolved missed-run question is the load-bearing behaviour here, and it is worth
restating because it is counter-intuitive: a missed occurrence **does not catch up**. The
reasoning is a real failure mode, not simplicity for its own sake — an extended outage would
otherwise release a flood of simultaneous catch-up jobs the moment the instance came back,
competing for resources exactly when the system is already recovering.

§9's sleep/wake correctness hook is the other half: a task scheduled against a service that is
currently asleep must still fire, because §5's whole correction is that a sleeping process
cannot run its own polling loop to notice its own schedule.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.task_scheduler.errors import TriggerUnavailable
from core.task_scheduler.firing import DEFAULT_GRACE, evaluate
from core.task_scheduler.triggers.base import TriggerRegistry

from .conftest import WEEKLY_SUNDAY_2AM, RecordingTrigger, run, task

SUNDAY_2AM = datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_a_task_not_yet_due_does_not_fire():
    decision = evaluate(WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=SATURDAY)

    assert not decision.should_fire
    assert not decision.missed
    assert decision.next_check_after == SUNDAY_2AM


def test_a_task_checked_exactly_on_time_fires():
    decision = evaluate(WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=SUNDAY_2AM)

    assert decision.should_fire
    assert not decision.missed


def test_a_task_checked_within_the_grace_window_still_fires():
    """A real wake mechanism has jitter of its own.

    A check landing a few seconds after the scheduled minute must not be treated as a missed
    run over that jitter alone — otherwise every occurrence is at the mercy of timer accuracy.
    """
    decision = evaluate(
        WEEKLY_SUNDAY_2AM,
        last_evaluated_at=SATURDAY,
        now=SUNDAY_2AM + timedelta(seconds=30),
    )

    assert decision.should_fire


def test_a_late_check_does_not_catch_up():
    """§10's resolved answer, and the single most important behaviour in this module.

    The instance was down for three days. The occurrence it missed is gone — it does not fire
    on return. Firing it would be the start of the catch-up flood §10 rejects, and with a
    daily or hourly schedule the backlog would be proportional to the outage.
    """
    three_days_late = SUNDAY_2AM + timedelta(days=3)

    decision = evaluate(WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=three_days_late)

    assert not decision.should_fire
    assert decision.missed
    assert decision.next_check_after > three_days_late


def test_a_missed_run_skips_to_the_next_future_occurrence_not_the_missed_one():
    """The skip target matters as much as the skip.

    Returning the missed occurrence as `next_check_after` would leave the very next check
    finding it due all over again — a catch-up run reintroduced by accident, one call later.
    """
    late = SUNDAY_2AM + timedelta(days=3)

    decision = evaluate(WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=late)

    assert decision.next_check_after == datetime(2026, 8, 9, 2, 0, tzinfo=timezone.utc)


def test_a_long_outage_loses_one_occurrence_not_a_backlog_of_them():
    """The concrete shape of the flood §10 exists to prevent.

    An hourly task down for a week would otherwise have ~168 runs queued the instant it came
    back. Driving the loop the way a real dispatcher does shows it firing at most once.
    """
    hourly = "0 * * * *"
    started = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    back_online = started + timedelta(days=7)

    fires = 0
    cursor = started
    for _ in range(10):
        decision = evaluate(hourly, last_evaluated_at=cursor, now=back_online)
        cursor = decision.next_check_after
        if decision.should_fire:
            fires += 1
        if not decision.should_fire and not decision.missed:
            break

    assert fires <= 1


def test_repeated_checks_do_not_fire_the_same_occurrence_twice():
    """The partitioning property `evaluate`'s own docstring describes.

    A dispatcher that checks more often than the schedule fires must not re-fire what it
    already ran — which is why the fire case returns the occurrence that just fired as
    `next_check_after`, so the following call searches strictly past it.
    """
    first = evaluate(WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=SUNDAY_2AM)
    assert first.should_fire

    second = evaluate(
        WEEKLY_SUNDAY_2AM,
        last_evaluated_at=first.next_check_after,
        now=SUNDAY_2AM + timedelta(seconds=5),
    )

    assert not second.should_fire
    assert not second.missed


def test_the_grace_boundary_is_where_on_time_becomes_missed():
    """Asserted from both sides, since an off-by-one here silently changes the policy."""
    on_time = evaluate(
        WEEKLY_SUNDAY_2AM, last_evaluated_at=SATURDAY, now=SUNDAY_2AM + DEFAULT_GRACE
    )
    just_late = evaluate(
        WEEKLY_SUNDAY_2AM,
        last_evaluated_at=SATURDAY,
        now=SUNDAY_2AM + DEFAULT_GRACE + timedelta(seconds=1),
    )

    assert on_time.should_fire
    assert just_late.missed


# --------------------------------------------------------------- the trigger registry


def test_a_registered_trigger_receives_the_task():
    registry = TriggerRegistry()
    trigger = RecordingTrigger()
    registry.register(trigger)

    result = run(registry.arm("recording", task()))

    assert result.ok
    assert trigger.registered == ["task-1"]


def test_the_sleeping_service_case_still_registers_a_wake():
    """§9's sleep/wake correctness hook, at the level this package owns.

    §5's correction is that a sleeping dispatcher cannot poll its own schedule — so the task
    has to be handed to something always-resident. What this asserts is the part inside this
    boundary: registration reaches the trigger regardless of the dispatcher's own sleep state,
    since nothing here consults it. Supervisor's own wake grant is its deep-dive's to prove.
    """
    registry = TriggerRegistry()
    supervisor_like = RecordingTrigger()
    registry.register(supervisor_like)
    sleeping_service_task = task(task_id="nightly", cron_expression="0 3 * * *")

    result = run(registry.arm("recording", sleeping_service_task))

    assert result.ok
    assert supervisor_like.registered == ["nightly"]


def test_an_unavailable_trigger_degrades_rather_than_crashing_the_scheduler():
    """`docs/PRINCIPLES.md` §4.4: an unavailable provider is an unavailable trigger.

    A self-hosted install whose OS-native scheduler is not reachable must not take the whole
    scheduler down — the task simply is not armed, and the result says so as data.
    """
    registry = TriggerRegistry()
    registry.register(RecordingTrigger(available=False))

    result = run(registry.arm("recording", task()))

    assert not result.ok
    assert result.error_code


def test_arming_against_an_unknown_provider_is_reported_not_silently_accepted():
    """Silently accepting would leave a user with a task that never runs and no reason why."""
    registry = TriggerRegistry()

    result = run(registry.arm("supervisor_wake", task()))

    assert not result.ok
    assert result.error_code


def test_deregistration_reaches_the_trigger():
    registry = TriggerRegistry()
    trigger = RecordingTrigger()
    registry.register(trigger)
    run(registry.arm("recording", task()))

    result = run(registry.disarm("recording", "task-1"))

    assert result.ok
    assert trigger.deregistered == ["task-1"]


def test_trigger_unavailable_is_an_error_type_not_a_bare_exception():
    """Errors are data at the boundary (§4.1); the internal type still exists to tell cases
    apart, which is exactly what `errors.py`'s hierarchy is for."""
    assert issubclass(TriggerUnavailable, Exception)
