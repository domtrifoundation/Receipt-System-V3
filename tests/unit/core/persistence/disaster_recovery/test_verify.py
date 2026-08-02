"""The corruption-detection and ordering-violation hooks (Disaster Recovery's own §8)."""

from __future__ import annotations

import pytest

from core.persistence.contracts import StorageCodec
from core.persistence.db.receipts import ReceiptRepository
from core.persistence.disaster_recovery.errors import OrderingViolation
from core.persistence.disaster_recovery.verify import verify_restore

from ..conftest import make_receipt, run


def _seed(db, blobs, count=2):
    repo = ReceiptRepository(db)
    refs = []
    for i in range(count):
        write = run(blobs.put(f"receipt bytes {i}".encode()))
        run(repo.save(make_receipt(f"rc{i}", blob=write.blob_ref), actor="worker"))
        refs.append(write.blob_ref)
    return refs


def test_a_healthy_store_verifies_clean(db, blobs):
    _seed(db, blobs)
    report = run(verify_restore(db, blobs.root))
    assert report.clean
    assert report.hash_mismatches == ()


def test_a_bit_flipped_blob_is_caught_by_hash_verification(db, blobs):
    """Existence-checking alone would call this file fine. It is corrupt."""
    refs = _seed(db, blobs)
    path = run(blobs.resolve_blob_path(refs[0].logical_id))
    data = bytearray(path.read_bytes())
    data[3] ^= 0xFF
    path.write_bytes(bytes(data))

    report = run(verify_restore(db, blobs.root))
    assert not report.clean
    assert len(report.hash_mismatches) == 1
    assert report.orphaned_physical_files == ()


def test_a_missing_file_and_a_missing_mapping_are_reported_separately(db, blobs):
    """Different repairs, so never merged into one count."""
    refs = _seed(db, blobs)
    run(blobs.resolve_blob_path(refs[0].logical_id)).unlink()

    repo = ReceiptRepository(db)
    run(repo.save(make_receipt("rc-orphan", blob=type(refs[0])("f" * 64)), actor="worker"))

    report = run(verify_restore(db, blobs.root))
    assert not report.clean
    assert len(report.orphaned_physical_files) == 1
    assert report.orphaned_logical_ids == ("f" * 64,)


def test_verifying_before_blobs_are_restored_is_refused(db, tmp_path):
    """Answering it would report every reference as orphaned regardless of whether the
    backups are intact — a result that looks like information and is not."""
    empty_root = tmp_path / "not-restored-yet"
    empty_root.mkdir()
    with pytest.raises(OrderingViolation):
        run(verify_restore(db, empty_root))


def test_re_encoded_blobs_verify_against_the_stored_bytes_not_the_original(db, blobs):
    """The correction this verification pass exists because of.

    Checking a stored file against the hash of the *original* upload would fail for every
    re-encoded blob permanently. `physical_hash` is what is checked, and it is by definition
    the hash of what is genuinely on disk.
    """
    write = run(
        blobs.put(b"original upload", stored_bytes=b"archival copy", codec=StorageCodec.WEBP)
    )
    run(ReceiptRepository(db).save(make_receipt(blob=write.blob_ref), actor="worker"))
    report = run(verify_restore(db, blobs.root))
    assert report.clean
