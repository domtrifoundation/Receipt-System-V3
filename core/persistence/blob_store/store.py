"""Content-addressable blob store (§4), with the corrected two-layer address scheme (§3.3).

Read this before changing anything here:

- **`logical_id` = SHA-256 of the ORIGINAL uploaded bytes**, computed before any
  re-encoding. It is the identity every reference in the system uses and it never changes.
  It is *not* a filename and is never used to locate a file.
- **`physical_hash` = SHA-256 of whatever is stored right now.** It *is* the filename, via
  the two-level sharded layout (§4.2). It is recomputed whenever the stored representation
  changes, so a stored file always genuinely matches its own name.

They are joined by `blob_locations`. Collapsing them back into one value is the bug that was
caught before it shipped: retention purges the original upload, so a filename derived from
the identity hash would stop matching its own contents the moment that purge ran — breaking
content-addressability by definition and breaking Disaster Recovery's verification pass for
every blob, permanently (`v3-deepdive-33-disaster-recovery.md` §4).

Blobs carry **zero embedded metadata** (§4.3). Tagging a file changes its bytes, which
changes its hash; the browsable-copy design that would have worked around that was scoped
and deliberately reversed, because browsing is Search/Query's job through structured SQLite
data and an Explorer-only answer would not work outside single-user self-hosted installs.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ..contracts import (
    BackupConfirmation,
    BlobLocation,
    BlobReadResult,
    BlobRef,
    BlobWriteResult,
    StorageCodec,
    utcnow,
)
from ..db.connection import Database
from ..errors import (
    BACKUP_UNCONFIRMED,
    BLOB_CORRUPT,
    BLOB_LOCATION_MISSING,
    BLOB_NOT_FOUND,
    BLOB_WRITE_FAILED,
)
from .backup.base import BackupRegistry


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sharded_path(root: Path, physical_hash: str, codec: StorageCodec) -> Path:
    """`blobs/ab/cd/abcd…ef.webp` — two levels of two-hex-character sharding (§4.2).

    The same technique Git's own object store uses, for the same reason: a single directory
    holding hundreds of thousands of entries is a real filesystem-performance problem that
    is cheap to avoid on day one and expensive to retrofit.
    """
    suffix = "bin" if codec is StorageCodec.ORIGINAL else codec.value
    return root / physical_hash[:2] / physical_hash[2:4] / f"{physical_hash}.{suffix}"


class BlobStore:
    """The only thing in this system that writes image bytes to disk."""

    def __init__(self, db: Database, root: Path | str, backups: BackupRegistry | None = None):
        self._db = db
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._backups = backups or BackupRegistry()

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------ read
    def location_sync(self, logical_id: str) -> BlobLocation | None:
        def _read(conn: sqlite3.Connection) -> BlobLocation | None:
            row = conn.execute(
                "SELECT * FROM blob_locations WHERE logical_id = ?", (logical_id,)
            ).fetchone()
            return _row_to_location(row) if row else None

        return self._db.run_sync(_read)

    async def location(self, logical_id: str) -> BlobLocation | None:
        def _read(conn: sqlite3.Connection) -> BlobLocation | None:
            row = conn.execute(
                "SELECT * FROM blob_locations WHERE logical_id = ?", (logical_id,)
            ).fetchone()
            return _row_to_location(row) if row else None

        return await self._db.run(_read)

    def resolve_blob_path_sync(self, logical_id: str) -> Path | None:
        """`logical_id` → one indexed lookup → `physical_hash` → the real sharded path.

        Every consumer that needs actual bytes goes through this. Nothing anywhere assumes
        `logical_id` is a filename — that assumption is precisely the corrected bug.
        """
        loc = self.location_sync(logical_id)
        if loc is None:
            return None
        return sharded_path(self._root, loc.physical_hash, loc.codec)

    async def resolve_blob_path(self, logical_id: str) -> Path | None:
        loc = await self.location(logical_id)
        return None if loc is None else sharded_path(self._root, loc.physical_hash, loc.codec)

    async def get(self, logical_id: str, *, verify: bool = False) -> BlobReadResult:
        loc = await self.location(logical_id)
        if loc is None:
            return BlobReadResult(
                ok=False,
                error_code=BLOB_LOCATION_MISSING,
                error_detail=f"no BlobLocation for {logical_id}",
            )
        path = sharded_path(self._root, loc.physical_hash, loc.codec)
        if not path.exists():
            return BlobReadResult(
                ok=False,
                blob_ref=BlobRef(logical_id),
                location=loc,
                error_code=BLOB_NOT_FOUND,
                error_detail=str(path),
            )
        data = path.read_bytes()
        if verify and sha256_hex(data) != loc.physical_hash:
            # A file that exists but no longer matches its own name is silent corruption —
            # exactly what a self-consistent physical_hash makes detectable.
            return BlobReadResult(
                ok=False,
                blob_ref=BlobRef(logical_id),
                location=loc,
                error_code=BLOB_CORRUPT,
                error_detail=f"content does not match physical_hash {loc.physical_hash}",
            )
        return BlobReadResult(ok=True, blob_ref=BlobRef(logical_id), location=loc, data=data)

    # ----------------------------------------------------------------- write
    async def put(
        self,
        original_bytes: bytes,
        *,
        stored_bytes: bytes | None = None,
        codec: StorageCodec = StorageCodec.ORIGINAL,
    ) -> BlobWriteResult:
        """Store one blob and fan out to every enabled backup target.

        `original_bytes` is what `logical_id` is computed from — always, regardless of what
        is actually written. `stored_bytes` defaults to the original; pass the re-encoded
        bytes when the archival copy is what gets stored.

        **Idempotency**: the same original bytes uploaded twice produce one stored blob and
        two references, never two copies. That is the dedup guarantee content-addressing
        exists for, and it is checked against `logical_id` — the identity — not against
        whatever the current physical representation happens to be.
        """
        logical_id = sha256_hex(original_bytes)
        existing = await self.location(logical_id)
        if existing is not None:
            return BlobWriteResult(
                ok=True,
                blob_ref=BlobRef(logical_id),
                deduplicated=True,
                durably_backed_up=True,
                fully_synced=True,
                confirmed_targets=await self._confirmed_targets(logical_id),
            )

        payload = original_bytes if stored_bytes is None else stored_bytes
        physical_hash = sha256_hex(payload)
        path = sharded_path(self._root, physical_hash, codec)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, payload)
        except OSError as exc:
            return BlobWriteResult(ok=False, error_code=BLOB_WRITE_FAILED, error_detail=str(exc))

        location = BlobLocation(
            logical_id=logical_id,
            physical_hash=physical_hash,
            codec=codec,
            byte_size=len(payload),
            updated_at=utcnow(),
        )
        await self._db.transaction(lambda conn: _upsert_location(conn, location))

        fan_out = await self._backups.fan_out(physical_hash, payload)
        if fan_out.confirmed:
            await self._db.transaction(
                lambda conn: _record_confirmations(conn, logical_id, fan_out.confirmed)
            )
        return BlobWriteResult(
            ok=True,
            blob_ref=BlobRef(logical_id),
            durably_backed_up=fan_out.durably_backed_up,
            fully_synced=fan_out.fully_synced,
            confirmed_targets=fan_out.confirmed,
            failed_targets=fan_out.failed,
            # A local write that no enabled target confirmed is still `ok` — the bytes are
            # on disk. The code says the *backup* is unconfirmed; conflating the two states
            # into one "saved" flag is what §4.4 rules out.
            error_code="" if (fan_out.durably_backed_up or not fan_out.enabled_count)
            else BACKUP_UNCONFIRMED,
        )

    async def re_encode(
        self, logical_id: str, new_bytes: bytes, codec: StorageCodec
    ) -> BlobWriteResult:
        """Replace what is physically stored for an existing identity.

        This is the operation the whole two-layer scheme exists for: retention purging the
        original, or an owner-initiated codec migration. `blob_locations.physical_hash` and
        `.codec` change; `logical_id` does not, so no reference anywhere — Historian, Audit,
        every export ever generated — needs rewriting.
        """
        current = await self.location(logical_id)
        if current is None:
            return BlobWriteResult(
                ok=False, error_code=BLOB_LOCATION_MISSING, error_detail=logical_id
            )
        physical_hash = sha256_hex(new_bytes)
        path = sharded_path(self._root, physical_hash, codec)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, new_bytes)
        except OSError as exc:
            return BlobWriteResult(ok=False, error_code=BLOB_WRITE_FAILED, error_detail=str(exc))

        location = BlobLocation(
            logical_id=logical_id,
            physical_hash=physical_hash,
            codec=codec,
            byte_size=len(new_bytes),
            updated_at=utcnow(),
        )
        await self._db.transaction(lambda conn: _upsert_location(conn, location))

        old_path = sharded_path(self._root, current.physical_hash, current.codec)
        if old_path != path and old_path.exists() and not await self._is_referenced(
            current.physical_hash
        ):
            old_path.unlink(missing_ok=True)

        fan_out = await self._backups.fan_out(physical_hash, new_bytes)
        if fan_out.confirmed:
            await self._db.transaction(
                lambda conn: _record_confirmations(conn, logical_id, fan_out.confirmed)
            )
        return BlobWriteResult(
            ok=True,
            blob_ref=BlobRef(logical_id),
            durably_backed_up=fan_out.durably_backed_up,
            fully_synced=fan_out.fully_synced,
            confirmed_targets=fan_out.confirmed,
            failed_targets=fan_out.failed,
        )

    async def backup_confirmations(self, logical_id: str) -> tuple[BackupConfirmation, ...]:
        def _read(conn: sqlite3.Connection) -> tuple[BackupConfirmation, ...]:
            rows = conn.execute(
                "SELECT * FROM blob_backup_state WHERE logical_id = ?", (logical_id,)
            ).fetchall()
            return tuple(
                BackupConfirmation(
                    logical_id=r["logical_id"],
                    target_name=r["target_name"],
                    confirmed_at=_dt(r["confirmed_at"]),
                )
                for r in rows
            )

        return await self._db.run(_read)

    async def _confirmed_targets(self, logical_id: str) -> tuple[str, ...]:
        return tuple(c.target_name for c in await self.backup_confirmations(logical_id))

    async def _is_referenced(self, physical_hash: str) -> bool:
        def _count(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM blob_locations WHERE physical_hash = ?",
                (physical_hash,),
            ).fetchone()
            return int(row["n"])

        return await self._db.run(_count) > 0


# --------------------------------------------------------------------- helpers
def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file and rename, so a crash never leaves a half-written blob whose
    hash silently disagrees with its own filename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _upsert_location(conn: sqlite3.Connection, loc: BlobLocation) -> None:
    conn.execute(
        "INSERT INTO blob_locations (logical_id, physical_hash, codec, byte_size, updated_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(logical_id) DO UPDATE SET physical_hash=excluded.physical_hash,"
        " codec=excluded.codec, byte_size=excluded.byte_size, updated_at=excluded.updated_at",
        (loc.logical_id, loc.physical_hash, loc.codec.value, loc.byte_size,
         loc.updated_at.isoformat()),
    )


def _record_confirmations(
    conn: sqlite3.Connection, logical_id: str, targets: tuple[str, ...]
) -> None:
    now = utcnow().isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO blob_backup_state (logical_id, target_name, confirmed_at)"
        " VALUES (?,?,?)",
        [(logical_id, name, now) for name in targets],
    )


def _row_to_location(row: sqlite3.Row) -> BlobLocation:
    return BlobLocation(
        logical_id=row["logical_id"],
        physical_hash=row["physical_hash"],
        codec=StorageCodec(row["codec"]),
        byte_size=int(row["byte_size"]),
        updated_at=_dt(row["updated_at"]),
    )


def _dt(value: str):
    from datetime import datetime  # noqa: PLC0415 - keeps the module import list small

    return datetime.fromisoformat(value)


__all__ = ["BlobStore", "sha256_hex", "sharded_path"]
