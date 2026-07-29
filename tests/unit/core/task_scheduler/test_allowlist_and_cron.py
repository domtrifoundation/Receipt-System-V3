"""The curated allowlist and cron validation (`v3-deepdive-39-task-scheduler.md` §4, §9, §10).

Two of §9's three named testing hooks live here:

* **Allowlist enforcement test** — "confirms `action` values outside the registered allowlist
  are rejected at creation time, never silently accepted and failing later at dispatch."
* **Cron-expression validation test** — "malformed expressions rejected at the API boundary,
  not surfaced as a confusing failure at the next expected run time."

Both share a shape worth naming: the failure they prevent is not "the wrong thing happens",
it is "the wrong thing happens *later*, somewhere the user cannot connect back to what they
did". A scheduled task that fails at 2am on a Sunday is a support ticket; one rejected at
creation is a form error.

§10's resolved missed-run behaviour is tested in `test_firing.py`.
"""

from __future__ import annotations

import pytest

from core.task_scheduler.contracts import SchedulableAction
from core.task_scheduler.cron import next_after, parse
from core.task_scheduler.errors import (
    InvalidCronExpression,
    TaskLimitExceeded,
    UnknownSchedulableAction,
)
from core.task_scheduler.registry import (
    SchedulableActionRegistry,
    default_registry,
    enforce_task_cap,
)

from .conftest import WEEKLY_SUNDAY_2AM


# ------------------------------------------------------------------- the allowlist


def test_a_registered_action_is_allowed(registry):
    assert registry.is_allowed("full_rescan")
    assert registry.require("full_rescan").name == "full_rescan"


def test_an_unregistered_action_is_rejected(registry):
    """§9's allowlist-enforcement hook.

    §4 is unusually firm about this — "never arbitrary code, never a raw cron-to-shell-command
    mapping" — because the alternative is a string that some dispatcher reads and acts on. The
    rejection has to happen where the user can see it, at creation, not at 2am on a Sunday.
    """
    assert not registry.is_allowed("rm_minus_rf")

    with pytest.raises(UnknownSchedulableAction):
        registry.require("rm_minus_rf")


def test_an_empty_registry_allows_nothing():
    """The startup state, and it must be closed rather than open.

    A registry that allowed everything until something registered would invert §4 exactly
    during the window where nothing has had a chance to constrain it yet.
    """
    empty = SchedulableActionRegistry()

    assert not empty.is_allowed("full_rescan")
    with pytest.raises(UnknownSchedulableAction):
        empty.require("full_rescan")


def test_the_allowlist_is_enumerable_for_the_picker(registry):
    """§7's `ListSchedulableActions` exists so the Interface screen populates its picker.

    That is the same discipline as the allowlist itself: the set of schedulable things is
    visible in one place rather than implicit in whatever a dispatcher happens to accept.
    """
    names = {action.name for action in registry.list()}

    assert names == {"full_rescan", "generate_slsp_export"}


def test_the_default_registry_starts_empty_and_that_is_deliberate():
    """No Core API is wired to register a real action in this build yet.

    So the shipped default rejects every action at creation time rather than accepting
    something because nothing has constrained it yet — the same posture
    `core/health/resource_ledger.py` takes toward Setup's not-yet-existing hardware profile.
    An empty allowlist that denies is the safe state; an absent allowlist that permits is not.
    """
    assert default_registry().list() == ()

    with pytest.raises(UnknownSchedulableAction):
        default_registry().require("full_rescan")


def test_registering_the_same_name_twice_replaces_rather_than_duplicates(registry):
    registry.register(SchedulableAction(name="full_rescan", description="updated"))

    matching = [a for a in registry.list() if a.name == "full_rescan"]
    assert len(matching) == 1
    assert matching[0].description == "updated"


# ------------------------------------------------------------------ per-tier caps


def test_task_cap_rejects_one_past_the_limit():
    """§10's resolved per-tier cap: the mechanism is real, the numbers are Billing's call."""
    with pytest.raises(TaskLimitExceeded):
        enforce_task_cap(current_count=10, limit=10)


def test_task_cap_allows_up_to_the_limit():
    enforce_task_cap(current_count=9, limit=10)


def test_no_limit_means_uncapped():
    """`None` is "this tier has no cap", not "the cap is zero"."""
    enforce_task_cap(current_count=10_000, limit=None)


# ------------------------------------------------------------------------- cron


def test_a_valid_expression_parses():
    assert parse(WEEKLY_SUNDAY_2AM).matches(
        __import__("datetime").datetime(
            2026, 8, 2, 2, 0, tzinfo=__import__("datetime").timezone.utc
        )
    )


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "not cron at all",
        "0 2 * *",
        "0 2 * * * *",
        "60 2 * * 0",
        "0 24 * * 0",
        "0 2 32 * 0",
        "0 2 * 13 0",
        "0 2 * * 8",
        "*/0 2 * * 0",
    ],
)
def test_malformed_expressions_are_rejected_at_the_boundary(expression):
    """§9's cron-validation hook, over every way a field can be wrong.

    Parametrised rather than written out because the failure mode is uniform and the coverage
    is the point: an out-of-range minute and a missing field are the same class of user error,
    and both must fail here rather than at the next expected run time.
    """
    with pytest.raises(InvalidCronExpression):
        parse(expression)


def test_next_after_finds_the_deep_dive_s_own_sunday_example():
    """§1's literal example: "run a full rescan every Sunday at 2am"."""
    from datetime import datetime, timezone

    following = next_after(WEEKLY_SUNDAY_2AM, datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc))

    assert following == datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc)
    assert following.weekday() == 6


def test_next_after_is_strictly_after_its_argument():
    """The property the whole firing loop rests on.

    If `next_after` could return the moment it was given, `evaluate` would keep finding the
    same occurrence due and fire it forever.
    """
    from datetime import datetime, timezone

    exact = datetime(2026, 8, 2, 2, 0, tzinfo=timezone.utc)

    assert next_after(WEEKLY_SUNDAY_2AM, exact) > exact


def test_step_and_list_syntax_are_supported():
    """A friendly schedule-builder (§6) generates these, so they have to actually work."""
    from datetime import datetime, timezone

    quarter_hourly = parse("*/15 * * * *")

    assert quarter_hourly.matches(datetime(2026, 8, 2, 3, 15, tzinfo=timezone.utc))
    assert not quarter_hourly.matches(datetime(2026, 8, 2, 3, 16, tzinfo=timezone.utc))

    weekdays = parse("0 9 * * 1,3,5")
    assert weekdays.matches(datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc))
    assert not weekdays.matches(datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc))
