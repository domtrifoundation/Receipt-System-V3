"""Disaster Recovery contracts (`v3-deepdive-33-disaster-recovery.md` §3, §4).

Types only. Disaster Recovery owns **full-instance restore** — rebuilding a working instance
from the B2/Storj blob backups and the SQLite snapshot backups after catastrophic disk loss.
Distinct from the backup *mechanisms* (replication, not restore), from Reimport (single-user
reconciliation against canonical state), and from Historian (an audit trail, not a way to
reconstruct a database from backups at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class RestoreStage(str, Enum):
    """The stages in their required order. Blobs before SQLite, always — see `restore.py`."""

    PENDING = "pending"
    RESTORING_BLOBS = "restoring_blobs"
    RESTORING_DATABASE = "restoring_database"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    COMPLETE_WITH_ISSUES = "complete_with_issues"
    FAILED = "failed"


class RestoreScope(str, Enum):
    """Resolved scoping (§5, and the parent deep-dive's §12).

    `SINGLE_USER` is genuinely supported — a user's own database and blob subset are
    structurally independent, so restoring just those is coherent. It is explicitly **not** a
    substitute for a full-instance restore when the underlying cause might have touched
    shared state, and it never touches `GLOBAL`-layer data (Architect's shared moderation
    queue, temporal_learning's promoted facts): that data is inherently system-wide and
    cannot be rolled back for one user without risking inconsistency for everyone already
    referencing it.
    """

    FULL_INSTANCE = "full_instance"
    SINGLE_USER = "single_user"


@dataclass(frozen=True)
class VerificationReport:
    """Three distinct failure lists, deliberately not merged into one.

    A `logical_id` with no `BlobLocation` mapping, a `BlobLocation` pointing at a file that
    is not there, and a file that is there but no longer matches its own `physical_hash` are
    three different problems implying three different repairs. Reporting them as one count
    would lose exactly the information an operator needs.

    `clean` is True only when all three are empty — a restore is never reported as "mostly
    worked."
    """

    total_refs_checked: int
    orphaned_logical_ids: tuple[str, ...] = ()
    orphaned_physical_files: tuple[str, ...] = ()
    hash_mismatches: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (
            self.orphaned_logical_ids
            or self.orphaned_physical_files
            or self.hash_mismatches
        )


@dataclass(frozen=True)
class RestoreJob:
    """One restore, progressing through the stages.

    Immutable — `with_stage` returns a new value rather than mutating, so a job handed to a
    progress reporter cannot change underneath it.
    """

    job_id: str
    snapshot_id: str
    scope: RestoreScope
    stage: RestoreStage
    started_at: datetime
    user_id: str = ""
    blobs_restored: int = 0
    report: VerificationReport | None = None
    error_code: str = ""
    error_detail: str = ""

    def with_stage(self, stage: RestoreStage, **changes) -> RestoreJob:
        return RestoreJob(**{**self.__dict__, "stage": stage, **changes})


__all__ = ["RestoreJob", "RestoreScope", "RestoreStage", "VerificationReport"]
