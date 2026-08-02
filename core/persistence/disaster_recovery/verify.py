"""Post-restore verification (`v3-deepdive-33-disaster-recovery.md` §4).

A successful-looking restore is not the same as a *correct* one. Backup corruption, a
partial or interrupted backup cycle, and a mismatch between the SQLite snapshot's expected
blob set and what actually reached backup are all real failure modes to actively check for —
not to discover later when a user opens a receipt and the image is gone.

**Verification walks `BlobLocation`, not `logical_id` directly.** That is a real correction
from an earlier version of this design, which would have checked a stored file's bytes
against the hash of bytes that were never on disk in the first place (the original,
pre-re-encode upload). `physical_hash` is by definition the hash of whatever is *actually*
stored, so it is always self-consistent — which is exactly what makes a mismatch mean
"silent corruption" rather than "retention ran."

Three checks, three separately reported lists, because they imply three different repairs:
a receipt referencing a `logical_id` with no mapping row at all; a mapping row pointing at a
file that is not there; a file that is there but no longer matches its own `physical_hash`.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from pathlib import Path

from ..blob_store.store import sharded_path
from ..contracts import StorageCodec
from ..db.connection import Database
from ..db.schema import BLOB_REFERENCING_TABLES
from .contracts import VerificationReport
from .errors import OrderingViolation

#: How many blob checks run concurrently. Bounded rather than an unbounded `gather` over
#: every blob at once: a restored instance can hold hundreds of thousands of them, and
#: opening that many file handles simultaneously is its own failure mode.
CONCURRENCY = 32


async def verify_restore(
    db: Database, blob_root: Path | str, *, require_blobs_present: bool = True
) -> VerificationReport:
    """Walk every blob reference in the restored data and confirm it genuinely resolves.

    `require_blobs_present` is what makes §3's ordering claim real rather than asserted:
    verifying against a blob store that has not been restored yet would report every
    reference as orphaned and prove nothing, so that call is refused rather than answered
    with a result that looks like information.
    """
    root = Path(blob_root)
    if require_blobs_present and not any(root.rglob("*")):
        raise OrderingViolation(
            "the blob store is empty — restore blobs before verifying, or verification "
            "reports every reference as orphaned regardless of whether backups are intact"
        )

    referenced, locations = await _load_references(db)

    orphaned_logical = tuple(
        sorted(logical_id for logical_id in referenced if logical_id not in locations)
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _check(physical_hash: str, codec: StorageCodec) -> tuple[str, str]:
        async with semaphore:
            return await asyncio.to_thread(_check_file, root, physical_hash, codec)

    # Concurrent rather than a sequential loop (§6) — the same sequential-loop mistake this
    # project already corrected elsewhere, and a restore checking hundreds of thousands of
    # files one at a time is where it would hurt most.
    results = await asyncio.gather(
        *(
            _check(physical_hash, codec)
            for physical_hash, codec in locations.values()
        )
    )

    missing = tuple(sorted(value for status, value in results if status == "missing"))
    mismatched = tuple(sorted(value for status, value in results if status == "mismatch"))

    return VerificationReport(
        total_refs_checked=len(referenced) + len(locations),
        orphaned_logical_ids=orphaned_logical,
        orphaned_physical_files=missing,
        hash_mismatches=mismatched,
    )


def _check_file(root: Path, physical_hash: str, codec: StorageCodec) -> tuple[str, str]:
    path = sharded_path(root, physical_hash, codec)
    if not path.exists():
        return ("missing", physical_hash)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != physical_hash:
        # The file exists and its content no longer matches its own name. Because
        # physical_hash is self-consistent by construction, this is real corruption — a
        # bit-flipped backup, not a side effect of retention having run.
        return ("mismatch", physical_hash)
    return ("ok", physical_hash)


async def _load_references(db: Database):
    def _read(conn: sqlite3.Connection):
        referenced: set[str] = set()
        for table in BLOB_REFERENCING_TABLES:
            # Table names come from a module constant next to the schema, never from input.
            rows = conn.execute(f"SELECT DISTINCT logical_id FROM {table}").fetchall()  # noqa: S608
            referenced.update(r["logical_id"] for r in rows if r["logical_id"])
        locations: dict[str, tuple[str, StorageCodec]] = {}
        for row in conn.execute(
            "SELECT logical_id, physical_hash, codec FROM blob_locations"
        ).fetchall():
            locations[row["logical_id"]] = (row["physical_hash"], StorageCodec(row["codec"]))
        return referenced, locations

    return await db.run(_read)


__all__ = ["CONCURRENCY", "verify_restore"]
