"""Task Scheduler's frozen contracts and its per-user store (§3, `docs/PRINCIPLES.md` §2.1).

§3 is explicit that a `UserScheduledTask` lives in **the owning user's own** Persistence
database — "per-user preference data, structurally the same category as any other user-owned
setting". So the store tests are mostly about that scoping holding: one user's schedule must
not be visible or deletable from another's, which is the same per-user isolation Persistence
itself enforces rather than a second model invented here.

The `forward_compat`-marked test covers `UserScheduledTask.action_params`, which is
`FrozenDict`-typed. On 3.15 the builtin `frozendict` is not a `dict` subclass, so an
`isinstance(x, dict)` check against it silently takes the wrong branch — here that would mean
a task's own parameters being dropped on the way to the action that reads them.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.task_scheduler.contracts import FireDecision, SchedulableAction, UserScheduledTask
from core.task_scheduler.errors import ERROR_CODES, ERROR_SUMMARIES
from core.task_scheduler.store import TaskStore

from .conftest import SUNDAY_0100, run, task


@pytest.fixture
def store(tmp_path) -> TaskStore:
    created = TaskStore(top_level=tmp_path)
    yield created
    created.close()


# ------------------------------------------------------------------------ contracts


@pytest.mark.forward_compat
def test_action_params_is_a_mapping_not_a_dict_subclass():
    """The check every consumer must make is `Mapping`, never `dict`.

    An action's own domain logic reads its parameters out of this field. A branch written
    against `dict` would find nothing there on 3.15 and run the action with no parameters,
    which for something like a rescan's `since` bound is a materially different job.
    """
    scheduled = task(params={"since": "2026-01-01"})

    assert isinstance(scheduled.action_params, Mapping)
    assert scheduled.action_params["since"] == "2026-01-01"


@pytest.mark.forward_compat
def test_action_params_cannot_be_mutated_after_the_fact():
    scheduled = task(params={"since": "2026-01-01"})

    with pytest.raises(Exception):
        scheduled.action_params["since"] = "1999-01-01"  # type: ignore[index]


@pytest.mark.forward_compat
def test_error_tables_are_frozen_mappings():
    """§2.1.1: a module-level constant lookup table is a `FrozenDict` too."""
    for table in (ERROR_CODES, ERROR_SUMMARIES):
        assert isinstance(table, Mapping)

    with pytest.raises(Exception):
        ERROR_SUMMARIES["INVALID_CRON_EXPRESSION"] = "changed"  # type: ignore[index]


def test_every_error_code_has_an_operator_summary():
    for code in ERROR_CODES.values():
        assert ERROR_SUMMARIES.get(code)


def test_a_scheduled_task_is_frozen():
    scheduled = task()

    with pytest.raises(Exception):
        scheduled.enabled = False  # type: ignore[misc]


def test_a_fire_decision_is_frozen():
    from datetime import datetime, timezone

    decision = FireDecision(
        should_fire=True, next_check_after=datetime(2026, 8, 2, tzinfo=timezone.utc)
    )

    with pytest.raises(Exception):
        decision.should_fire = False  # type: ignore[misc]


def test_schedulable_action_param_keys_are_informational_not_a_schema():
    """§4's own boundary: this package does not own the action, so it does not own its
    parameter contract either. `param_keys` documents what the action reads; it is not
    validated against, and a test asserting otherwise would be encoding the wrong ownership.
    """
    action = SchedulableAction(name="full_rescan", description="", param_keys=("since",))

    assert action.param_keys == ("since",)


# --------------------------------------------------------------------------- store


def test_a_task_round_trips_through_the_store(store):
    original = task(params={"since": "2026-01-01"})

    run(store.insert(original))
    loaded = run(store.get("user-1", "task-1"))

    assert loaded is not None
    assert loaded.action == "full_rescan"
    assert loaded.cron_expression == original.cron_expression
    assert loaded.action_params["since"] == "2026-01-01"
    assert isinstance(loaded.action_params, Mapping)


def test_one_user_cannot_read_another_user_s_schedule(store):
    """§3: per-user data, not a system-wide setting.

    The isolation is the same one Persistence enforces for every other user-owned record —
    asserted here because this store opens its own per-user database and a path bug would be
    invisible until two real tenants existed.
    """
    run(store.insert(task(task_id="mine", created_by="user-1")))

    assert run(store.get("user-2", "mine")) is None
    assert run(store.list_for_user("user-2")) == []


def test_one_user_cannot_delete_another_user_s_schedule(store):
    run(store.insert(task(task_id="mine", created_by="user-1")))

    deleted = run(store.delete("user-2", "mine"))

    assert not deleted
    assert run(store.get("user-1", "mine")) is not None


def test_listing_returns_only_that_user_s_tasks(store):
    run(store.insert(task(task_id="a", created_by="user-1")))
    run(store.insert(task(task_id="b", created_by="user-1")))
    run(store.insert(task(task_id="c", created_by="user-2")))

    mine = run(store.list_for_user("user-1"))

    assert {t.task_id for t in mine} == {"a", "b"}


def test_updating_a_task_changes_it_in_place(store):
    run(store.insert(task()))
    updated = task(cron_expression="0 3 * * 1", enabled=False)

    changed = run(store.update(updated))
    loaded = run(store.get("user-1", "task-1"))

    assert changed
    assert loaded.cron_expression == "0 3 * * 1"
    assert loaded.enabled is False


def test_updating_a_task_that_does_not_exist_reports_rather_than_creating_one(store):
    """Silently inserting would turn a stale UI update into a task the user never asked for."""
    changed = run(store.update(task(task_id="never-created")))

    assert not changed
    assert run(store.get("user-1", "never-created")) is None


def test_deleting_a_task_removes_it(store):
    run(store.insert(task()))

    deleted = run(store.delete("user-1", "task-1"))

    assert deleted
    assert run(store.get("user-1", "task-1")) is None


def test_counting_is_scoped_per_user_so_the_tier_cap_is_too(store):
    """The cap §10 resolves is per-user, so the count it reads has to be as well.

    A process-wide count would let one heavy tenant exhaust every other tenant's allowance.
    """
    run(store.insert(task(task_id="a", created_by="user-1")))
    run(store.insert(task(task_id="b", created_by="user-1")))
    run(store.insert(task(task_id="c", created_by="user-2")))

    assert run(store.count_for_user("user-1")) == 2
    assert run(store.count_for_user("user-2")) == 1


def test_created_at_survives_the_round_trip(store):
    """`created_at` is what the firing loop's very first evaluation is measured against.

    If the store dropped or re-stamped it, a brand-new task's first occurrence would be
    computed from the wrong origin — silently, and only visibly wrong once.
    """
    run(store.insert(task()))

    loaded = run(store.get("user-1", "task-1"))

    assert loaded.created_at == SUNDAY_0100
