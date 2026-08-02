"""The cursor-resume and filename-collision hooks (Archive Sync's own §7), plus the
notify-then-pause behaviour §8 resolves."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from core.persistence.archive_sync import errors
from core.persistence.archive_sync.contracts import SyncState, SyncTarget
from core.persistence.archive_sync.providers.base import (
    LocalFolderProvider,
    SyncProviderRegistry,
)
from core.persistence.archive_sync.sync import ArchiveSync, external_name
from core.persistence.db.receipts import ReceiptRepository

from ..conftest import make_receipt, run


class _Notifications:
    def __init__(self):
        self.sent = []

    async def notify(self, user_id, kind, detail):
        self.sent.append((user_id, kind, detail))


def _setup(db, tmp_path, blobs, count=3):
    repo = ReceiptRepository(db)
    stored = []
    for i in range(count):
        write = run(blobs.put(f"receipt bytes {i}".encode()))
        run(
            repo.save(
                make_receipt(f"rc{i}", blob=write.blob_ref, vendor_name=f"Vendor {i}"),
                actor="worker",
            )
        )
        stored.append(write.blob_ref)

    async def fetch(logical_id):
        read = await blobs.get(logical_id)
        return read.data if read.ok else None

    provider = LocalFolderProvider(tmp_path / "external", fetch)
    (tmp_path / "external").mkdir(parents=True, exist_ok=True)
    sync = ArchiveSync(db, blobs, SyncProviderRegistry([provider]), _Notifications(), repo)
    target = SyncTarget("local_folder", "archive", "user-1")
    return sync, provider, target


def test_a_full_pass_mirrors_everything_and_advances_the_cursor(db, tmp_path, blobs):
    sync, _, target = _setup(db, tmp_path, blobs)
    job = run(sync.sync_new_archives(target))
    assert job.ok
    assert job.mirrored == 3
    assert job.cursor.last_receipt_id == "rc2"
    mirrored = list((tmp_path / "external" / "archive").iterdir())
    assert len(mirrored) == 3


def test_an_interrupted_run_resumes_from_the_cursor(db, tmp_path, blobs):
    """Not re-uploading everything, and not silently skipping unmirrored items."""
    sync, _, target = _setup(db, tmp_path, blobs)
    first = run(sync.sync_new_archives(target, batch=2))
    assert first.mirrored == 2
    assert first.cursor.last_receipt_id == "rc1"

    second = run(sync.sync_new_archives(target, batch=2))
    assert second.mirrored == 1, "resume re-uploaded or skipped items"
    assert second.cursor.last_receipt_id == "rc2"

    third = run(sync.sync_new_archives(target))
    assert third.mirrored == 0


def test_two_receipts_that_would_collide_get_distinct_external_names():
    """Same date and same vendor, different blobs — the distinguishing suffix is what stops
    one silently overwriting the other."""
    when = datetime(2026, 7, 17, tzinfo=timezone.utc)
    from core.persistence.contracts import BlobRef

    left = make_receipt("rc1", transaction_date=when, vendor_name="ABC Corp",
                        blob=BlobRef("a" * 64))
    right = make_receipt("rc2", transaction_date=when, vendor_name="ABC Corp",
                         blob=BlobRef("b" * 64))
    assert external_name(left) != external_name(right)
    assert external_name(left).startswith("2026-07-17_ABC-Corp_")


def test_an_unreachable_target_notifies_then_pauses(db, tmp_path, blobs):
    sync, provider, target = _setup(db, tmp_path, blobs)
    provider.reachable = False

    job = run(sync.sync_new_archives(target))
    assert not job.ok
    assert job.state is SyncState.PAUSED
    assert job.error_code == errors.TARGET_UNREACHABLE
    assert sync._notifications.sent, "the user was never told their mirror stopped"

    # Never silently continues retrying while paused.
    provider.reachable = True
    again = run(sync.sync_new_archives(target))
    assert again.error_code == errors.SYNC_PAUSED
    assert again.mirrored == 0


def test_resume_requires_an_explicit_call(db, tmp_path, blobs):
    sync, provider, target = _setup(db, tmp_path, blobs)
    provider.reachable = False
    run(sync.sync_new_archives(target))
    provider.reachable = True

    cursor = run(sync.resume("user-1", "local_folder"))
    assert cursor.state is SyncState.ACTIVE
    job = run(sync.sync_new_archives(target))
    assert job.ok and job.mirrored == 3


def test_an_unknown_provider_is_an_error_code(db, tmp_path, blobs):
    sync, _, _ = _setup(db, tmp_path, blobs)
    job = run(sync.sync_new_archives(SyncTarget("nope", "archive", "user-1")))
    assert not job.ok
    assert job.error_code == errors.UNKNOWN_PROVIDER


def test_a_purged_internal_blob_is_not_removed_externally(db, tmp_path, blobs):
    """Retention parity is deliberately absent: the external copy is the user's own."""
    sync, _, target = _setup(db, tmp_path, blobs)
    run(sync.sync_new_archives(target))
    mirrored_before = {p.name for p in (tmp_path / "external" / "archive").iterdir()}

    for path in list(blobs.root.rglob("*")):
        if path.is_file():
            path.unlink()

    run(sync.sync_new_archives(target))
    mirrored_after = {p.name for p in (tmp_path / "external" / "archive").iterdir()}
    assert mirrored_after == mirrored_before
