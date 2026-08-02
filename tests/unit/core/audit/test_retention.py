"""The deep-dive's §7 retention-boundary test, plus the §5 policy rules around it.

§7 names two things specifically: that the 10-year default genuinely retains a record at
9 years 11 months, and that `indefinite` mode never purges. Both are here, along with the
§5 rule that retention cannot be quietly configured *below* the BIR baseline.
"""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from core.audit.contracts import (
    DEFAULT_RETENTION_DAYS,
    ActionType,
    AuditQueryFilter,
    RetentionMode,
    RetentionPolicy,
)
from core.audit.errors import (
    E_PURGE_DISABLED,
    E_RETENTION_BELOW_BASELINE,
    E_RETENTION_INVALID,
)
from core.audit.retention import RetentionPurge, horizon, resolve_policy

from .conftest import run, utc

NINE_YEARS_ELEVEN_MONTHS = 3620  # comfortably inside 3650, deliberately close to the edge
TEN_YEARS_ONE_MONTH = 3680


@pytest.fixture
def purger(db_path):
    p = RetentionPurge(db_path)
    yield p
    p.close()


# --------------------------------------------------------------- policy resolution


def test_the_default_is_the_bir_ten_year_baseline():
    resolution = resolve_policy()
    assert resolution.error is None
    assert resolution.policy.retention_days == DEFAULT_RETENTION_DAYS == 3650
    assert resolution.policy.mode is RetentionMode.FIXED


def test_a_longer_period_is_always_allowed():
    assert resolve_policy(7300).policy.retention_days == 7300


def test_indefinite_is_always_allowed():
    resolution = resolve_policy(mode="indefinite")
    assert resolution.error is None and resolution.policy.mode is RetentionMode.INDEFINITE


def test_indefinite_is_allowed_even_carrying_a_stale_short_day_count():
    """Regression. The below-baseline gate belongs to `fixed` mode alone: `indefinite` never
    purges anything, so it retains strictly *more* than the BIR baseline no matter what an
    unused `retention_days` says. Refusing it was refusing the one setting that cannot
    under-retain — and it contradicted `retention.py`'s own docstring, which states that
    switching to indefinite is always permitted."""
    resolution = resolve_policy(30, mode="indefinite")
    assert resolution.error is None, resolution.error_detail
    assert resolution.policy.mode is RetentionMode.INDEFINITE
    assert resolution.policy.shorten_override is False
    assert horizon(resolution.policy) is None


def test_shortening_below_the_baseline_is_refused_without_an_explicit_override():
    """§5 — defaulting downward from a researched legal baseline is exactly the quiet drift
    this project's hygiene discipline exists to prevent. The refusal is data, not an
    exception, and its detail names the regulation."""
    resolution = resolve_policy(365)
    assert resolution.policy is None
    assert resolution.error == E_RETENTION_BELOW_BASELINE
    assert "RR No. 17-2013" in resolution.error_detail or "17-2013" in resolution.error_detail


def test_an_override_without_a_stated_reason_is_still_refused():
    assert resolve_policy(365, shorten_override=True).error == E_RETENTION_BELOW_BASELINE


def test_an_override_with_a_reason_is_honoured_and_recorded_on_the_policy():
    resolution = resolve_policy(
        365, shorten_override=True, shorten_override_reason="jurisdiction has no BIR obligation"
    )
    assert resolution.error is None
    assert resolution.policy.retention_days == 365
    assert resolution.policy.shorten_override is True
    assert resolution.policy.shorten_override_reason


def test_a_nonsense_mode_or_period_is_reported_not_guessed_at():
    assert resolve_policy(mode="forever").error == E_RETENTION_INVALID
    assert resolve_policy(0, shorten_override=True, shorten_override_reason="x").error == (
        E_RETENTION_INVALID
    )


def test_indefinite_mode_has_no_horizon():
    assert horizon(RetentionPolicy(mode=RetentionMode.INDEFINITE)) is None
    assert horizon(RetentionPolicy()) is not None


# ------------------------------------------------------------- purge boundary


def test_a_record_at_nine_years_eleven_months_is_retained(writer, query, purger):
    """The §7 boundary test, stated in its own terms."""
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(NINE_YEARS_ELEVEN_MONTHS)))
    result = run(purger.purge(resolve_policy().policy))
    assert result.error is None and result.purged == 0
    assert run(query.fetch(AuditQueryFilter(), "owner")).total_matching == 1


