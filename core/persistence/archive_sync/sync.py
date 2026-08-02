"""The mirror job itself (`v3-deepdive-32-archive-sync.md` §4).

A Background Workers idle-time job, not a live filesystem watch — this is a convenience
feature with no urgency, and a watcher would be real machinery bought for nothing.

**Three behaviours here are the resolved design, not implementation choices:**

1. **The cursor advances only after a confirmed successful upload.** That single ordering
   rule is what makes an interrupted job resume correctly rather than re-uploading everything
   or silently skipping unmirrored items.
2. **External filenames carry date plus a short hash suffix from the start.** Content-
   addressable internal naming does not map to a human-friendly external filename, so two
   receipts producing the same generated name is unlikely but possible — designing the
   distinguishing detail in now is much cheaper than a retroactive rename scheme after a
   production collision.
3. **A missing or inaccessible target notifies, then pauses** (§8). Never silently continue
   retrying, which masks a real problem from the person who needs to know about it; never
   auto-recreate the folder, which risks undoing something the user deliberately did.

**Retention parity is deliberately absent** (§8's second resolution): a purged internal blob
is *not* removed from the external mirror. That copy is the user's own, outside this system's
retention decisions. An opt-in "mirror deletions too" toggle is a real future option; it is
not the default and nothing here should quietly become it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from ..blob_store.store import BlobStore
from ..contracts import Receipt, utcnow
from ..db.connection import Database
from ..db.receipts import ReceiptRepository
from . import errors
from .contracts import SyncCursor, SyncJob, SyncState, SyncTarget
from .providers.base import SyncProviderRegistry


class NotificationSink(Protocol):
    """Notifications API's own entry point, behind one small interface (§1.3)."""

    async def notify(self, user_id: str, kind: str, detail: str) -> None: ...


def external_name(receipt: Receipt) -> str:
    """`2026-07-17_ABC-Corp_a1b2c3d4.webp`-shaped, collision-resistant by construction.

    Date plus vendor gives a human-browsable name; the short `logical_id` prefix is what
    makes two receipts with the same date and vendor genuinely distinct files rather than
    one silently overwriting the other.
    """
    date = (
        receipt.transaction_date.date().isoformat()
        if receipt.transaction_date
        else receipt.created_at.date().isoformat()
    )
    vendor = "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in (receipt.vendor_name or "unknown")
    ).strip("-") or "unknown"
    return f"{date}_{vendor}_{receipt.blob.logical_id[:8]}"


