"""Blob content-addressing — deep-dive §11's second named testing hook, plus the
logical/physical split that has already been gotten wrong once."""

from __future__ import annotations

from core.persistence.blob_store.store import sha256_hex, sharded_path
from core.persistence.contracts import StorageCodec
from core.persistence.errors import BLOB_CORRUPT, BLOB_LOCATION_MISSING, BLOB_NOT_FOUND

from ..conftest import run

ORIGINAL = b"the original uploaded bytes"
REENCODED = b"the re-encoded archival copy"


def test_same_bytes_twice_produce_one_blob_and_two_references(blobs):
    """The real idempotency guarantee content-addressing exists for."""
    first = run(blobs.put(ORIGINAL))
    second = run(blobs.put(ORIGINAL))
    assert first.ok and second.ok
    assert first.blob_ref == second.blob_ref
    assert second.deduplicated is True
    stored = [p for p in blobs.root.rglob("*") if p.is_file()]
    assert len(stored) == 1, "the same bytes were stored twice"


def test_logical_id_is_the_hash_of_the_original_not_of_what_is_stored(blobs):
    """The correctness point, asserted directly.

    Uploading `ORIGINAL` but storing `REENCODED` must produce a `logical_id` derived from the
    original and a `physical_hash` derived from what is genuinely on disk. If these ever
    collapse into one value, the stored file stops matching its own filename the moment
    retention purges the original.
    """
    result = run(blobs.put(ORIGINAL, stored_bytes=REENCODED, codec=StorageCodec.WEBP))
    logical_id = result.blob_ref.logical_id
    assert logical_id == sha256_hex(ORIGINAL)

    location = run(blobs.location(logical_id))
    assert location.physical_hash == sha256_hex(REENCODED)
    assert location.physical_hash != logical_id

    path = run(blobs.resolve_blob_path(logical_id))
    assert logical_id not in path.name, "logical_id must never appear in a storage path"
    assert location.physical_hash in path.name
    assert path.read_bytes() == REENCODED


def test_storage_path_is_sharded_two_levels(blobs):
    result = run(blobs.put(ORIGINAL))
    path = run(blobs.resolve_blob_path(result.blob_ref.logical_id))
    location = run(blobs.location(result.blob_ref.logical_id))
    assert path.parent.name == location.physical_hash[2:4]
    assert path.parent.parent.name == location.physical_hash[:2]


def test_stored_file_always_matches_its_own_name(blobs):
    result = run(blobs.put(ORIGINAL, stored_bytes=REENCODED, codec=StorageCodec.WEBP))
    read = run(blobs.get(result.blob_ref.logical_id, verify=True))
    assert read.ok
    assert read.data == REENCODED


def test_re_encode_changes_the_physical_address_and_not_the_identity(blobs):
    """The whole point of the two-layer scheme: retention or a codec migration rewrites
    physical storage while every reference in the system stays valid untouched."""
    result = run(blobs.put(ORIGINAL))
    logical_id = result.blob_ref.logical_id
    original_path = run(blobs.resolve_blob_path(logical_id))

    run(blobs.re_encode(logical_id, REENCODED, StorageCodec.WEBP))

    assert run(blobs.location(logical_id)).logical_id == logical_id, "identity changed"
    new_path = run(blobs.resolve_blob_path(logical_id))
    assert new_path != original_path
    assert new_path.read_bytes() == REENCODED
    assert not original_path.exists(), "the superseded original was left behind"


def test_corruption_is_detected_by_verification(blobs):
    result = run(blobs.put(ORIGINAL))
    path = run(blobs.resolve_blob_path(result.blob_ref.logical_id))
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))

    read = run(blobs.get(result.blob_ref.logical_id, verify=True))
    assert not read.ok
    assert read.error_code == BLOB_CORRUPT


def test_missing_mapping_and_missing_file_are_different_errors(blobs):
    unmapped = run(blobs.get("f" * 64))
    assert unmapped.error_code == BLOB_LOCATION_MISSING

    result = run(blobs.put(ORIGINAL))
    run(blobs.resolve_blob_path(result.blob_ref.logical_id)).unlink()
    missing = run(blobs.get(result.blob_ref.logical_id))
    assert missing.error_code == BLOB_NOT_FOUND


def test_sharded_path_uses_the_codec_suffix(tmp_path):
    path = sharded_path(tmp_path, "ab" + "0" * 62, StorageCodec.WEBP)
    assert path.suffix == ".webp"
    assert sharded_path(tmp_path, "ab" + "0" * 62, StorageCodec.ORIGINAL).suffix == ".bin"
