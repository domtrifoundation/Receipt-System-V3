"""Data-portability export completeness (`v3-deepdive-06-account-guardian-api.md` §11).

§11 names this hook precisely, and its stated purpose is what shapes the test:

> **Export completeness check**: a bench/regression case confirming a data-portability export
> genuinely covers every table touching a user's data, not just the obviously-relevant ones —
> the kind of gap that's easy to introduce silently when a new table gets added elsewhere in
> the system without anyone remembering to add it to the export scope too.

So the failure being guarded against is **not** "the export is wrong today". It is "someone
adds a table to Persistence six months from now and nobody remembers this file exists". A test
that asserted the current five table names against a hardcoded list would pass forever while
that gap opened, which is precisely the silent regression §11 is describing.

What actually closes it: derive the table list from Persistence's **live schema** and require
every table to be accounted for — either in the export scope, or in an explicit
`NOT_USER_DATA` set below with a written reason. A new table lands in neither and this fails.
Adding a table then becomes a deliberate choice between "export it" and "say why not", which
is the only version of this check that stays true without maintenance.

Account Guardian owns the requirement (§6.2's data-portability obligation is its own), while
the scope itself lives in Persistence's provider — so this test reaches across that boundary
deliberately. It is the one place the two have to agree.
"""

from __future__ import annotations

import re

import pytest

from core.persistence.db.schema import SCHEMA
from core.persistence.exports.providers.data_portability import PORTABLE_TABLES

#: Tables that genuinely hold no user-portable data, each with the reason it is excluded.
#: A reason is required rather than a bare name: "not user data" asserted without saying why
#: is exactly how a table that *is* user data gets quietly parked here to make a test pass.
NOT_USER_DATA: dict[str, str] = {
    "schema_meta": (
        "schema version bookkeeping for the database itself; contains no row belonging to any "
        "user and would be meaningless in an export they received"
    ),
    "blob_backup_state": (
        "per-blob replication bookkeeping — which backup target holds which copy and when it "
        "last succeeded. It is infrastructure state about our own storage, not the user's "
        "content; the blob's own location row is exported via blob_locations"
    ),
    "export_snapshots": (
        "the record of exports previously generated, including this one. Including it would "
        "make an export's contents depend on how many exports came before it, and it carries "
        "no receipt data the user did not already receive in the export it describes"
    ),
    "archive_sync_cursor": (
        "an internal progress marker for the archive-sync sweep; a row number, not user data"
    ),
}


def schema_tables() -> set[str]:
    """Every table Persistence's live schema actually creates.

    Read from the schema string rather than listed here, which is the whole point: a table
    added there shows up here automatically, with no one having to remember to update a list.
    """
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))


def test_the_schema_is_actually_readable():
    """A guard on the guard.

    If `SCHEMA` were ever restructured so this regex matched nothing, every assertion below
    would pass vacuously — the completeness check would silently stop checking anything, which
    is the same class of failure it exists to catch.
    """
    tables = schema_tables()

    assert len(tables) >= 5
    assert "receipts" in tables


def test_every_table_is_either_exported_or_explicitly_excluded():
    """§11's hook, in the form that survives a table being added later.

    This is the assertion that fails on the day someone adds a table to Persistence's schema
    without deciding whether it belongs in a user's data-portability export.
    """
    accounted_for = set(PORTABLE_TABLES) | set(NOT_USER_DATA)
    unaccounted = schema_tables() - accounted_for

    assert not unaccounted, (
        f"{sorted(unaccounted)} exist in Persistence's schema but are neither in the export "
        f"scope nor listed in NOT_USER_DATA with a reason. Decide which, and say why if the "
        f"answer is 'not user data' — see this module's docstring."
    )


def test_the_exclusion_list_does_not_drift_past_the_schema():
    """An exclusion naming a table that no longer exists is stale reasoning.

    Left in place it makes the exclusion list look more considered than it is, and a future
    table reusing that name would inherit an exemption nobody chose for it.
    """
    stale = set(NOT_USER_DATA) - schema_tables()

    assert not stale, f"{sorted(stale)} are excluded but no longer exist in the schema"


def test_the_export_scope_does_not_reference_a_table_that_no_longer_exists():
    """The mirror case: an export query against a dropped table fails at export time.

    That failure would land on a user who asked for their data, which is the worst place for
    it to surface.
    """
    missing = set(PORTABLE_TABLES) - schema_tables()

    assert not missing, f"{sorted(missing)} are in the export scope but not in the schema"


def test_no_table_is_both_exported_and_excluded():
    """Two contradictory answers about one table mean neither was really decided."""
    both = set(PORTABLE_TABLES) & set(NOT_USER_DATA)

    assert not both, f"{sorted(both)} are both exported and listed as not-user-data"


@pytest.mark.parametrize("table", sorted(NOT_USER_DATA))
def test_every_exclusion_carries_a_real_reason(table):
    """A bare name would let "not user data" become a place to park inconvenient tables."""
    reason = NOT_USER_DATA[table]

    assert len(reason) > 40, f"{table}'s exclusion reason is too thin to be a real judgement"


def test_the_tables_holding_a_user_s_own_receipt_data_are_all_in_scope():
    """The positive assertion, so the test cannot pass by excluding everything.

    Every table here holds content the user themself created or that describes their own
    receipts — the core of what a portability export owes them.
    """
    for table in ("receipts", "reference_identifiers", "historian_events", "narrative_events"):
        assert table in PORTABLE_TABLES


def test_every_scoped_query_filters_by_the_requesting_user():
    """A completeness check that ignored scoping would invite the opposite bug.

    An export query missing its `user_id` predicate would hand one user another's receipts —
    a far worse failure than an incomplete export, and cheap to assert alongside it.
    """
    for table, sql in PORTABLE_TABLES.items():
        assert "?" in sql, f"{table}'s export query takes no user parameter"
        assert "user_id" in sql, f"{table}'s export query does not filter by user_id"
