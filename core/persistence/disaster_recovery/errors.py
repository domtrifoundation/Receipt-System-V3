"""Disaster Recovery error codes."""

from __future__ import annotations

SNAPSHOT_NOT_FOUND = "restore_snapshot_not_found"
NO_BACKUP_TARGET_REACHABLE = "restore_no_backup_target_reachable"
BLOB_RESTORE_INCOMPLETE = "restore_blob_restore_incomplete"
DATABASE_RESTORE_FAILED = "restore_database_restore_failed"
ORDERING_VIOLATION = "restore_ordering_violation"
VERIFICATION_FAILED = "restore_verification_failed"


class DisasterRecoveryError(Exception):
    code = DATABASE_RESTORE_FAILED


class OrderingViolation(DisasterRecoveryError):
    """Verification was asked for against a not-yet-blob-restored store.

    Refused rather than answered: verifying blob references against an empty blob store
    would report every reference as orphaned regardless of whether the backups are actually
    intact, which is a result that looks like information and is not (§3, §8).
    """

    code = ORDERING_VIOLATION


__all__ = [
    "BLOB_RESTORE_INCOMPLETE",
    "DATABASE_RESTORE_FAILED",
    "NO_BACKUP_TARGET_REACHABLE",
    "ORDERING_VIOLATION",
    "SNAPSHOT_NOT_FOUND",
    "VERIFICATION_FAILED",
    "DisasterRecoveryError",
    "OrderingViolation",
]
