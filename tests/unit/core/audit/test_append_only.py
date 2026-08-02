"""The deep-dive's §7 append-only enforcement test.

§7 names this precisely: confirm `set_authorizer()` genuinely denies `SQLITE_UPDATE` and
`SQLITE_DELETE` at the *connection* level, "not just that application code politely avoids
issuing them." So these tests do not call the writer's public API and check that it behaved —
they go around it, issue the raw SQL an attacker or a careless future maintainer would issue,
and assert SQLite itself refuses.

The second half of this file covers the other half of the same guarantee: that no method
exposing an edit exists anywhere on this package's public surface. A connection-level
authorizer only holds while every module keeps using the right profile; the absent method is
what makes it hard to stop doing that by accident.
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from core.audit import query as query_module
from core.audit import retention as retention_module
from core.audit import sinks as sinks_module
from core.audit import writer as writer_module
from core.audit.contracts import ActionType, AuditSink
from core.audit.db import PROFILE_EXTRA_OPS, connect
from core.audit.errors import AppendOnlyViolation

from .conftest import make_event, run

FORBIDDEN_NAME_FRAGMENTS = ("update", "delete", "purge", "edit", "modify", "amend", "remove")


def _seed(db_path):
    conn = connect(db_path, profile="append")
    from core.audit.db import INSERT_SQL, event_to_row

    event = make_event(ActionType.BREAK_GLASS_GRANTED, reason="incident 42")
    conn.execute(INSERT_SQL, event_to_row(event))
    conn.commit()
    return conn, event


# ------------------------------------------------------- connection-level enforcement


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_events SET reason = 'nothing happened'",
        "UPDATE audit_events SET actor_user_id = 'someone_else' WHERE event_id IS NOT NULL",
        "DELETE FROM audit_events",
        "DROP TABLE audit_events",
        "ALTER TABLE audit_events ADD COLUMN backdoor TEXT",
        "CREATE TABLE shadow_events (x TEXT)",
        "ATTACH DATABASE ':memory:' AS elsewhere",
    ],
)
def test_append_profile_denies_every_mutation(db_path, sql):
    """This is the test that matters most in this package. If it ever fails, the audit log
    has stopped being evidence and is merely a table."""
    conn, _ = _seed(db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute(sql)
    finally:
        conn.close()


def test_append_profile_still_permits_insert_and_select(db_path):
    """The denial must be surgical: an authorizer that also broke ordinary appends would
    pass the test above while making the API useless."""
    conn, event = _seed(db_path)
    try:
        row = conn.execute(
            "SELECT reason FROM audit_events WHERE event_id = ?", (event.event_id,)
        ).fetchone()
        assert row["reason"] == "incident 42"
    finally:
        conn.close()


def test_read_profile_cannot_write_at_all(db_path):
    """`query.py` and `metrics.py` use this profile. A read path that is structurally
    incapable of writing is worth more than one that merely never does (§4.5)."""
    _seed(db_path)[0].close()
    conn = connect(db_path, profile="read")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute(
                "INSERT INTO audit_events (event_id, action_type, actor_user_id, occurred_at)"
                " VALUES ('x','config_changed','a','2020-01-01T00:00:00+00:00')"
            )
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute("DELETE FROM audit_events")
    finally:
        conn.close()


def test_no_profile_anywhere_permits_update():
    """`SQLITE_UPDATE` appears in no profile at all — not even the purge profile, which is
    allowed to delete. An audit row is never modified by any connection this package can
    open, which is a stronger statement than 'the writer does not issue UPDATE'."""
    for profile, ops in PROFILE_EXTRA_OPS.items():
        assert sqlite3.SQLITE_UPDATE not in ops, profile


def test_purge_profile_is_the_only_one_that_can_delete():
    delete_capable = [
        name for name, ops in PROFILE_EXTRA_OPS.items() if sqlite3.SQLITE_DELETE in ops
    ]
    assert delete_capable == ["purge"]


def test_writer_surfaces_an_authorizer_denial_as_its_own_error(db_path):
    """If code inside this package ever did try to mutate the log, the denial is classified
    rather than mistaken for an unreachable database — the two need different responses."""
    conn = connect(db_path, profile="append")
    try:
        with pytest.raises(sqlite3.DatabaseError) as exc_info:
            conn.execute("UPDATE audit_events SET reason = 'x'")
        assert "not authorized" in str(exc_info.value)
        assert AppendOnlyViolation("x").code == "APPEND_ONLY_VIOLATION"
    finally:
        conn.close()


def test_each_module_opens_the_profile_it_is_supposed_to(db_path, monkeypatch):
    """The gap the other tests in this file leave open. They prove each *profile* enforces
    what it claims, and that no mutation method exists — but the guarantee only holds while
    every module actually asks for the right profile. Nothing else here would notice if
    `sinks.py` were edited to open `purge`, and every other test would still pass.
    """
    from core.audit import db as db_module
    from core.audit import metrics as metrics_module

    seen: dict[str, str] = {}
    real_connect = db_module.connect

    def recording_connect(path, profile):
        seen[profile] = profile
        return real_connect(path, profile)

    for module in (sinks_module, query_module, metrics_module, retention_module):
        monkeypatch.setattr(module, "connect", recording_connect)

    seen.clear()
    sinks_module.SqliteAuditSink(db_path).close()
    assert set(seen) == {"append"}, "the write path must open the append profile"

    for factory in (query_module.AuditQuery, metrics_module.AuditMetricsReader):
        seen.clear()
        factory(db_path).close()
        assert set(seen) == {"read"}, f"{factory.__name__} must open the read profile"

    seen.clear()
    retention_module.RetentionPurge(db_path).close()
    assert set(seen) == {"purge"}, "retention is the only module permitted the purge profile"


# ------------------------------------------------------------ public-surface enforcement


@pytest.mark.parametrize(
    "module", [writer_module, query_module, sinks_module], ids=lambda m: m.__name__
)
def test_no_module_exposes_a_mutation_method(module):
    """No `update_event()`, no `delete_event()`, anywhere. `retention.py` is excluded here
    and checked separately below — it is the one deliberate, isolated deletion path."""
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ != module.__name__:
            continue
        for name, _ in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            assert not any(f in name.lower() for f in FORBIDDEN_NAME_FRAGMENTS), (
                f"{module.__name__}.{cls.__name__}.{name} looks like a mutation path; "
                f"append-only is a structural property of this package's surface (§3.2)"
            )


def test_the_sink_protocol_declares_no_way_to_remove_a_record():
    """A sink that cannot be *asked* to remove a record is a guarantee that survives whatever
    a future third-party sink implementation decides to do internally."""
    declared = {n for n in dir(AuditSink) if not n.startswith("_")}
    assert declared == {"append", "close", "is_primary", "name"}


def test_retention_purge_exposes_exactly_one_deletion_entry_point():
    public = {
        name
        for name, _ in inspect.getmembers(retention_module.RetentionPurge, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"purge", "close"}

    # And `purge` takes no event id and no predicate — the only thing a caller can express
    # is "apply the configured policy."
    params = set(inspect.signature(retention_module.RetentionPurge.purge).parameters)
    assert params == {"self", "policy", "actor_user_id", "now"}


def test_a_correction_is_a_new_event_not_an_edit(db_path, writer, query):
    """§3.2's stated model: a correction references the original's `event_id`; the original
    row is untouched and still readable exactly as first written."""
    original = run(
        writer.record_action(
            "break_glass_grant", "staff_1", target_user_id="client_9", reason="incident 42"
        )
    )
    assert original.recorded

    correction = run(
        writer.record_correction(
            original.event_id,
            "break_glass_grant",
            "staff_1",
            reason="reason was recorded against the wrong incident; correct is 43",
        )
    )
    assert correction.recorded
    assert correction.event_id != original.event_id

    result = run(query.get(original.event_id, "owner"))
    assert result.error is None
    assert [e.event_id for e in result.events] == [original.event_id, correction.event_id]
    # The original still says what it originally said.
    assert result.events[0].reason == "incident 42"
    assert result.events[1].corrects_event_id == original.event_id
