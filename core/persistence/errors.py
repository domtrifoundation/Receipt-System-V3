"""Persistence error taxonomy.

Two halves, deliberately:

- **Error *codes*** — the stable strings that cross the gRPC boundary in every result
  object's own `error_code` field (`docs/PRINCIPLES.md` §4.1). These are what callers
  branch on; they are only ever added to, never renamed, for the same reason a `.proto`
  field number is never reused.
- **Internal exceptions** — real types for the *internal* call path, where distinguishing a
  missing blob from a corrupt one genuinely changes what the code does next. These never
  escape this package; `service.py` converts them into codes.

Persistence has no Auth-style "fail loudly" exception. Every boundary result here is data.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

# --- error codes (boundary-stable strings) -----------------------------------
OK = ""
BLOB_NOT_FOUND = "blob_not_found"
BLOB_LOCATION_MISSING = "blob_location_missing"
BLOB_CORRUPT = "blob_corrupt"
BLOB_WRITE_FAILED = "blob_write_failed"
BACKUP_UNCONFIRMED = "backup_unconfirmed"
RECEIPT_NOT_FOUND = "receipt_not_found"
WRITE_CONFLICT = "write_conflict"
TRANSACTION_FAILED = "transaction_failed"
SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
DATABASE_UNAVAILABLE = "database_unavailable"
INVALID_REQUEST = "invalid_request"

#: Human-readable hint per code, for a caller that wants to say something useful without
#: re-deriving the meaning of every string. A module-level dict-shaped constant, so it is a
#: `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — a lookup table, not a mutable registry.
ERROR_HINTS = FrozenDict(
    {
        BLOB_NOT_FOUND: "No blob is stored for that logical_id.",
        BLOB_LOCATION_MISSING: (
            "The logical_id is referenced but has no BlobLocation mapping — a distinct "
            "failure from a missing physical file, implying a different repair."
        ),
        BLOB_CORRUPT: (
            "The stored file's recomputed SHA-256 does not match its own physical_hash."
        ),
        BLOB_WRITE_FAILED: "The local blob write did not complete.",
        BACKUP_UNCONFIRMED: "No enabled backup target confirmed the write.",
        RECEIPT_NOT_FOUND: "No canonical receipt row with that id for that user.",
        WRITE_CONFLICT: "Canonical state changed underneath this write.",
        TRANSACTION_FAILED: (
            "The data write and its Historian event were rolled back together."
        ),
        SCHEMA_VERSION_MISMATCH: "The row's schema_version is ahead of this build's.",
        DATABASE_UNAVAILABLE: "The per-user database could not be opened.",
        INVALID_REQUEST: "The request itself was malformed.",
    }
)


# --- internal exceptions -----------------------------------------------------
class PersistenceError(Exception):
    """Base for everything this package raises internally. Never crosses the boundary."""

    code = TRANSACTION_FAILED


class BlobNotFound(PersistenceError):
    code = BLOB_NOT_FOUND


class BlobLocationMissing(PersistenceError):
    """A `logical_id` exists as a reference but has no mapping row.

    Deliberately distinct from `BlobNotFound`: a missing mapping and a missing file imply
    different repairs, which is exactly why `VerificationReport` reports them separately.
    """

    code = BLOB_LOCATION_MISSING


class BlobCorrupt(PersistenceError):
    code = BLOB_CORRUPT


class ReceiptNotFound(PersistenceError):
    code = RECEIPT_NOT_FOUND


class SchemaVersionMismatch(PersistenceError):
    code = SCHEMA_VERSION_MISMATCH


class DatabaseUnavailable(PersistenceError):
    code = DATABASE_UNAVAILABLE


def code_for(exc: BaseException) -> str:
    """The boundary code for an internal exception, or the generic failure code."""
    return getattr(exc, "code", TRANSACTION_FAILED)


__all__ = [
    "BACKUP_UNCONFIRMED",
    "BLOB_CORRUPT",
    "BLOB_LOCATION_MISSING",
    "BLOB_NOT_FOUND",
    "BLOB_WRITE_FAILED",
    "DATABASE_UNAVAILABLE",
    "ERROR_HINTS",
    "INVALID_REQUEST",
    "OK",
    "RECEIPT_NOT_FOUND",
    "SCHEMA_VERSION_MISMATCH",
    "TRANSACTION_FAILED",
    "WRITE_CONFLICT",
    "BlobCorrupt",
    "BlobLocationMissing",
    "BlobNotFound",
    "DatabaseUnavailable",
    "PersistenceError",
    "ReceiptNotFound",
    "SchemaVersionMismatch",
    "code_for",
]
