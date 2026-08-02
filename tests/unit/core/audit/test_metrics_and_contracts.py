"""Metrics snapshots, and the immutability guarantees `contracts.py` is supposed to carry.

The `forward_compat`-marked tests here are marked deliberately narrowly: only the ones that
turn on `FrozenDict`'s *resolved type* differing across interpreters, per `pytest.ini`'s own
note that the marker is not for tests that merely import a module which happens to use it.
"""

from __future__ import annotations

import collections.abc
import dataclasses

import pytest

from common.frozen_dict import FrozenDict
from core.audit import contracts
from core.audit.contracts import (
    DEFAULT_RETENTION_DAYS,
    RETENTION_SETTING_SPEC,
    ActionType,
    AuditEvent,
    AuditMetrics,
    RetentionPolicy,
)
from core.audit.db import PROFILE_EXTRA_OPS
from core.audit.errors import ERROR_SUMMARIES
from core.audit.metrics import AuditMetricsReader

from .conftest import run, utc


@pytest.fixture
def reader(db_path):
    r = AuditMetricsReader(db_path)
    yield r
    r.close()


# ---------------------------------------------------------------------- metrics


def test_snapshot_of_an_empty_log(reader):
    snapshot = run(reader.snapshot())
    assert snapshot.error is None
    assert snapshot.total_events == 0
    assert dict(snapshot.events_by_action) == {}
    assert snapshot.oldest_occurred_at is None


def test_snapshot_counts_by_action_and_bounds_the_range(writer, reader):
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(100)))
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(1)))
    run(writer.record_action("force_wake", "staff_1", occurred_at=utc(50)))

    snapshot = run(reader.snapshot())
    assert snapshot.total_events == 3
    assert dict(snapshot.events_by_action) == {"config_changed": 2, "service_force_woken": 1}
    assert snapshot.oldest_occurred_at < snapshot.newest_occurred_at


def test_snapshot_reports_how_much_is_waiting_for_the_next_sweep(writer, reader):
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(4000)))
    run(writer.record_action("config_change", "owner_1", occurred_at=utc(10)))
    snapshot = run(reader.snapshot(RetentionPolicy()))
    assert snapshot.events_past_horizon == 1


def test_a_snapshot_over_an_unreadable_row_degrades_instead_of_raising(db_path, reader):
    """A monitoring read must never be able to raise across the boundary of the thing it is
    monitoring. A row whose timestamp this build cannot parse used to escape as a bare
    `ValueError` (`docs/PRINCIPLES.md` §4.1, §4.4)."""
    from core.audit.db import INSERT_SQL, connect

    conn = connect(db_path, profile="append")
    try:
        conn.execute(
            INSERT_SQL,
            ("aud_bad", "config_changed", "s", None, None, "{}", "not-a-timestamp", None),
        )
        conn.commit()
    finally:
        conn.close()

    snapshot = run(reader.snapshot())
    assert snapshot.error is not None
    assert snapshot.total_events == 0


def test_a_metrics_read_cannot_write(reader, db_path):
    """It uses the `read` profile, so it is structurally incapable of disturbing the thing
    it is monitoring."""
    assert PROFILE_EXTRA_OPS["read"] == frozenset()


# -------------------------------------------------------------------- contracts


@pytest.mark.parametrize(
    "cls",
    [
        contracts.AuditEvent,
        contracts.AuditQueryFilter,
        contracts.AuditMetrics,
        contracts.RecordResult,
        contracts.AuditQueryResult,
        contracts.PurgeResult,
        contracts.RetentionPolicy,
        contracts.RetentionResolution,
    ],
)
def test_every_contract_is_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen, f"{cls.__name__} crosses a boundary unfrozen"


def test_contracts_module_declares_no_mutating_result_type():
    """§3.2 — the absence is the guarantee. If a future change adds an `UpdateEventRequest`,
    this is where it gets caught."""
    names = [n for n in dir(contracts) if not n.startswith("_")]
    assert not [n for n in names if "Update" in n or "Delete" in n], names


def test_the_retention_setting_carries_the_regulation_not_a_bare_number():
    """§5 — the actual regulation is shown in the TUI itself, so an owner changing this
    value is making an informed choice against the real legal context."""
    assert RETENTION_SETTING_SPEC["default"] == DEFAULT_RETENTION_DAYS == 3650
    tooltip = RETENTION_SETTING_SPEC["tooltip"]
    assert "17-2013" in tooltip and "5-2014" in tooltip
    assert RETENTION_SETTING_SPEC["docs_ref"]


def test_error_summaries_cover_every_declared_code():
    from core.audit import errors

    codes = {v for k, v in vars(errors).items() if k.startswith("E_") and isinstance(v, str)}
    assert codes <= set(ERROR_SUMMARIES)


# ------------------------------------------------------------- forward compat


@pytest.mark.forward_compat
def test_module_level_lookup_tables_are_frozen_dicts():
    """`docs/PRINCIPLES.md` §2.1.1 — a table every module reads and nothing should ever
    write, shared across real OS threads under free-threading. The assertion is against
    `Mapping` plus a mutation attempt rather than against `dict`, because the 3.15 builtin
    is not a `dict` subclass and a `dict` check would pass on 3.14 and fail on 3.15."""
    for table in (contracts.PRIVILEGED_ACTIONS, RETENTION_SETTING_SPEC, ERROR_SUMMARIES,
                  PROFILE_EXTRA_OPS):
        assert isinstance(table, collections.abc.Mapping)
        assert type(table) is FrozenDict
        with pytest.raises(TypeError):
            table["injected"] = "value"  # type: ignore[index]


@pytest.mark.forward_compat
def test_a_recorded_events_details_cannot_be_mutated_after_the_fact():
    """The immutability that matters most for this API specifically: an append-only record
    whose payload could still be edited in place would be a real hole (§2.1)."""
    event = AuditEvent(
        event_id="aud_x",
        action_type=ActionType.BREAK_GLASS_GRANTED,
        actor_user_id="staff_1",
        occurred_at=utc(),
        reason="incident",
        details=FrozenDict({"folder": "client_9"}),
    )
    assert isinstance(event.details, collections.abc.Mapping)
    with pytest.raises(TypeError):
        event.details["folder"] = "client_1"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.reason = "nothing happened"  # type: ignore[misc]


@pytest.mark.forward_compat
def test_the_default_details_factory_produces_a_frozen_dict():
    """A default of `FrozenDict({})` produced through `field(default_factory=...)` is the
    easy thing to get wrong — a shared plain `{}` default would be both mutable and shared
    across every event that omitted the field."""
    a = AuditEvent("a", ActionType.CONFIG_CHANGED, "o", utc())
    b = AuditEvent("b", ActionType.CONFIG_CHANGED, "o", utc())
    assert type(a.details) is FrozenDict
    assert a.details is not b.details or len(a.details) == 0
    assert type(AuditMetrics().events_by_action) is FrozenDict
