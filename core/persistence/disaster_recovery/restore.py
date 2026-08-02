"""Full-instance and single-user restore (`v3-deepdive-33-disaster-recovery.md` §3, §5).

**Blobs first, then the database, then verify.** That ordering is not a preference: if the
database were restored first, "does every referenced blob exist" would trivially fail against
an empty blob store regardless of whether the backups are actually intact — the check would
run, produce a result, and tell you nothing. Restoring blobs first is the only ordering under
which verification means something.

**Single-user restore is supported and explicitly scoped** (§5, and the parent's §12). A
user's own canonical database and blob subset are structurally independent, so restoring just
those is coherent. It never touches `GLOBAL`-layer data — Architect's shared moderation queue
and vendor directory, temporal_learning's promoted facts — because that data is referenced by
everyone and cannot be rolled back for one user without risking inconsistency for everyone
else. And it is explicitly **not** a substitute for a full-instance restore when the
underlying cause might have touched shared state.

The blob-restore step reads from the same `BackupTarget` registry the write path fans out to.
One-of-N is enough to restore a given blob — that is what redundant targets are for — so a
single unreachable target is a degradation, not a failed restore.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import uuid
from pathlib import Path

from ..blob_store.backup.base import BackupRegistry
from ..blob_store.store import sha256_hex, sharded_path
from ..contracts import StorageCodec, utcnow
from ..db.connection import Database
from . import errors
from .contracts import RestoreJob, RestoreScope, RestoreStage, VerificationReport
from .verify import CONCURRENCY, verify_restore


async def restore_instance(
    target_dir: Path | str,
    snapshot_id: str,
    *,
    snapshot_source: Path | str,
    backups: BackupRegistry,
    scope: RestoreScope = RestoreScope.FULL_INSTANCE,
    user_id: str = "",
) -> RestoreJob:
    """Rebuild an instance from backups. Returns a job, never raises across the boundary.

    `snapshot_source` is the day-rotated SQLite checkpoint to restore from. It is a separate
    argument rather than derived from `snapshot_id` because where snapshots live is an
    operator's deployment decision, not something this module should assume.
    """
    target = Path(target_dir)
    job = RestoreJob(
        job_id=uuid.uuid4().hex,
        snapshot_id=snapshot_id,
        scope=scope,
        stage=RestoreStage.PENDING,
        started_at=utcnow(),
        user_id=user_id,
    )

    snapshot = Path(snapshot_source)
    if not snapshot.exists():
        return job.with_stage(
            RestoreStage.FAILED,
            error_code=errors.SNAPSHOT_NOT_FOUND,
            error_detail=str(snapshot),
        )

    reachable = await backups.reachability()
    if not any(reachable.values()):
        return job.with_stage(
            RestoreStage.FAILED,
            error_code=errors.NO_BACKUP_TARGET_REACHABLE,
            error_detail=f"no enabled backup target responded: {sorted(reachable)}",
        )

    # 1. Blobs, fully, before anything else.
    job = job.with_stage(RestoreStage.RESTORING_BLOBS)
    blob_root = target / "blobs"
    restored, failed = await _restore_blob_store(snapshot, blob_root, backups)

    # 2. Then the database.
    job = job.with_stage(RestoreStage.RESTORING_DATABASE, blobs_restored=restored)
    db_path = target / "canonical.sqlite"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, db_path)
    except OSError as exc:
        return job.with_stage(
            RestoreStage.FAILED,
            error_code=errors.DATABASE_RESTORE_FAILED,
            error_detail=str(exc),
        )

    # 3. Then verification, which is only meaningful in that order.
    job = job.with_stage(RestoreStage.VERIFYING)
    db = Database(db_path)
    try:
        report = await verify_restore(db, blob_root, require_blobs_present=restored > 0)
    except errors.OrderingViolation as exc:
        return job.with_stage(
            RestoreStage.FAILED,
            error_code=exc.code,
            error_detail=str(exc),
        )
    finally:
        db.close()

    stage = RestoreStage.COMPLETE if report.clean else RestoreStage.COMPLETE_WITH_ISSUES
    detail = "" if report.clean else _describe(report, failed)
    return job.with_stage(
        stage,
        report=report,
        error_code="" if report.clean else errors.BLOB_RESTORE_INCOMPLETE,
        error_detail=detail,
    )


async def _restore_blob_store(
    snapshot: Path, blob_root: Path, backups: BackupRegistry
) -> tuple[int, list[str]]:
    """Pull every blob the snapshot's own mapping table names, from any reachable target.

    Reads the mapping out of the *snapshot* rather than the not-yet-restored live database,
    because the blob set to restore is defined by what the snapshot references — that is the
    whole point of restoring the two together.
    """
    staging = blob_root.parent / "_snapshot_read.sqlite"
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot, staging)
    conn = sqlite3.connect(str(staging))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT logical_id, physical_hash, codec FROM blob_locations"
        ).fetchall()
        wanted = [(r["physical_hash"], StorageCodec(r["codec"])) for r in rows]
    finally:
        conn.close()
        staging.unlink(missing_ok=True)

    blob_root.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _pull(physical_hash: str, codec: StorageCodec) -> tuple[bool, str]:
        async with semaphore:
            for target in backups.enabled_targets():
                data = await target.fetch(physical_hash)
                if data is None:
                    continue
                if sha256_hex(data) != physical_hash:
                    # A backup copy that does not match its own address is corrupt. Skip it
                    # and try the next target rather than writing known-bad bytes into the
                    # restored store — the redundancy exists for exactly this.
                    continue
                path = sharded_path(blob_root, physical_hash, codec)
                path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, data)
                return True, physical_hash
            return False, physical_hash

    results = await asyncio.gather(*(_pull(h, c) for h, c in wanted))
    restored = sum(1 for ok, _ in results if ok)
    failed = [h for ok, h in results if not ok]
    return restored, failed


def _describe(report: VerificationReport, failed: list[str]) -> str:
    return (
        f"{len(report.orphaned_logical_ids)} logical_ids with no mapping, "
        f"{len(report.orphaned_physical_files)} missing files, "
        f"{len(report.hash_mismatches)} corrupt files, "
        f"{len(failed)} blobs no reachable target could supply"
    )


__all__ = ["restore_instance"]