def test_a_record_past_the_horizon_is_purged(writer, query, purger):
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(TEN_YEARS_ONE_MONTH)))
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(1)))
    result = run(purger.purge(resolve_policy().policy, actor_user_id="system"))
    assert result.error is None and result.purged == 1

    remaining = run(query.fetch(AuditQueryFilter(), "owner"))
    # The recent event, plus the record of the purge itself.
    kinds = sorted(e.action_type.value for e in remaining.events)
    assert kinds == ["config_changed", "retention_purge_executed"]


def test_indefinite_mode_never_purges_anything(writer, query, purger):
    """The other half of §7's own retention test."""
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(365 * 40)))
    result = run(purger.purge(RetentionPolicy(mode=RetentionMode.INDEFINITE)))
    assert result.purged == 0
    assert result.error == E_PURGE_DISABLED
    assert run(query.fetch(AuditQueryFilter(), "owner")).total_matching == 1


def test_a_purge_records_itself(writer, query, purger):
    """The one class of deletion this log permits must not be the one it cannot account
    for. The record carries the count and the horizon actually applied."""
    for _ in range(3):
        run(writer.record_action("role_change", "owner_1", occurred_at=utc(TEN_YEARS_ONE_MONTH)))
    result = run(purger.purge(resolve_policy().policy, actor_user_id="staff_7"))
    assert result.purged == 3

    records = run(
        query.fetch(
            AuditQueryFilter(action_types=(ActionType.RETENTION_PURGE_EXECUTED,)), "owner"
        )
    )
    assert records.total_matching == 1
    record = records.events[0]
    assert record.actor_user_id == "staff_7"
    assert record.details["purged_count"] == 3
    assert record.details["retention_days"] == DEFAULT_RETENTION_DAYS
    assert record.reason


def test_purge_records_are_themselves_exempt_from_purging(writer, purger, query):
    """Otherwise the trail of prunings eventually prunes itself."""
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(TEN_YEARS_ONE_MONTH)))
    run(purger.purge(resolve_policy().policy))

    # Age the purge record itself well past the horizon and sweep again.
    stale = resolve_policy().policy
    later = utc(0) + timedelta(days=DEFAULT_RETENTION_DAYS + 10)
    second = run(purger.purge(stale, now=later))
    assert second.purged == 0

    survivors = run(
        query.fetch(
            AuditQueryFilter(action_types=(ActionType.RETENTION_PURGE_EXECUTED,)), "owner"
        )
    )
    assert survivors.total_matching == 1


def test_an_event_recorded_in_a_non_utc_offset_is_purged_on_its_real_instant(
    writer, purger, query
):
    """Regression, and the sharpest one in this package. `occurred_at` is stored as TEXT, so
    every horizon comparison SQLite makes is *lexical*. An event one hour past the horizon,
    recorded by a caller in `+08:00`, spells that instant as a string seven hours *later*
    than the UTC horizon it is being compared against — so it sorted as newer and survived a
    sweep it should not have. `db.to_storage_ts` normalises to UTC at the single point where
    a timestamp enters storage, which is what makes the lexical comparison agree with the
    real chronology."""
    now = utc(0)
    cutoff = horizon(resolve_policy().policy, now)
    instant = cutoff - timedelta(hours=1)  # genuinely older than the horizon
    run(
        writer.record_action(
            "config_change", "owner_1", occurred_at=instant.astimezone(timezone(timedelta(hours=8)))
        )
    )
    result = run(purger.purge(resolve_policy().policy, now=now))
    assert result.purged == 1, "an event past the horizon survived because of its UTC offset"


def test_an_event_just_inside_the_horizon_in_a_negative_offset_is_retained(writer, purger):
    """The other direction of the same bug: a caller in `-10:00` spelling an instant that is
    still inside the horizon as a string that sorts *older* than the cutoff, and being purged
    early."""
    now = utc(0)
    cutoff = horizon(resolve_policy().policy, now)
    instant = cutoff + timedelta(hours=1)  # still inside the horizon
    run(
        writer.record_action(
            "config_change",
            "owner_1",
            occurred_at=instant.astimezone(timezone(timedelta(hours=-10))),
        )
    )
    assert run(purger.purge(resolve_policy().policy, now=now)).purged == 0


def test_a_no_op_sweep_writes_no_record(writer, query, purger):
    """Recording a no-op purge every sweep would bury the records that matter."""
    run(writer.record_action("config_change", "owner_1"))
    assert run(purger.purge(resolve_policy().policy)).purged == 0
    assert run(query.fetch(AuditQueryFilter(), "owner")).total_matching == 1
