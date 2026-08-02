"""WAL mode, explicit transaction control, and the append-only database triggers."""

from __future__ import annotations

import sqlite3

import pytest

from core.persistence.db.connection import Database, default_blob_root, default_db_path
from core.persistence.db.schema import CURRENT_SCHEMA_VERSION

from ..conftest import run


def test_wal_mode_is_on(db: Database):
    mode = db.run_sync(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0])
    assert mode.lower() == "wal"


def test_schema_version_is_recorded(db: Database):
    assert db.schema_version() == CURRENT_SCHEMA_VERSION


def test_transaction_rolls_back_on_exception(db: Database):
    def _fail(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('sentinel', 'written')"
        )
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        db.transaction_sync(_fail)

    row = db.run_sync(
        lambda c: c.execute(
            "SELECT value FROM schema_meta WHERE key = 'sentinel'"
        ).fetchone()
    )
    assert row is None


def test_async_transaction_commits(db: Database):
    run(
        db.transaction(
            lambda c: c.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('async', 'ok')"
            )
        )
    )
    row = db.run_sync(
        lambda c: c.execute("SELECT value FROM schema_meta WHERE key='async'").fetchone()
    )
    assert row["value"] == "ok"


def test_historian_events_reject_update_at_the_database_level(db: Database):
    """The structural backstop behind append-only.

    The application half is that no update or delete method exists on Historian's surface at
    all. This is what catches a raw statement that bypasses that surface entirely.
    """
    db.transaction_sync(
        lambda c: c.execute(
            "INSERT INTO historian_events (event_id, table_name, row_id, before_json,"
            " after_json, actor, program_version, occurred_at)"
            " VALUES ('e1','receipts','r1',NULL,'{}','worker','x00.00.00','2026-07-17')"
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.transaction_sync(
            lambda c: c.execute("UPDATE historian_events SET actor = 'someone-else'")
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.transaction_sync(lambda c: c.execute("DELETE FROM historian_events"))


def test_narrative_events_reject_update_and_delete(db: Database):
    db.transaction_sync(
        lambda c: c.execute(
            "INSERT INTO narrative_events (event_id, receipt_id, run_id, stage, summary,"
            " detail_json, triggered_by, occurred_at)"
            " VALUES ('n1','r1','run1','written','done','{}','initial_scan','2026-07-17')"
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.transaction_sync(
            lambda c: c.execute("UPDATE narrative_events SET summary = 'rewritten'")
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.transaction_sync(lambda c: c.execute("DELETE FROM narrative_events"))


def test_a_snapshot_carries_data_still_sitting_in_the_wal(db: Database, tmp_path):
    """A real trap, guarded rather than discovered during a restore.

    Copying a WAL database's `.sqlite` file alone produces a snapshot that opens without
    error and is missing every committed transaction still living in the `-wal` file — the
    worst possible shape for a backup to fail in. `snapshot_to` uses SQLite's own online
    backup API, which checkpoints properly.
    """
    db.transaction_sync(
        lambda c: c.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('committed', 'before-snapshot')"
        )
    )
    snapshot = db.snapshot_to(tmp_path / "snap.sqlite")

    restored = Database(snapshot)
    try:
        row = restored.run_sync(
            lambda c: c.execute(
                "SELECT value FROM schema_meta WHERE key='committed'"
            ).fetchone()
        )
        assert row is not None, "the snapshot lost data still in the WAL"
        assert row["value"] == "before-snapshot"
    finally:
        restored.close()


def test_per_user_paths_are_outside_the_repository(tmp_path):
    """Per-user data lives in the top-level install directory, never in a release clone."""
    db_path = default_db_path(tmp_path, "user-1")
    blob_path = default_blob_root(tmp_path, "user-1")
    assert db_path.parent == tmp_path / "users" / "user-1"
    assert blob_path == tmp_path / "users" / "user-1" / "blobs"
    # Two users are two different folders — the isolation boundary is structural.
    assert default_db_path(tmp_path, "user-2") != db_path
