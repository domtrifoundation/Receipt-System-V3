"""Archive Sync contracts (`v3-deepdive-32-archive-sync.md` §2).

Types only. Archive Sync mirrors processed receipts *out* to an external drive provider,
one-way. The external copy is never a second source of truth: if it goes missing, is deleted
externally, or drifts, Persistence's own blob store remains authoritative, full stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.frozen_dict import FrozenDict


class SyncState(str, Enum):
    """`PAUSED` is a real, first-class state, not an error condition.

    A missing or inaccessible external target pauses sync and notifies the user; it never
    silently retries forever (which masks a real problem from the person who needs to know)
    and never auto-recreates the folder (which risks doing something they deliberately
    undid). See §8's resolution.
    """

    DISABLED = "disabled"
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass(frozen=True)
class SyncTarget:
    """One configured external destination."""

    provider_name: str
    target_path: str
    user_id: str
    enabled: bool = True
    options: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class SyncResult:
    """One blob's mirror attempt."""

    ok: bool
    external_name: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class SyncCursor:
    """Where a user's mirror got to.

    A cursor rather than a full re-scan every run, and it advances **only after a confirmed
    successful upload** — that ordering is what makes an interrupted job resume correctly
    instead of either re-uploading everything or silently skipping unmirrored items.
    """

    user_id: str
    target_name: str
    last_receipt_id: str = ""
    last_synced_at: datetime | None = None
    paused_reason: str = ""

    @property
    def state(self) -> SyncState:
        if self.paused_reason:
            return SyncState.PAUSED
        return SyncState.ACTIVE


@dataclass(frozen=True)
class SyncJob:
    """The outcome of one mirror pass. Errors are data (`docs/PRINCIPLES.md` §4.1)."""

    ok: bool
    user_id: str = ""
    mirrored: int = 0
    skipped: int = 0
    cursor: SyncCursor | None = None
    state: SyncState = SyncState.ACTIVE
    error_code: str = ""
    error_detail: str = ""


__all__ = ["SyncCursor", "SyncJob", "SyncResult", "SyncState", "SyncTarget"]
