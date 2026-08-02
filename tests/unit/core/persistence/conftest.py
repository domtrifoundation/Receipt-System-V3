"""Shared fixtures for Persistence's unit tests.

**Why `run()` instead of `pytest-asyncio`.** Persistence's surface is async throughout, but
adding a test-only dependency belongs in the same PR that declares it in `requirements.txt`,
and `requirements.txt` is deliberately minimal. `asyncio.run` per test is the smaller,
dependency-free answer and it also gives each test its own event loop, which is the isolation
an async plugin's default configuration would have to be set up to provide anyway.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from core.persistence.blob_store.backup.base import BackupRegistry, InMemoryTarget
from core.persistence.blob_store.store import BlobStore
from core.persistence.contracts import BlobRef, Receipt, utcnow
from core.persistence.db.connection import Database


def run(coro):
    """Drive one coroutine to completion on its own event loop."""
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """A real on-disk database, not `:memory:` — WAL mode and the append-only triggers are
    both properties of a real file, and testing against something that skips them would
    validate a configuration nothing ever runs."""
    database = Database(tmp_path / "canonical.sqlite")
    yield database
    database.close()


@pytest.fixture
def backups() -> BackupRegistry:
    """Two targets, one deliberately unreachable — the one-of-two durability case."""
    return BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj")])


@pytest.fixture
def blobs(db: Database, tmp_path: Path, backups: BackupRegistry) -> BlobStore:
    return BlobStore(db, tmp_path / "blobs", backups)


def make_receipt(receipt_id: str = "rc1", **overrides) -> Receipt:
    """A receipt record. Contains no receipt *image* and no fixture data of any kind — these
    are synthetic identifiers and amounts for exercising the write path only."""
    base = {
        "receipt_id": receipt_id,
        "user_id": "user-1",
        "blob": BlobRef("0" * 64),
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "vendor_name": "Vendor A",
        "total_amount": Decimal("100.00"),
        "vat_amount": Decimal("12.00"),
    }
    base.update(overrides)
    return Receipt(**base)
