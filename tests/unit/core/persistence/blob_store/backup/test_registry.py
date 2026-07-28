"""Backup-target failover — deep-dive §11's third named testing hook.

The resolved semantics (§12): one confirmed target is already real durability and is what
gates the write path; both confirming is a separate, stronger "fully synced" status. This
file is where that distinction is held to.
"""

from __future__ import annotations

from core.persistence.blob_store.backup.base import BackupRegistry, InMemoryTarget
from core.persistence.blob_store.store import BlobStore
from core.persistence.errors import BACKUP_UNCONFIRMED

from ...conftest import run

DATA = b"blob bytes"


def test_one_of_two_reachable_is_durable_but_not_fully_synced(db, tmp_path):
    registry = BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj", reachable=False)])
    store = BlobStore(db, tmp_path / "blobs", registry)

    result = run(store.put(DATA))

    assert result.ok
    assert result.durably_backed_up is True, "one redundant target is real durability"
    assert result.fully_synced is False, "fully_synced must require every enabled target"
    assert result.confirmed_targets == ("b2",)
    assert result.failed_targets == ("storj",)


def test_both_reachable_is_fully_synced(db, tmp_path):
    registry = BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj")])
    store = BlobStore(db, tmp_path / "blobs", registry)
    result = run(store.put(DATA))
    assert result.durably_backed_up and result.fully_synced
    assert set(result.confirmed_targets) == {"b2", "storj"}


def test_no_target_reachable_still_writes_locally_but_says_so(db, tmp_path):
    """Local write success and remote confirmation are separate states, never one flag."""
    registry = BackupRegistry(
        [InMemoryTarget("b2", reachable=False), InMemoryTarget("storj", reachable=False)]
    )
    store = BlobStore(db, tmp_path / "blobs", registry)
    result = run(store.put(DATA))

    assert result.ok, "the bytes are on local disk — that is not a failed write"
    assert result.durably_backed_up is False
    assert result.error_code == BACKUP_UNCONFIRMED
    assert run(store.get(result.blob_ref.logical_id)).ok


def test_a_raising_target_is_recorded_as_failed_not_propagated(db, tmp_path):
    class ExplodingTarget:
        name = "exploding"

        async def is_reachable(self):
            return True

        async def upload(self, physical_hash, data):
            raise RuntimeError("network went away mid-upload")

        async def fetch(self, physical_hash):
            return None

    registry = BackupRegistry([InMemoryTarget("b2"), ExplodingTarget()])
    store = BlobStore(db, tmp_path / "blobs", registry)
    result = run(store.put(DATA))

    assert result.ok
    assert result.durably_backed_up is True
    assert result.failed_targets == ("exploding",)


def test_no_enabled_targets_is_not_an_error(db, tmp_path):
    """A self-hosted install with no remote backup configured degrades, never fails."""
    store = BlobStore(db, tmp_path / "blobs", BackupRegistry())
    result = run(store.put(DATA))
    assert result.ok
    assert result.error_code == ""


def test_disabling_a_target_removes_it_from_the_fan_out():
    registry = BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj")])
    registry.set_enabled("storj", False)
    result = run(registry.fan_out("a" * 64, DATA))
    assert result.enabled_count == 1
    assert result.confirmed == ("b2",)
    assert result.fully_synced is True


def test_reachability_is_checkable_independently_of_a_write():
    registry = BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj", reachable=False)])
    assert run(registry.reachability()) == {"b2": True, "storj": False}
