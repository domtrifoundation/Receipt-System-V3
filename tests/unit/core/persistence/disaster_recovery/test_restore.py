"""The restore-integrity hook (deep-dive §11's fourth) and the blobs-before-SQLite ordering.

Restore integrity means the restored database's own **row-level content** matches the
pre-restore state — not merely that the restore process exited cleanly.
"""

from __future__ import annotations

from core.persistence.blob_store.backup.base import BackupRegistry, InMemoryTarget
from core.persistence.blob_store.store import BlobStore
from core.persistence.db.connection import Database
from core.persistence.db.receipts import ReceiptRepository
from core.persistence.disaster_recovery import errors
from core.persistence.disaster_recovery.contracts import RestoreScope, RestoreStage
from core.persistence.disaster_recovery.restore import restore_instance

from ..conftest import make_receipt, run


def _live_instance(tmp_path):
    db = Database(tmp_path / "live" / "canonical.sqlite")
    registry = BackupRegistry([InMemoryTarget("b2"), InMemoryTarget("storj")])
    store = BlobStore(db, tmp_path / "live" / "blobs", registry)
    repo = ReceiptRepository(db)
    for i in range(3):
        write = run(store.put(f"receipt bytes {i}".encode()))
        run(repo.save(make_receipt(f"rc{i}", blob=write.blob_ref,
                                   vendor_name=f"Vendor {i}"), actor="worker"))
    return db, store, registry, repo


def test_a_full_restore_reproduces_row_level_content(tmp_path):
    db, store, registry, repo = _live_instance(tmp_path)
    before = {r.receipt_id: (r.vendor_name, str(r.total_amount), r.blob.logical_id)
              for r in run(repo.list_for_user("user-1"))}
    snapshot = db.snapshot_to(tmp_path / "snapshot.sqlite")
    db.close()

    job = run(
        restore_instance(
            tmp_path / "restored", "snap-1", snapshot_source=snapshot, backups=registry
        )
    )
    assert job.stage is RestoreStage.COMPLETE, job.error_detail
    assert job.report.clean
    assert job.blobs_restored == 3

    restored_db = Database(tmp_path / "restored" / "canonical.sqlite")
    try:
        restored = run(ReceiptRepository(restored_db).list_for_user("user-1"))
        after = {r.receipt_id: (r.vendor_name, str(r.total_amount), r.blob.logical_id)
                 for r in restored}
        assert after == before
    finally:
        restored_db.close()


def test_restore_runs_blobs_before_the_database(tmp_path):
    """Asserted through the outcome rather than by watching the order: a restore that
    reached COMPLETE with a clean report can only have restored blobs first, because
    verification against a not-yet-restored store refuses to answer at all."""
    db, store, registry, _ = _live_instance(tmp_path)
    snapshot = db.snapshot_to(tmp_path / "snapshot.sqlite")
    db.close()

    job = run(
        restore_instance(
            tmp_path / "restored", "snap-1", snapshot_source=snapshot, backups=registry
        )
    )
    blob_files = list((tmp_path / "restored" / "blobs").rglob("*"))
    assert [p for p in blob_files if p.is_file()]
    assert job.stage is RestoreStage.COMPLETE


def test_a_corrupt_backup_copy_is_not_written_into_the_restored_store(tmp_path):
    """The redundancy exists for exactly this: a target whose copy no longer matches its own
    address is skipped, not trusted."""
    db, store, registry, _ = _live_instance(tmp_path)
    snapshot = db.snapshot_to(tmp_path / "snapshot.sqlite")
    db.close()

    corrupt = InMemoryTarget("corrupt")
    for physical_hash in list(registry.get("b2")._blobs):
        corrupt._blobs[physical_hash] = b"tampered"
    only_corrupt = BackupRegistry([corrupt])

    job = run(
        restore_instance(
            tmp_path / "restored", "snap-1", snapshot_source=snapshot, backups=only_corrupt
        )
    )
    assert job.blobs_restored == 0
    assert job.stage is RestoreStage.COMPLETE_WITH_ISSUES
    assert job.error_code == errors.BLOB_RESTORE_INCOMPLETE


def test_a_missing_snapshot_fails_before_touching_anything(tmp_path):
    registry = BackupRegistry([InMemoryTarget("b2")])
    job = run(
        restore_instance(
            tmp_path / "restored",
            "snap-1",
            snapshot_source=tmp_path / "does-not-exist.sqlite",
            backups=registry,
        )
    )
    assert job.stage is RestoreStage.FAILED
    assert job.error_code == errors.SNAPSHOT_NOT_FOUND
    assert not (tmp_path / "restored").exists()


def test_no_reachable_backup_target_is_reported_not_attempted(tmp_path):
    db, _, _, _ = _live_instance(tmp_path)
    snapshot = db.snapshot_to(tmp_path / "snapshot.sqlite")
    db.close()

    job = run(
        restore_instance(
            tmp_path / "restored",
            "snap-1",
            snapshot_source=snapshot,
            backups=BackupRegistry([InMemoryTarget("b2", reachable=False)]),
        )
    )
    assert job.stage is RestoreStage.FAILED
    assert job.error_code == errors.NO_BACKUP_TARGET_REACHABLE


def test_a_single_user_restore_records_its_own_scope(tmp_path):
    """§5's boundary: real and supported, and never a substitute for a full-instance
    restore when the cause might have touched shared state."""
    db, _, registry, _ = _live_instance(tmp_path)
    snapshot = db.snapshot_to(tmp_path / "snapshot.sqlite")
    db.close()

    job = run(
        restore_instance(
            tmp_path / "restored",
            "snap-1",
            snapshot_source=snapshot,
            backups=registry,
            scope=RestoreScope.SINGLE_USER,
            user_id="user-1",
        )
    )
    assert job.scope is RestoreScope.SINGLE_USER
    assert job.user_id == "user-1"
    assert job.stage is RestoreStage.COMPLETE
