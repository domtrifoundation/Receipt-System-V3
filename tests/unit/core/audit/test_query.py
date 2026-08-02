"""Read access: the staff/owner gate, filtering, and paging.

The role tests are the load-bearing ones. §4 makes audit history staff/owner-only, and the
check must fail *closed* (`docs/PRINCIPLES.md` §4.2) — an unrecognised role, an empty string
or `None` is denied, never treated as "no restriction specified, so allow."
"""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from core.audit.contracts import ActionType, AuditQueryFilter
from core.audit.db import INSERT_SQL, connect
from core.audit.errors import E_READ_FAILED, E_ROLE_FORBIDDEN
from core.audit.query import MAX_LIMIT, build_where, role_permitted

from .conftest import run, utc


def seed(writer, n: int = 5):
    for i in range(n):
        run(
            writer.record_action(
                "config_change", f"owner_{i % 2}", details={"i": i}, target_user_id="client_1"
            )
        )
    run(
        writer.record_action(
            "break_glass_grant", "staff_9", target_user_id="client_2", reason="incident"
        )
    )


# ------------------------------------------------------------------ role gating


@pytest.mark.parametrize("role", ["staff", "owner"])
def test_staff_and_owner_can_read(writer, query, role):
    seed(writer, 1)
    assert run(query.fetch(AuditQueryFilter(), role)).error is None


@pytest.mark.parametrize("role", ["client", "", None, "CLIENT", "admin", "Owner", "staff "])
def test_everything_else_is_denied(writer, query, role):
    """Note `"Owner"` and `"staff "` are in this list on purpose: the check is exact, not
    normalised, so a caller passing a display-cased or padded role is refused rather than
    silently accepted through a helpful-looking `.strip().lower()`."""
    seed(writer, 1)
    result = run(query.fetch(AuditQueryFilter(), role))
    assert result.error == E_ROLE_FORBIDDEN
    assert result.events == ()


def test_a_denied_read_returns_no_rows_at_all(writer, query):
    """Fail-closed means no partial answer either — a denied caller must not learn the
    log's size from `total_matching`."""
    seed(writer, 3)
    result = run(query.fetch(AuditQueryFilter(), "client"))
    assert result.total_matching == 0 and result.events == ()


def test_get_by_id_is_gated_the_same_way(writer, query):
    seed(writer, 1)
    listed = run(query.fetch(AuditQueryFilter(), "owner"))
    event_id = listed.events[0].event_id
    assert run(query.get(event_id, "client")).error == E_ROLE_FORBIDDEN
    assert run(query.get(event_id, "staff")).error is None


def test_role_permitted_is_the_single_gate():
    assert role_permitted("staff") and role_permitted("owner")
    assert not any(role_permitted(r) for r in (None, "", "client", "system", "anonymous"))


# -------------------------------------------------------------------- filtering


def test_filter_by_action_type(writer, query):
    seed(writer)
    result = run(
        query.fetch(AuditQueryFilter(action_types=(ActionType.BREAK_GLASS_GRANTED,)), "owner")
    )
    assert result.total_matching == 1
    assert result.events[0].actor_user_id == "staff_9"


def test_filter_by_actor_and_target(writer, query):
    seed(writer)
    assert run(query.fetch(AuditQueryFilter(actor_user_id="owner_0"), "owner")).total_matching == 3
    assert (
        run(query.fetch(AuditQueryFilter(target_user_id="client_2"), "owner")).total_matching == 1
    )


def test_paging_reports_the_unpaged_total(writer, query):
    seed(writer, 5)
    page = run(query.fetch(AuditQueryFilter(limit=2, offset=2), "owner"))
    assert len(page.events) == 2
    assert page.total_matching == 6


def test_limit_is_capped_server_side(writer, query):
    """A mis-set limit must not be able to pull a decade of records into one response."""
    seed(writer, 3)
    result = run(query.fetch(AuditQueryFilter(limit=10_000_000), "owner"))
    assert len(result.events) <= MAX_LIMIT


def test_every_filter_value_is_bound_not_interpolated(writer, query):
    """The one piece of SQL built from input is the `IN (?,?)` placeholder run; the values
    themselves are always parameters. A quote-heavy actor id must be inert."""
    hostile = "'; DROP TABLE audit_events; --"
    where, params = build_where(AuditQueryFilter(actor_user_id=hostile))
    assert hostile not in where and hostile in params

    seed(writer, 1)
    result = run(query.fetch(AuditQueryFilter(actor_user_id=hostile), "owner"))
    assert result.error is None and result.total_matching == 0
    # The table is still there.
    assert run(query.fetch(AuditQueryFilter(), "owner")).total_matching == 2


def test_results_are_newest_first(writer, query):
    seed(writer, 3)
    result = run(query.fetch(AuditQueryFilter(), "owner"))
    times = [e.occurred_at for e in result.events]
    assert times == sorted(times, reverse=True)


def test_ordering_holds_across_events_recorded_in_different_utc_offsets(writer, query):
    """Regression. `ORDER BY occurred_at` is a *lexical* comparison of stored strings, so an
    event recorded in `+14:00` sorted ahead of a genuinely newer UTC one purely on the
    spelling of its offset. `db.to_storage_ts` normalises on the way in."""
    now = utc(0)
    run(writer.record_action("config_change", "newest", occurred_at=now))
    run(
        writer.record_action(
            "config_change",
            "two_hours_old_in_plus_14",
            occurred_at=(now - timedelta(hours=2)).astimezone(timezone(timedelta(hours=14))),
        )
    )
    result = run(query.fetch(AuditQueryFilter(), "owner"))
    assert [e.actor_user_id for e in result.events] == ["newest", "two_hours_old_in_plus_14"]
    times = [e.occurred_at for e in result.events]
    assert times == sorted(times, reverse=True)


def test_a_range_filter_matches_on_the_instant_not_the_spelling(writer, query):
    run(writer.record_action("config_change", "o", occurred_at=utc(0)))
    # Same instant, expressed in a different offset — the bound must still match.
    bound = (utc(0) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-5)))
    result = run(query.fetch(AuditQueryFilter(occurred_after=bound), "owner"))
    assert result.total_matching == 1


def test_an_undecodable_row_is_reported_as_error_data_not_raised(db_path, writer, query):
    """A row written by a *newer* build — carrying an `ActionType` this one has never heard
    of — used to make `ActionType(...)` raise `ValueError` straight across the gRPC boundary,
    which `docs/PRINCIPLES.md` §4.1 rules out. It is now reported on the result."""
    conn = connect(db_path, profile="append")
    try:
        conn.execute(
            INSERT_SQL,
            ("aud_future", "tenant_deleted", "staff_1", None, None, "{}",
             "2026-01-01T00:00:00+00:00", None),
        )
        conn.commit()
    finally:
        conn.close()

    result = run(query.fetch(AuditQueryFilter(), "owner"))
    assert result.error == E_READ_FAILED
    assert result.events == ()
    assert "tenant_deleted" in result.error_detail
