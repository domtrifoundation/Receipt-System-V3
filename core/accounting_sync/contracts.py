"""Accounting Sync API data contracts (`v3-deepdive-50-accounting-sync.md` §3).

This is the only module in this package other APIs import from. Same "errors are data,
not exceptions" convention as every other API built this session — a per-push failure
populates `.error` rather than raising across the API boundary.

**`SyncConnection` deliberately carries no token material** (deep-dive §5) — access/
refresh tokens live encrypted, associated with the user's own record, never in a plain
queryable table alongside business data, the same posture Auth's own OIDC tokens already
require. Anything returned over this API's own gRPC surface is built from this type, so
the credential-isolation guarantee (deep-dive §9's own named test) is structural: there is
no field here a servicer could accidentally serialize a token into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountingProvider(str, Enum):
    QUICKBOOKS = "quickbooks"
    XERO = "xero"


class SyncErrorCode(str, Enum):
    NOT_CONNECTED = "not_connected"
    AUTH_FAILED = "auth_failed"
    RECEIPT_FLAGGED = "receipt_flagged"  # a flagged receipt is never push-eligible, deep-dive §6
    PUSH_FAILED = "push_failed"
    RATE_LIMITED = "rate_limited"
    MAPPING_FAILED = "mapping_failed"


@dataclass(frozen=True)
class SyncError:
    code: SyncErrorCode
    detail: str = ""


@dataclass(frozen=True)
class AuthUrl:
    """What `authenticate()` hands back — the OAuth consent URL the caller redirects the
    user's browser to. Never populated alongside an error; a provider that can't even
    start the OAuth flow (missing app credentials) reports that as `SyncError` instead."""

    url: str
    state: str  # CSRF/replay-protection token, round-tripped through the OAuth callback
    error: SyncError | None = None


@dataclass(frozen=True)
class SyncConnection:
    user_id: str
    provider: AccountingProvider
    connected_at: datetime = field(default_factory=utcnow)
    #: The provider's own tenant/company identifier (QuickBooks' `realmId`, Xero's
    #: `tenantId`) — needed on every subsequent API call to that provider, itself not a
    #: secret, so it's fine to carry here unlike the actual OAuth tokens (deep-dive §5).
    external_account_id: str = ""


@dataclass(frozen=True)
class MappedRecord:
    """A receipt, already translated into the shape a provider's own expense/bill-create
    call expects (`mapping.py`) — this package's own internal input to `push_record()`,
    never a type either provider SDK sees directly."""

    receipt_id: str
    vendor_name: str
    transaction_date: datetime
    total_amount: str  # decimal-as-string — never a float, matching Persistence's own Receipt.total_amount discipline
    currency: str
    category: str | None = None
    notes: str = ""
    #: Provider-specific extra fields (line items, a receipt image attachment reference)
    #: that don't have a first-class column here — FrozenDict per `docs/PRINCIPLES.md` §2.1.
    extra: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class SyncedRecord:
    receipt_id: str
    provider: AccountingProvider
    #: The provider's own record identifier (QuickBooks' Purchase `Id`, Xero's
    #: BankTransaction `BankTransactionID`) — proof the push actually landed, not guessed.
    external_record_id: str
    synced_at: datetime = field(default_factory=utcnow)
    error: SyncError | None = None

    @classmethod
    def failure(cls, receipt_id: str, provider: AccountingProvider, error: SyncError) -> SyncedRecord:
        return cls(receipt_id=receipt_id, provider=provider, external_record_id="", error=error)


class FlagChecker(Protocol):
    """The Protocol seam this package uses to answer "is this receipt push-eligible"
    (deep-dive §6 — "a flagged receipt shouldn't push a possibly-wrong record into
    someone's books") — `core/review_flagging/` owns the actual flag lifecycle and has no
    gRPC surface of its own yet to call over the wire, so this stays a Protocol seam
    (`docs/PRINCIPLES.md` §1.3) rather than a direct `core.review_flagging` import, the
    same boundary discipline every sibling-API relationship in this project follows."""

    async def has_open_flag(self, receipt_id: str) -> bool:
        """`True` if `receipt_id` has any `Flag` whose `status` is not terminal
        (`FlagStatus.OPEN`/`ASSIGNED`, per `core/review_flagging/contracts.py`'s own
        lifecycle) — never guessed at, a real query against whatever store this
        package's own caller wires in."""
        ...


@dataclass(frozen=True)
class SyncMetrics:
    pushes_succeeded: int = 0
    pushes_failed: int = 0
    pushes_skipped_flagged: int = 0
    auth_completed: int = 0
    auth_failed: int = 0
    retries_attempted: int = 0


__all__ = [
    "AccountingProvider",
    "AuthUrl",
    "FlagChecker",
    "MappedRecord",
    "SyncConnection",
    "SyncError",
    "SyncErrorCode",
    "SyncMetrics",
    "SyncedRecord",
]
