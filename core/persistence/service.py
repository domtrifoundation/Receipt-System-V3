"""The thin service layer every Persistence RPC in `persistence.proto` maps onto.

Deliberately **transport-agnostic**: it speaks contract types, not protobuf messages, and
imports no `grpc`. The generated servicer is a one-line-per-RPC adapter over this class, so
the actual behaviour is testable without standing up a server and cannot quietly diverge
between the gRPC path and any in-process caller.

Thin means thin. Every method here does three things at most: assemble the collaborators,
call into the module that owns the logic, and turn an internal exception into an error code.
No business rule lives in this file — if one shows up here, it belongs in `db/`,
`blob_store/`, `historian/`, `reimport/`, `exports/`, `archive_sync/` or
`disaster_recovery/` instead.

**Errors are data.** Nothing raises out of these methods. `errors.code_for` maps an internal
exception to the boundary-stable code that goes in the response's own `error_code` field.
"""

from __future__ import annotations

from pathlib import Path

from common.frozen_dict import FrozenDict

from . import errors
from .archive_sync.contracts import SyncJob, SyncTarget
from .archive_sync.sync import ArchiveSync
from .blob_store.backup.base import BackupRegistry
from .blob_store.store import BlobStore
from .contracts import (
    BlobReadResult,
    BlobWriteResult,
    Receipt,
    ReceiptReadResult,
    StorageCodec,
    WriteResult,
)
from .db.connection import Database, default_blob_root, default_db_path
from .db.receipts import ReceiptRepository
from .disaster_recovery.contracts import RestoreJob, RestoreScope, VerificationReport
from .disaster_recovery.restore import restore_instance
from .disaster_recovery.verify import verify_restore
from .exports.contracts import ExportResult
from .exports.registry import ExportRegistry
from .historian.contracts import HistoryEntry
from .historian.query import HistorianQuery
from .historian.writer import HistorianWriter
from .metrics import Metrics
from .reimport.conflict_resolution import ReimportService
from .reimport.contracts import ReimportRequest, ReimportResult


