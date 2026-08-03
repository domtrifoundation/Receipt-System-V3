"""Accounting Sync API's error taxonomy.

`SyncError` (`contracts.py`) is the wire-facing shape — never raised across this API's
own gRPC boundary (`docs/PRINCIPLES.md` §4.1). The exception classes below exist for the
*internal* call path only: each provider adapter raises one of these, and `sync_engine.py`
is the one place they get caught and converted into a `SyncedRecord`/`AuthUrl` carrying a
`SyncError` (mirroring every other API's single-conversion-point convention this session
— `core/ocr/engine_registry.py`, `core/inference/model_registry.py`).

`ReceiptFlagged` is its own subtype rather than a flavor of `PushFailed` — deep-dive §6's
own exclusion rule ("a flagged receipt shouldn't push a possibly-wrong record") is a
policy decision this package enforces itself, structurally distinct from the external
provider actually rejecting a push.
"""

from __future__ import annotations

__all__ = [
    "AccountingSyncInternalError",
    "AuthenticationFailed",
    "MappingFailed",
    "NotConnected",
    "PushFailed",
    "ReceiptFlagged",
    "SyncRateLimited",
]


class AccountingSyncInternalError(Exception):
    """Base for everything this package raises internally, never across its own boundary."""


class NotConnected(AccountingSyncInternalError):
    """The user has no active `SyncConnection` for the requested provider — a real,
    ordinary state (most users won't have connected either platform), not a crash."""


class AuthenticationFailed(AccountingSyncInternalError):
    """The OAuth flow itself failed — a bad/expired authorization code, a state
    mismatch, the provider's own token endpoint rejecting the exchange."""


class ReceiptFlagged(AccountingSyncInternalError):
    """The receipt has an open `Flag` (deep-dive §6) — never push a possibly-wrong
    record into someone's books. Discovered before any provider API call is made."""


class PushFailed(AccountingSyncInternalError):
    """The provider's own API rejected or failed the push — a validation error, an
    expired token, a transient outage. Retried with backoff by `sync_engine.py`'s own
    caller (a Background Workers job, deep-dive §6), never retried silently in place."""


class SyncRateLimited(AccountingSyncInternalError):
    """The provider's own rate limit rejected the call — distinct from a generic
    `PushFailed` since the correct backoff behavior differs (wait for the provider's own
    stated reset window, not a generic exponential backoff)."""


class MappingFailed(AccountingSyncInternalError):
    """`mapping.py` could not translate a `Receipt` into a `MappedRecord` — missing
    required fields (no vendor name, no total amount), not a provider-side failure at all."""
