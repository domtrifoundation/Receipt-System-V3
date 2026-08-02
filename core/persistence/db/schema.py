"""Canonical per-user database schema (`v3-deepdive-13-persistence-api.md` §3.2).

Table definitions and nothing else — no connection handling, no queries. Every table
carries `schema_version`, which is what ties this into Migration API: a migration is not a
special kind of write, it is an ordinary write that happens to touch schema-defining rows,
so it inherits the same atomicity and Historian trail every other write already has (§3.2).

**Two structural properties that are enforced here rather than by convention:**

1. `historian_events` and `narrative_events` are append-only. There is no UPDATE or DELETE
   statement for either anywhere in this package, and nothing hands out the raw connection
   (`docs/PRINCIPLES.md` §2.3). The trigger below makes that a database-level guarantee too,
   so a future careless raw statement fails loudly instead of quietly succeeding.
2. `receipts.logical_id` references `blob_locations.logical_id` as *identity*, never as a
   path. The physical address lives only in `blob_locations.physical_hash` (§3.3).

**No taxonomy tables live here.** `reference_identifiers.kind` and `receipt_fields.field_key`
are foreign references to types Architect API registered; this schema stores instance values
against them and defines none of its own (`docs/PRINCIPLES.md` §3.4).
"""

from __future__ import annotations

#: The schema version this build writes. Migration API compares this against the value
#: stored in `schema_meta` and drives any upgrade through the normal write path.
CURRENT_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key            TEXT PRIMARY KEY,
    value          TEXT NOT NULL
);

-- Identity → physical storage. One indexed lookup resolves a blob (§3.3). This table is
-- the entire reason logical_id never needs to change when retention purges the original
-- upload or an owner-initiated codec migration rewrites what is actually stored.
CREATE TABLE IF NOT EXISTS blob_locations (
    logical_id     TEXT PRIMARY KEY,
    physical_hash  TEXT NOT NULL,
    codec          TEXT NOT NULL,
    byte_size      INTEGER NOT NULL,
    updated_at     TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_blob_locations_physical
    ON blob_locations(physical_hash);

-- Per-target backup confirmation. Deliberately separate rows rather than a single "saved"
-- flag on the blob: local write success and remote confirmation are different states, and
-- one-of-N confirmed vs all-of-N confirmed are different questions (§4.4, §12).
CREATE TABLE IF NOT EXISTS blob_backup_state (
    logical_id     TEXT NOT NULL,
    target_name    TEXT NOT NULL,
    confirmed_at   TEXT NOT NULL,
    PRIMARY KEY (logical_id, target_name)
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_id       TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    logical_id       TEXT NOT NULL,
    group_id         TEXT,
    vendor_id        TEXT,
    vendor_name      TEXT NOT NULL DEFAULT '',
    transaction_date TEXT,
    currency         TEXT NOT NULL DEFAULT 'PHP',
    total_amount     TEXT,
    vat_amount       TEXT,
    fields_json      TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    schema_version   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_receipts_user ON receipts(user_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_receipts_group ON receipts(group_id);
CREATE INDEX IF NOT EXISTS idx_receipts_logical ON receipts(logical_id);

-- `kind` names an Architect-registered type. Nothing here validates or invents kinds.
CREATE TABLE IF NOT EXISTS reference_identifiers (
    receipt_id     TEXT NOT NULL,
    kind           TEXT NOT NULL,
    value          TEXT NOT NULL,
    normalized     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (receipt_id, kind, value)
);

-- Historian, data-change track. Append-only (§2.3) — see the trigger below.
CREATE TABLE IF NOT EXISTS historian_events (
    event_id        TEXT PRIMARY KEY,
    seq             INTEGER,
    table_name      TEXT NOT NULL,
    row_id          TEXT NOT NULL,
    before_json     TEXT,
    after_json      TEXT,
    actor           TEXT NOT NULL,
    program_version TEXT NOT NULL,
    occurred_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_historian_row ON historian_events(row_id, occurred_at);

-- Historian, narrative track. Append-only as well. `detail_json` is quantized by design —
-- never raw OCR text, never a full prompt/response. That resolution boundary is what keeps
-- this track webapp-displayable while Logs stays origin-server-only.
CREATE TABLE IF NOT EXISTS narrative_events (
    event_id     TEXT PRIMARY KEY,
    receipt_id   TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    stage        TEXT NOT NULL,
    summary      TEXT NOT NULL,
    detail_json  TEXT NOT NULL DEFAULT '{}',
    triggered_by TEXT NOT NULL,
    occurred_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_narrative_receipt
    ON narrative_events(receipt_id, occurred_at);

-- The baseline a reimported workbook diffs against (`v3-deepdive-30-reimport.md` §3).
-- A reimport whose referenced export row no longer exists is rejected outright rather than
-- guessed at — that is the resolved "stale snapshot reference" answer (§9 there).
CREATE TABLE IF NOT EXISTS export_snapshots (
    export_id           TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    historian_event_id  TEXT NOT NULL,
    generated_at        TEXT NOT NULL
);

-- Archive Sync's per-user cursor. A cursor, not a full re-scan every run (§4 there).
CREATE TABLE IF NOT EXISTS archive_sync_cursor (
    user_id        TEXT NOT NULL,
    target_name    TEXT NOT NULL,
    last_receipt_id TEXT NOT NULL DEFAULT '',
    last_synced_at TEXT,
    paused_reason  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, target_name)
);

-- The structural half of append-only. The application half is that no update/delete method
-- exists on Historian's public surface at all; this is the backstop for a raw statement.
CREATE TRIGGER IF NOT EXISTS historian_events_no_update
BEFORE UPDATE ON historian_events
BEGIN
    SELECT RAISE(ABORT, 'historian_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS historian_events_no_delete
BEFORE DELETE ON historian_events
BEGIN
    SELECT RAISE(ABORT, 'historian_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS narrative_events_no_update
BEFORE UPDATE ON narrative_events
BEGIN
    SELECT RAISE(ABORT, 'narrative_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS narrative_events_no_delete
BEFORE DELETE ON narrative_events
BEGIN
    SELECT RAISE(ABORT, 'narrative_events is append-only');
END;
"""

#: Tables a Disaster Recovery verification pass walks looking for blob references. Named
#: here rather than inline in `verify.py` so adding a blob-referencing table cannot silently
#: skip verification — the list lives next to the schema that defines them.
BLOB_REFERENCING_TABLES = ("receipts",)


__all__ = ["BLOB_REFERENCING_TABLES", "CURRENT_SCHEMA_VERSION", "SCHEMA"]