class PersistenceService:
    """One user's Persistence surface.

    Per-user, because the isolation boundary is structural: a user's data is a separate
    database in a separate folder, not a `WHERE user_id = ?` applied consistently by
    convention (`docs/PRINCIPLES.md` §4.5). A bug in a role check at the Gateway is a real
    problem but not a catastrophic one, because another user's rows are not in this
    connection at all.
    """

    def __init__(
        self,
        user_id: str,
        *,
        top_level: Path | str | None = None,
        db: Database | None = None,
        blob_root: Path | str | None = None,
        backups: BackupRegistry | None = None,
        exports: ExportRegistry | None = None,
        archive_sync: ArchiveSync | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.user_id = user_id
        self.db = db or Database(default_db_path(top_level, user_id))
        self.blobs = BlobStore(
            self.db, blob_root or default_blob_root(top_level, user_id), backups
        )
        self.historian = HistorianWriter(self.db)
        self.history = HistorianQuery(self.db)
        self.receipts = ReceiptRepository(self.db, self.historian)
        self.exports = exports or ExportRegistry()
        self.archive_sync = archive_sync
        self.metrics = metrics or Metrics()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ canonical
    async def get_receipt(self, receipt_id: str) -> ReceiptReadResult:
        try:
            receipt = await self.receipts.get(receipt_id)
        except errors.PersistenceError as exc:
            return ReceiptReadResult(ok=False, error_code=exc.code, error_detail=str(exc))
        if receipt is None:
            return ReceiptReadResult(
                ok=False, error_code=errors.RECEIPT_NOT_FOUND, error_detail=receipt_id
            )
        return ReceiptReadResult(ok=True, receipt=receipt)

    async def save_receipt(self, receipt: Receipt, *, actor: str) -> WriteResult:
        if not actor:
            return WriteResult(
                ok=False,
                error_code=errors.INVALID_REQUEST,
                error_detail="actor is required — an unattributed write has no audit value",
            )
        try:
            saved, event = await self.receipts.save(receipt, actor=actor)
        except Exception as exc:  # noqa: BLE001 - nothing raises across this boundary
            return WriteResult(
                ok=False, error_code=errors.code_for(exc), error_detail=str(exc)
            )
        self.metrics.increment("canonical_writes")
        self.metrics.increment("historian_data_events")
        return WriteResult(
            ok=True, receipt_id=saved.receipt_id, historian_event_id=event.event_id
        )

    async def list_receipts(
        self, *, after_receipt_id: str = "", limit: int = 500
    ) -> tuple[Receipt, ...]:
        return await self.receipts.list_for_user(
            self.user_id, after_receipt_id=after_receipt_id, limit=limit
        )

    # ---------------------------------------------------------------- blobs
    async def put_blob(
        self,
        original_bytes: bytes,
        *,
        stored_bytes: bytes | None = None,
        codec: StorageCodec = StorageCodec.ORIGINAL,
    ) -> BlobWriteResult:
        result = await self.blobs.put(
            original_bytes, stored_bytes=stored_bytes, codec=codec
        )
        if result.ok:
            self.metrics.increment(
                "blob_dedup_hits" if result.deduplicated else "blob_writes"
            )
            if result.durably_backed_up:
                self.metrics.increment("blob_backup_confirmed")
            if result.fully_synced:
                self.metrics.increment("blob_backup_full")
            if result.failed_targets:
                self.metrics.increment("blob_backup_failed", len(result.failed_targets))
        return result

    async def get_blob(self, logical_id: str, *, verify: bool = False) -> BlobReadResult:
        result = await self.blobs.get(logical_id, verify=verify)
        if result.error_code == errors.BLOB_CORRUPT:
            self.metrics.increment("verify_hash_mismatches")
        return result

    # ------------------------------------------------------------ historian
    async def get_receipt_history(self, receipt_id: str) -> tuple[HistoryEntry, ...]:
        return await self.history.get_receipt_history(receipt_id)

    # -------------------------------------------------------------- exports
    def list_export_providers(self) -> tuple[str, ...]:
        return self.exports.names()

    async def generate_export(
        self, provider_name: str, params: FrozenDict | None = None
    ) -> ExportResult:
        result = await self.exports.generate(provider_name, self.user_id, params)
        if result.ok:
            self.metrics.increment("exports_generated")
        return result

    # ------------------------------------------------------------- reimport
    async def submit_reimport(
        self, request: ReimportRequest, service: ReimportService | None = None
    ) -> ReimportResult:
        reimport = service or ReimportService(self.db, self.receipts, self.history)
        result = await reimport.submit(request)
        if result.conflicts:
            self.metrics.increment("reimport_conflicts", len(result.conflicts))
        return result

    # --------------------------------------------------------- archive sync
    async def sync_archives(self, target: SyncTarget) -> SyncJob:
        if self.archive_sync is None:
            from .archive_sync import errors as sync_errors  # noqa: PLC0415

            return SyncJob(
                ok=False,
                user_id=self.user_id,
                error_code=sync_errors.UNKNOWN_PROVIDER,
                error_detail="archive sync is not configured for this instance",
            )
        job = await self.archive_sync.sync_new_archives(target)
        self.metrics.increment("archive_sync_mirrored", job.mirrored)
        if not job.ok and job.error_code:
            self.metrics.increment("archive_sync_paused")
        return job

    # ----------------------------------------------------- disaster recovery
    async def verify_integrity(self, *, require_blobs_present: bool = True):
        try:
            report = await verify_restore(
                self.db, self.blobs.root, require_blobs_present=require_blobs_present
            )
        except Exception as exc:  # noqa: BLE001
            return VerificationReport(total_refs_checked=0), errors.code_for(exc), str(exc)
        self.metrics.increment("verify_hash_mismatches", len(report.hash_mismatches))
        return report, "", ""

    async def start_restore(
        self,
        target_dir: Path | str,
        snapshot_id: str,
        *,
        snapshot_source: Path | str,
        backups: BackupRegistry,
        scope: RestoreScope = RestoreScope.FULL_INSTANCE,
    ) -> RestoreJob:
        return await restore_instance(
            target_dir,
            snapshot_id,
            snapshot_source=snapshot_source,
            backups=backups,
            scope=scope,
            user_id=self.user_id if scope is RestoreScope.SINGLE_USER else "",
        )


__all__ = ["PersistenceService"]