class ArchiveSync:
    """One user's outbound mirror."""

    def __init__(
        self,
        db: Database,
        blobs: BlobStore,
        providers: SyncProviderRegistry,
        notifications: NotificationSink | None = None,
        receipts: ReceiptRepository | None = None,
    ) -> None:
        self._db = db
        self._blobs = blobs
        self._providers = providers
        self._notifications = notifications
        self._receipts = receipts or ReceiptRepository(db)

    # --------------------------------------------------------------- cursor
    async def get_cursor(self, user_id: str, target_name: str) -> SyncCursor:
        def _read(conn: sqlite3.Connection) -> SyncCursor:
            row = conn.execute(
                "SELECT * FROM archive_sync_cursor WHERE user_id = ? AND target_name = ?",
                (user_id, target_name),
            ).fetchone()
            if row is None:
                return SyncCursor(user_id=user_id, target_name=target_name)
            return SyncCursor(
                user_id=row["user_id"],
                target_name=row["target_name"],
                last_receipt_id=row["last_receipt_id"],
                last_synced_at=datetime.fromisoformat(row["last_synced_at"])
                if row["last_synced_at"]
                else None,
                paused_reason=row["paused_reason"],
            )

        return await self._db.run(_read)

    async def _save_cursor(self, cursor: SyncCursor) -> None:
        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO archive_sync_cursor (user_id, target_name,"
                " last_receipt_id, last_synced_at, paused_reason) VALUES (?,?,?,?,?)",
                (
                    cursor.user_id,
                    cursor.target_name,
                    cursor.last_receipt_id,
                    cursor.last_synced_at.isoformat() if cursor.last_synced_at else None,
                    cursor.paused_reason,
                ),
            )

        await self._db.transaction(_write)

    async def resume(self, user_id: str, target_name: str) -> SyncCursor:
        """Clear a pause. Only ever called because the user explicitly re-confirmed."""
        cursor = await self.get_cursor(user_id, target_name)
        resumed = SyncCursor(
            user_id=cursor.user_id,
            target_name=cursor.target_name,
            last_receipt_id=cursor.last_receipt_id,
            last_synced_at=cursor.last_synced_at,
            paused_reason="",
        )
        await self._save_cursor(resumed)
        return resumed

    # ----------------------------------------------------------------- job
    async def sync_new_archives(self, target: SyncTarget, *, batch: int = 200) -> SyncJob:
        """Mirror everything after the cursor, advancing it one confirmed upload at a time."""
        provider = self._providers.get(target.provider_name)
        if provider is None:
            return SyncJob(
                ok=False,
                user_id=target.user_id,
                error_code=errors.UNKNOWN_PROVIDER,
                error_detail=target.provider_name,
            )

        cursor = await self.get_cursor(target.user_id, target.provider_name)
        if cursor.paused_reason:
            return SyncJob(
                ok=False,
                user_id=target.user_id,
                cursor=cursor,
                state=SyncState.PAUSED,
                error_code=errors.SYNC_PAUSED,
                error_detail=cursor.paused_reason,
            )

        if not await provider.is_reachable():
            return await self._pause(
                cursor,
                "the external target is missing or access was revoked; sync is paused until "
                "you re-confirm or reconfigure it",
                errors.TARGET_UNREACHABLE,
            )

        pending = await self._receipts.list_for_user(
            target.user_id, after_receipt_id=cursor.last_receipt_id, limit=batch
        )
        mirrored = 0
        skipped = 0
        for receipt in pending:
            result = await provider.mirror(
                receipt.blob.logical_id, f"{target.target_path}/{external_name(receipt)}"
            )
            if not result.ok:
                if result.error_code == errors.TARGET_MISSING:
                    return await self._pause(
                        cursor,
                        f"the external target became unavailable mid-run: {result.error_detail}",
                        errors.TARGET_UNREACHABLE,
                    )
                # A single blob failing is not a reason to pause the whole mirror or to
                # advance past it — it stays pending and the next pass retries it.
                skipped += 1
                break
            mirrored += 1
            cursor = SyncCursor(
                user_id=cursor.user_id,
                target_name=cursor.target_name,
                last_receipt_id=receipt.receipt_id,
                last_synced_at=utcnow(),
            )
            # Persisted per item, not once at the end: a crash mid-batch must not lose the
            # record of what already made it across.
            await self._save_cursor(cursor)

        return SyncJob(
            ok=True,
            user_id=target.user_id,
            mirrored=mirrored,
            skipped=skipped,
            cursor=cursor,
            state=SyncState.ACTIVE,
        )

    async def _pause(self, cursor: SyncCursor, reason: str, code: str) -> SyncJob:
        paused = SyncCursor(
            user_id=cursor.user_id,
            target_name=cursor.target_name,
            last_receipt_id=cursor.last_receipt_id,
            last_synced_at=cursor.last_synced_at,
            paused_reason=reason,
        )
        await self._save_cursor(paused)
        if self._notifications is not None:
            await self._notifications.notify(cursor.user_id, "archive_sync_paused", reason)
        return SyncJob(
            ok=False,
            user_id=cursor.user_id,
            cursor=paused,
            state=SyncState.PAUSED,
            error_code=code,
            error_detail=reason,
        )


__all__ = ["ArchiveSync", "NotificationSink", "external_name"]
