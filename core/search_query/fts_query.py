"""FTS5 query construction and schema provisioning
(`v3-deepdive-21-search-query-api.md` §3, §7's "FTS5 injection test").

**The injection surface this module exists to close, precisely.** FTS5's `MATCH` argument is
itself a small query language — `AND`/`OR`/`NOT`/`NEAR`, `*` prefix matching, `^` column
weighting, and `"..."` phrase quoting are all live syntax inside it. Passing a bound SQL
parameter is necessary but **not sufficient**: `conn.execute("... MATCH ?", (raw_text,))` is
safe from *SQL* injection (the statement text itself never changes), but `raw_text` is still
parsed as an *FTS5* query, so a user typing `OR`, `NOT`, `*`, or an unbalanced `"` changes
what the search does or raises `sqlite3.OperationalError` straight out of a boundary that
returns errors as data (`docs/PRINCIPLES.md` §4.1). `build_match_expression` closes this by
quoting every token as an FTS5 string literal (doubling embedded `"` per FTS5's own escaping
rule) before it is ever bound — every character the user typed becomes literal text to match,
never a query operator, and a malformed fragment can no longer produce an unbalanced
expression because every token is independently well-formed.

**Schema provisioning, and why it lives here rather than in Persistence's own schema.**
`db.py`'s own docstring records the real gap: `core/persistence/db/schema.py` does not yet
define `receipts_fts`, and this task's scope forbids adding it there directly.
`ensure_fts_schema` provisions a plain (non-external-content) FTS5 table plus `AFTER
INSERT`/`AFTER UPDATE`/`AFTER DELETE` triggers on `receipts` that keep it synced —
confirmed against SQLite's own upsert-trigger semantics: `receipts`' own writer
(`core/persistence/db/receipts.py`'s `_upsert`) is an `INSERT ... ON CONFLICT DO UPDATE`, and
SQLite fires the `INSERT` trigger only on the genuine insert path and the `UPDATE` trigger
only on the conflict-resolution path — never both, never neither — so a receipt becomes
searchable inside the identical transaction that writes its own row, exactly as the deep-dive
requires, without one line of Persistence's own code changing.
"""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS receipts_fts USING fts5(
    receipt_id UNINDEXED,
    user_id UNINDEXED,
    vendor_name,
    search_text
);

CREATE TRIGGER IF NOT EXISTS receipts_fts_ai AFTER INSERT ON receipts BEGIN
    INSERT INTO receipts_fts(receipt_id, user_id, vendor_name, search_text)
    VALUES (new.receipt_id, new.user_id, new.vendor_name,
            new.vendor_name || ' ' || COALESCE(new.fields_json, ''));
END;

CREATE TRIGGER IF NOT EXISTS receipts_fts_au AFTER UPDATE ON receipts BEGIN
    DELETE FROM receipts_fts WHERE receipt_id = old.receipt_id;
    INSERT INTO receipts_fts(receipt_id, user_id, vendor_name, search_text)
    VALUES (new.receipt_id, new.user_id, new.vendor_name,
            new.vendor_name || ' ' || COALESCE(new.fields_json, ''));
END;

CREATE TRIGGER IF NOT EXISTS receipts_fts_ad AFTER DELETE ON receipts BEGIN
    DELETE FROM receipts_fts WHERE receipt_id = old.receipt_id;
END;
"""

#: Runs every time `ensure_fts_schema` opens a connection, not only on first creation — a
#: receipt written before this schema existed on a given user's database (any pre-existing
#: install, or the ordinary gap between Persistence writing a row and Search/Query's own
#: first connection to that file) has no trigger to have fired for it. The `NOT IN` guard
#: makes repeated runs cheap no-ops once a database is caught up, so this is safe to run
#: unconditionally on every open rather than tracked with its own one-shot flag.
_BACKFILL = """
INSERT INTO receipts_fts (receipt_id, user_id, vendor_name, search_text)
SELECT receipt_id, user_id, vendor_name, vendor_name || ' ' || COALESCE(fields_json, '')
FROM receipts
WHERE receipt_id NOT IN (SELECT receipt_id FROM receipts_fts);
"""


def ensure_fts_schema(conn: sqlite3.Connection) -> bool:
    """Idempotently provision `receipts_fts`, its sync triggers, and backfill any rows
    written before this schema existed, against `conn`.

    Returns whether full-text search is usable on this connection. `False` — never a raised
    exception — on any `sqlite3.OperationalError` (an interpreter/SQLite build without FTS5
    compiled in, or a `receipts` table that does not exist yet on a brand-new database):
    degrades to structured-only search rather than failing the query outright
    (`docs/PRINCIPLES.md` §4.4), the same posture `core/health/errors.py`'s
    `DriftCheckUnavailable` documents for a probe that cannot run on a given interpreter.
    """
    try:
        conn.executescript(_SCHEMA)
        conn.execute(_BACKFILL)
        conn.commit()
    except sqlite3.OperationalError:
        return False
    return True


def build_match_expression(raw_query: str) -> str:
    """User text -> a well-formed FTS5 `MATCH` expression, safe to bind as a single parameter.

    Every whitespace-separated token becomes its own quoted FTS5 string literal, `AND`-joined
    — see the module docstring for exactly what this closes. An all-whitespace or empty
    `raw_query` returns `""`, which callers treat as "no text filter" rather than binding an
    empty `MATCH` expression (FTS5 rejects one).
    """
    tokens = raw_query.split()
    if not tokens:
        return ""
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def text_match_clause(query_text: str) -> tuple[str, str] | None:
    """The `WHERE` fragment and its bound parameter for a free-text filter over `receipts`,
    or `None` when there is no text to filter on.

    Returned as a subquery against `receipts_fts` — joined by `receipt_id`, never a raw
    string concatenation of `query_text` into the surrounding SQL — so `structured_query.py`
    only ever combines this with its own bound parameters, never with `query_text` itself.
    """
    expression = build_match_expression(query_text)
    if not expression:
        return None
    return (
        "receipt_id IN (SELECT receipt_id FROM receipts_fts WHERE receipts_fts MATCH ?)",
        expression,
    )


__all__ = ["build_match_expression", "ensure_fts_schema", "text_match_clause"]
