"""The append path: validation, errors-as-data, and multi-sink fan-out."""

from __future__ import annotations

import collections.abc

import pytest

from common.frozen_dict import FrozenDict
from core.audit.contracts import ActionType, AuditEvent, AuditQueryFilter, AuditSink
from core.audit.errors import (
    E_INVALID_EVENT,
    E_REASON_REQUIRED,
    E_SINK_UNAVAILABLE,
    E_UNKNOWN_ACTION,
)
from core.audit.sinks import SinkRegistry, SqliteAuditSink
from core.audit.writer import AuditWriter, coerce_details, new_event_id

from .conftest import make_event, run, utc


class RecordingSink:
    """A mirror that just remembers what it was handed."""

    def __init__(self, name: str = "mirror", fail: bool = False) -> None:
        self._name = name
        self._fail = fail
        self.events: list[AuditEvent] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_primary(self) -> bool:
        return False

    def append(self, event: AuditEvent) -> None:
        if self._fail:
            raise RuntimeError("mirror volume offline")
        self.events.append(event)

    def close(self) -> None:
        pass


# ------------------------------------------------------------------- happy path


def test_record_action_writes_and_returns_the_event_id(writer, query):
    result = run(writer.record_action("config_change", "owner_1", details={"key": "audit.x"}))
    assert result.recorded and result.error is None
    assert result.event_id.startswith("aud_")

    read = run(query.fetch(AuditQueryFilter(), "staff"))
    assert read.total_matching == 1
    assert read.events[0].action_type is ActionType.CONFIG_CHANGED


def test_event_ids_are_unguessable_and_unique():
    ids = {new_event_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(i.startswith("aud_") for i in ids)


# -------------------------------------------------------------------- validation


def test_reason_is_mandatory_for_break_glass(writer):
    """Auth's own requirement (§4). A break-glass grant with no stated reason is not
    evidence, so it is rejected rather than stored as a record nobody can interpret."""
    result = run(writer.record_action("break_glass_grant", "staff_1", target_user_id="c1"))
    assert not result.recorded
    assert result.error == E_REASON_REQUIRED


def test_reason_is_optional_elsewhere(writer):
    assert run(writer.record_action("config_change", "owner_1")).recorded


def test_an_unregistered_operation_is_refused(writer):
    """The privileged-action set is closed on purpose — §7's coverage guarantee is only
    meaningful if a caller cannot invent a name that bypasses it."""
    result = run(writer.record_action("quietly_do_a_thing", "staff_1"))
    assert not result.recorded
    assert result.error == E_UNKNOWN_ACTION
    assert "PRIVILEGED_ACTIONS" in result.error_detail


def test_an_event_with_no_actor_is_refused(writer):
    result = run(writer.record(make_event(actor="")))
    assert not result.recorded
    assert result.error == E_INVALID_EVENT


def test_errors_are_returned_never_raised(writer):
    """`docs/PRINCIPLES.md` §4.1 — Audit has no equivalent of Auth's raise-loudly carve-out.
    Every failure path above returns a result; none of them raises."""
    for bad in (
        AuditEvent(
            event_id="", action_type=ActionType.CONFIG_CHANGED,
            actor_user_id="a", occurred_at=utc(),
        ),
        AuditEvent(
            event_id="x", action_type=ActionType.CONFIG_CHANGED,
            actor_user_id="a", occurred_at="not-a-datetime",  # type: ignore[arg-type]
        ),
    ):
        result = run(writer.record(bad))
        assert result.recorded is False and result.error


# ----------------------------------------------------------------- details field


def test_details_are_stored_and_read_back_as_a_frozen_mapping(writer, query, db_path):
    run(writer.record_action("role_change", "owner_1", details={"old": "client", "new": "staff"}))
    result = run(query.fetch(AuditQueryFilter(), "owner"))
    details = result.events[0].details

    # Mapping, never `dict` — the 3.15 builtin frozendict is not a dict subclass.
    assert isinstance(details, collections.abc.Mapping)
    assert dict(details) == {"old": "client", "new": "staff"}
    with pytest.raises(TypeError):
        details["old"] = "owner"  # type: ignore[index]


def test_coerce_details_accepts_an_already_frozen_payload():
    """The regression this guards: a `isinstance(x, dict)` check here would silently reject
    an already-`FrozenDict` payload on Python 3.15+ and take the error branch."""
    frozen = FrozenDict({"a": 1})
    assert dict(coerce_details(frozen)) == {"a": 1}
    assert dict(coerce_details(None)) == {}
    with pytest.raises(Exception):
        coerce_details(["not", "a", "mapping"])


# --------------------------------------------------------------------- fan-out


def test_a_failing_mirror_degrades_but_the_write_still_succeeds(db_path):
    """§4.4 — losing a redundant copy is not a reason to fail the privileged action that
    already happened. The failure is reported, not swallowed."""
    registry = SinkRegistry(SqliteAuditSink(db_path))
    registry.register(RecordingSink("worm", fail=True))
    registry.register(RecordingSink("offbox"))
    w = AuditWriter(registry=registry)
    try:
        result = run(w.record_action("config_change", "owner_1"))
        assert result.recorded and result.error is None
        # Bare sink *names*, which is what `RecordResult.degraded_sinks` is documented to
        # hold — a caller comparing an entry against a registered sink's `name` has to be
        # able to match it, and it could not against a "name: message" string. The reason a
        # mirror failed belongs in the operational trace (Logs API), not in this field.
        assert result.degraded_sinks == ("worm",)
        assert result.degraded_sinks[0] in registry.names
    finally:
        w.close()


def test_a_working_mirror_receives_every_event(db_path):
    mirror = RecordingSink("offbox")
    registry = SinkRegistry(SqliteAuditSink(db_path))
    registry.register(mirror)
    w = AuditWriter(registry=registry)
    try:
        run(w.record_action("force_wake", "staff_1"))
        run(w.record_action("pin_service_version", "owner_1", details={"version": "x03.00.00"}))
    finally:
        w.close()
    assert [e.action_type for e in mirror.events] == [
        ActionType.SERVICE_FORCE_WOKEN,
        ActionType.SERVICE_VERSION_PINNED,
    ]


def test_a_missing_primary_is_an_error_not_a_degradation():
    """The asymmetry that makes this API trustworthy: a caller must never be told its audit
    entry was recorded when it was not."""
    w = AuditWriter(registry=SinkRegistry())
    result = run(w.record_action("config_change", "owner_1"))
    assert not result.recorded
    assert result.error == E_SINK_UNAVAILABLE


def test_only_one_primary_may_be_registered(db_path):
    registry = SinkRegistry(SqliteAuditSink(db_path))
    with pytest.raises(ValueError):
        registry.register(SqliteAuditSink(db_path))
    registry.close()


def test_the_sqlite_sink_satisfies_the_protocol(db_path):
    sink = SqliteAuditSink(db_path)
    try:
        assert isinstance(sink, AuditSink)
        assert sink.is_primary and sink.name == "sqlite"
    finally:
        sink.close()
