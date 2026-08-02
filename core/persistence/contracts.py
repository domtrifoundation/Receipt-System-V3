"""Persistence API data contracts (`v3-deepdive-13-persistence-api.md` §3, §4).

This is the canonical definition of `BlobRef` — a type every prior deep-dive already used
as a first-class value without anywhere formally defining it. It is also the only module in
this package other packages import from (`docs/PRINCIPLES.md` §1.1).

Types only, no logic. Every contract is `@dataclass(frozen=True)` and every dict-typed field
is a `FrozenDict` (§2.1) — a frozen dataclass holding a plain `dict` is only *shallowly*
immutable, and these cross a process boundary.

**The single most important thing in this file**: `logical_id` and `physical_hash` are two
different values joined by a mapping table (`BlobLocation`), never one value doing both
jobs. `logical_id` is the SHA-256 of the *original uploaded bytes*, computed before any
re-encoding, and is what every reference anywhere in the system uses — SQLite rows,
Historian events, Audit events, exports. `physical_hash` is the SHA-256 of whatever is
*actually stored on disk right now*, and is what the sharded storage path is derived from.
Retention deletes the original upload, so a storage filename derived from the identity hash
would stop matching its own contents the moment that purge ran, permanently breaking
Disaster Recovery's own verification step (§3.3, and `v3-deepdive-33-disaster-recovery.md`
§4). Collapsing them back into one value is the exact bug that was caught before it shipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    """Timezone-aware UTC now. Every timestamp in this API is aware, never naive."""
    return datetime.now(timezone.utc)


class StorageCodec(str, Enum):
    """What a blob is *currently* stored as.

    A fact about physical storage, so it lives on `BlobLocation` and never on `BlobRef`.
    An earlier version of this contract had `stored_encoding` on `BlobRef` itself — a
    mutable fact living on a type whose whole purpose is being permanent (§3.3).
    """

    ORIGINAL = "original"
    WEBP = "webp"
    AVIF = "avif"


@dataclass(frozen=True)
class BlobRef:
    """A permanent, stable reference to an archived image. Never a file path.

    `logical_id` is *never* used to locate a file directly — it resolves through
    `BlobLocation` to a `physical_hash`, which is the real on-disk address
    (`blob_store.store.resolve_blob_path`).
    """

    logical_id: str


@dataclass(frozen=True)
class BlobLocation:
    """Where a `logical_id`'s bytes actually live right now, and in what form.

    `physical_hash` is always genuinely self-consistent: it is recomputed whenever the
    stored representation changes, so a stored file always matches its own filename. That
    self-consistency is what makes `verify_restore`'s corruption check mean anything.
    """

    logical_id: str
    physical_hash: str
    codec: StorageCodec
    byte_size: int
    updated_at: datetime


@dataclass(frozen=True)
class BackupConfirmation:
    """One backup target's own confirmation for one blob.

    Local write success and remote backup confirmation are tracked as separate states,
    never conflated into one "saved" flag (§4.4).
    """

    logical_id: str
    target_name: str
    confirmed_at: datetime


@dataclass(frozen=True)
class BlobWriteResult:
    """Errors are data at this boundary, never raised (`docs/PRINCIPLES.md` §4.1).

    `durably_backed_up` and `fully_synced` are deliberately two separate flags, resolving
    the parent deep-dive's own §12 open question: B2 and Storj are redundant, so one
    confirmation is already real durability and is what gates the write path; both
    confirming is a stronger "fully synced" status for operators who want that visibility,
    not a latency cost imposed on every write.
    """

    ok: bool
    blob_ref: BlobRef | None = None
    deduplicated: bool = False
    durably_backed_up: bool = False
    fully_synced: bool = False
    confirmed_targets: tuple[str, ...] = ()
    failed_targets: tuple[str, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class BlobReadResult:
    """Bytes plus the location they came from, or an error. Never a raise."""

    ok: bool
    blob_ref: BlobRef | None = None
    location: BlobLocation | None = None
    data: bytes = b""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ReferenceIdentifier:
    """A typed identifier read off a receipt — an OR number, an invoice number, a TIN.

    `kind` is a *reference* to a type Architect API has registered, never a taxonomy this
    API defines (`docs/PRINCIPLES.md` §3.4). Persistence stores the instance value against
    whatever kinds Architect knows about and validates nothing about the kind itself.
    """

    kind: str
    value: str
    normalized: str = ""


@dataclass(frozen=True)
class Receipt:
    """One canonical receipt record.

    `fields` carries the Architect-typed extracted values that are not first-class columns.
    `group_id` is stamped at write time from Groups' own `GetEffectiveGroup()`; *who may
    query across a group* is Groups' and Search/Query's concern, never gated here — this
    API stores the tag faithfully and nothing more (§1).
    """

    receipt_id: str
    user_id: str
    blob: BlobRef
    created_at: datetime
    updated_at: datetime
    group_id: str | None = None
    vendor_id: str | None = None
    vendor_name: str = ""
    transaction_date: datetime | None = None
    currency: str = "PHP"
    total_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    identifiers: tuple[ReferenceIdentifier, ...] = ()
    fields: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    schema_version: int = 1


@dataclass(frozen=True)
class WriteResult:
    """The result of a canonical write and its paired Historian event.

    `historian_event_id` being populated is the caller-visible evidence that §5's
    same-transaction guarantee actually held: the data row and its event committed together
    or neither did.
    """

    ok: bool
    receipt_id: str = ""
    historian_event_id: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ReceiptReadResult:
    ok: bool
    receipt: Receipt | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ExportSnapshotRef:
    """The baseline a reimported file diffs against (`v3-deepdive-30-reimport.md` §3).

    Written into the generated workbook as a hidden reference cell at export time and read
    back by Reimport's parser. Without it there is no way to tell "the user changed this
    field" apart from "this field happens to differ from current canonical state."
    """

    export_id: str
    user_id: str
    historian_event_id: str
    generated_at: datetime


__all__ = [
    "BackupConfirmation",
    "BlobLocation",
    "BlobReadResult",
    "BlobRef",
    "BlobWriteResult",
    "ExportSnapshotRef",
    "Receipt",
    "ReceiptReadResult",
    "ReferenceIdentifier",
    "StorageCodec",
    "WriteResult",
    "utcnow",
]
