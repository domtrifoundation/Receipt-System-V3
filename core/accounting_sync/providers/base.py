"""`AccountingSyncProvider` — the Provider Registry every accounting-software adapter
implements (deep-dive §3). **Genuinely per-user, not system-wide** — unlike most Provider
Registry entries in this project (OCR engines, backup targets), which the *owner* enables
system-wide, each individual user connects (or doesn't) their own QuickBooks/Xero account
independently. A group context doesn't share one connection across members (deep-dive
§3's own note, consistent with Groups' own design never creating a shared data store).

Every provider adapter's own SDK import lives inside the methods that need it, never at
module level (`docs/PRINCIPLES.md` §3.3 point 5) — an install without a given provider's
SDK degrades that one provider to unavailable rather than failing this module's own import.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts import AccountingProvider, AuthUrl, MappedRecord, SyncConnection, SyncedRecord

__all__ = ["AccountingSyncProvider"]


@runtime_checkable
class AccountingSyncProvider(Protocol):
    @property
    def provider(self) -> AccountingProvider: ...

    async def is_available(self) -> bool:
        """Whether this provider's own SDK/app credentials are configured at all — a
        missing SDK install or unconfigured OAuth app client id/secret, not "is a given
        user connected" (that's `is_connected()`, a per-user question)."""
        ...

    async def authenticate(self, user_id: str) -> AuthUrl:
        """Returns the OAuth consent URL to redirect the user's browser to. Raises
        `errors.AuthenticationFailed` if the flow can't even start."""
        ...

    async def complete_auth(self, user_id: str, callback_params: dict) -> SyncConnection:
        """Exchanges the OAuth callback's own code/state for tokens, storing them
        encrypted (deep-dive §5) — never returned as part of the resulting
        `SyncConnection`. Raises `errors.AuthenticationFailed` on a failed exchange."""
        ...

    async def push_record(self, connection: SyncConnection, record: MappedRecord) -> SyncedRecord:
        """One-way push only (deep-dive §4) — creates a new expense/bill record in the
        provider's own books. Raises `errors.PushFailed`/`errors.SyncRateLimited` on
        failure; never reads anything back from the provider beyond confirming the
        created record's own id."""
        ...

    async def is_connected(self, user_id: str) -> bool: ...

    async def disconnect(self, user_id: str) -> None:
        """Revokes/discards the stored connection — best-effort against the provider's
        own token-revocation endpoint, always removes the local encrypted record
        regardless of whether that revocation call itself succeeds."""
        ...
