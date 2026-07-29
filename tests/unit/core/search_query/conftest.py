"""Shared fixtures for Search/Query's unit tests.

Every fixture writes **real receipt rows into a real SQLite database** under `tmp_path`, using
Persistence's own schema. That is deliberate rather than convenient: the two guarantees this
package has to hold — that user text never becomes SQL, and that a permission check happens at
query time — are both properties of the statement that actually executes. A fake store that
returned canned rows would test the fake, and would pass just as happily against an
implementation that string-concatenated its WHERE clause.

The permission checkers are injected as real Protocol implementations, and the default in
production denies. So a test that forgets to wire one in fails closed exactly as a real process
would, which means the fail-closed posture is exercised by the suite's own defaults rather than
only by the tests that name it.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.auth.contracts import Role
from core.persistence.db.schema import SCHEMA
from core.search_query.db import ReceiptDatabaseRegistry, default_db_path

BASE = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


def run(coro):
    """Drive one coroutine to completion.

    `asyncio.run` rather than `pytest-asyncio`, matching every other package's conftest in this
    repo — the dependency is deliberately absent and the stdlib already does this.
    """
    return asyncio.run(coro)


def seed_receipts(top_level: Path, user_id: str, rows: list[dict]) -> None:
    """Write real rows into that user's real canonical database.

    Creates the full Persistence schema rather than a cut-down table, so the FTS trigger
    plumbing and column set the query code actually targets are the ones under test.
    """
    path = default_db_path(top_level, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        for row in rows:
            written_at = row.get("transaction_date", BASE).isoformat()
            conn.execute(
                """
                INSERT INTO receipts (
                    receipt_id, user_id, logical_id, vendor_name, transaction_date,
                    total_amount, currency, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["receipt_id"],
                    user_id,
                    row.get("logical_id", f"blob-{row['receipt_id']}"),
                    row["vendor_name"],
                    written_at,
                    str(row.get("total_amount", Decimal("100.00"))),
                    row.get("currency", "PHP"),
                    written_at,
                    written_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


class AllowCrossUser:
    """A break-glass checker that grants — the "an active grant exists" case."""

    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str]] = []

    async def allow(self, requesting_user_id: str, target_user_id: str) -> bool:
        self.calls.append((requesting_user_id, target_user_id))
        return self.allowed


class ExpiringCrossUser:
    """A grant that is live for the first check and expired for every one after.

    This is what makes §7's break-glass-expiry hook a real test rather than a restatement: the
    grant genuinely changes state between two queries in the same session, which is only
    observable if the check happens per query rather than once when the session opened.
    """

    def __init__(self) -> None:
        self.checks = 0

    async def allow(self, requesting_user_id: str, target_user_id: str) -> bool:
        self.checks += 1
        return self.checks == 1


class StaticGroupManager:
    """A group-manager checker over fixed facts."""

    def __init__(self, *, manages: set[tuple[str, str]] | None = None, groups: dict | None = None):
        self._manages = manages or set()
        self._groups = groups or {}

    async def is_manager_over_group(self, group_id: str, user_id: str) -> bool:
        return (group_id, user_id) in self._manages

    async def group_of(self, user_id: str) -> str | None:
        return self._groups.get(user_id)


class StaticMembers:
    """A group-membership lookup over a fixed map."""

    def __init__(self, members: dict[str, tuple[str, ...]] | None = None) -> None:
        self._members = members or {}

    async def members_of(self, group_id: str) -> tuple[str, ...]:
        return self._members.get(group_id, ())


@pytest.fixture
def top_level(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def registry(top_level: Path) -> ReceiptDatabaseRegistry:
    return ReceiptDatabaseRegistry(top_level)


@pytest.fixture
def seeded(top_level: Path) -> Path:
    """One user with a few real receipts, including deliberately awkward vendor text.

    The vendor names are the shape the real fixture corpus actually contains — raw OCR output
    with punctuation and digits substituted for letters — so the text search is exercised
    against what it will really see rather than tidy names.
    """
    seed_receipts(
        top_level,
        "user-1",
        [
            {
                "receipt_id": "r1",
                "vendor_name": "7-ELEVEN PHILIPPINES",
                "transaction_date": BASE,
                "total_amount": Decimal("150.00"),
            },
            {
                "receipt_id": "r2",
                "vendor_name": "AENA@AV'S FOOD CENTER INC",
                "transaction_date": BASE + timedelta(days=5),
                "total_amount": Decimal("1250.50"),
            },
            {
                "receipt_id": "r3",
                "vendor_name": "JOLLIBEE FOODS CORPORA7I0N",
                "transaction_date": BASE + timedelta(days=10),
                "total_amount": Decimal("480.00"),
            },
        ],
    )
    return top_level


OWNER = Role.OWNER
STAFF = Role.STAFF
CLIENT = Role.CLIENT
