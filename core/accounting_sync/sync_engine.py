"""The real assembly point tying providers, the flag-exclusion check, and metrics
together (deep-dive §6) — this session's own repeated lesson (Ingestion's
`GoogleDriveSource`/`webhook_manager`, Preprocessing's `PreprocessingMetricsCollector`) is
that a module built and unit-tested in isolation is still a real gap until something in
the actual service construction calls it. `service.py`'s servicer constructs exactly one
`SyncEngine`, wiring in every configured provider, the real `FlagChecker`, and the shared
metrics collector — nothing downstream of this module reaches a provider adapter directly.

**Flagged-receipt exclusion (deep-dive §6, §9's own named test) happens here, before any
provider call** — `push_receipt()` checks `flag_checker.has_open_flag()` first and returns
a `SyncedRecord.failure(..., RECEIPT_FLAGGED)` without ever touching the provider's own
SDK, so a flagged receipt structurally cannot reach QuickBooks/Xero through this path.

**One-way push only** (deep-dive §4) — nothing in this module ever reads a record back
from a provider beyond confirming the id of what it just created; there is no pull/import
path anywhere in this package.
"""

from __future__ import annotations

from .contracts import (
    AccountingProvider,
    AuthUrl,
    FlagChecker,
    MappedRecord,
    SyncConnection,
    SyncError,
    SyncErrorCode,
    SyncedRecord,
)
from .errors import (
    AuthenticationFailed,
    MappingFailed,
    NotConnected,
    PushFailed,
    SyncRateLimited,
)
from .mapping import map_receipt_to_record
from .metrics import SyncMetricsCollector
from .providers.base import AccountingSyncProvider

__all__ = ["SyncEngine"]


class SyncEngine:
    def __init__(
        self,
        providers: dict[AccountingProvider, AccountingSyncProvider],
        flag_checker: FlagChecker,
        metrics: SyncMetricsCollector | None = None,
    ) -> None:
        self._providers = providers
        self._flag_checker = flag_checker
        self.metrics = metrics or SyncMetricsCollector()

    def _provider_for(self, provider: AccountingProvider) -> AccountingSyncProvider | None:
        return self._providers.get(provider)

    async def initiate_auth(self, user_id: str, provider: AccountingProvider) -> AuthUrl:
        adapter = self._provider_for(provider)
        if adapter is None:
            self.metrics.increment("auth_failed")
            return AuthUrl(url="", state="", error=SyncError(SyncErrorCode.AUTH_FAILED, f"no adapter configured for {provider.value}"))
        try:
            result = await adapter.authenticate(user_id)
        except AuthenticationFailed as exc:
            self.metrics.increment("auth_failed")
            return AuthUrl(url="", state="", error=SyncError(SyncErrorCode.AUTH_FAILED, str(exc)))
        if result.error is not None:
            self.metrics.increment("auth_failed")
        return result

    async def complete_auth(self, user_id: str, provider: AccountingProvider, callback_params: dict) -> SyncConnection:
        """Raises `errors.AuthenticationFailed`/`errors.NotConnected` on failure — unlike
        `push_record`/`initiate_auth`, this one isn't in `errors.py`'s own enumerated
        "converted to data here" list (only `SyncedRecord`/`AuthUrl` are), so `service.py`
        is where this becomes a gRPC-facing error instead."""
        adapter = self._provider_for(provider)
        if adapter is None:
            raise NotConnected(f"no adapter configured for {provider.value}")
        connection = await adapter.complete_auth(user_id, callback_params)
        self.metrics.increment("auth_completed")
        return connection

    async def is_connected(self, user_id: str, provider: AccountingProvider) -> bool:
        adapter = self._provider_for(provider)
        if adapter is None:
            return False
        return await adapter.is_connected(user_id)

    async def disconnect(self, user_id: str, provider: AccountingProvider) -> None:
        adapter = self._provider_for(provider)
        if adapter is None:
            return
        await adapter.disconnect(user_id)

    async def push_receipt(
        self,
        user_id: str,
        provider: AccountingProvider,
        receipt,
        vendor_display_name: str | None = None,
    ) -> SyncedRecord:
        """Maps `receipt` (`core.persistence.contracts.Receipt`, duck-typed per
        `mapping.py`'s own boundary choice) and pushes it, after the flag-exclusion check.
        The single real entry point `service.py`'s `RequestSync`-equivalent RPC calls."""
        receipt_id = getattr(receipt, "receipt_id", "")

        if await self._flag_checker.has_open_flag(receipt_id):
            self.metrics.increment("pushes_skipped_flagged")
            return SyncedRecord.failure(
                receipt_id, provider,
                SyncError(SyncErrorCode.RECEIPT_FLAGGED, "receipt has an open review flag"),
            )

        try:
            record = map_receipt_to_record(receipt, vendor_display_name)
        except MappingFailed as exc:
            self.metrics.increment("pushes_failed")
            return SyncedRecord.failure(receipt_id, provider, SyncError(SyncErrorCode.MAPPING_FAILED, str(exc)))

        return await self.push_record(user_id, provider, record)

    async def push_record(self, user_id: str, provider: AccountingProvider, record: MappedRecord) -> SyncedRecord:
        adapter = self._provider_for(provider)
        if adapter is None:
            self.metrics.increment("pushes_failed")
            return SyncedRecord.failure(
                record.receipt_id, provider,
                SyncError(SyncErrorCode.NOT_CONNECTED, f"no adapter configured for {provider.value}"),
            )

        connection = SyncConnection(user_id=user_id, provider=provider)
        try:
            result = await adapter.push_record(connection, record)
        except SyncRateLimited as exc:
            self.metrics.increment("retries_attempted")
            self.metrics.increment("pushes_failed")
            return SyncedRecord.failure(record.receipt_id, provider, SyncError(SyncErrorCode.RATE_LIMITED, str(exc)))
        except PushFailed as exc:
            self.metrics.increment("pushes_failed")
            return SyncedRecord.failure(record.receipt_id, provider, SyncError(SyncErrorCode.PUSH_FAILED, str(exc)))

        if result.error is not None:
            self.metrics.increment("pushes_failed")
        else:
            self.metrics.increment("pushes_succeeded")
        return result
