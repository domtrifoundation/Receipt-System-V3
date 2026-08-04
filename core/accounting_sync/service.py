"""The `AccountingSyncServicer` gRPC servicer (`accounting_sync.proto`) — the real
assembly point: it is the one place a `SyncEngine` gets constructed with real provider
adapters, a real `TokenStore`, and (see the gotcha below) the best `FlagChecker` currently
wireable.

The generated stubs are imported lazily, same convention as every other API's
`service.py` this session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import AccountingProvider, FlagChecker
from .errors import AuthenticationFailed, NotConnected
from .persistence_client import PersistenceClient, ReceiptNotFound
from .providers.quickbooks import QuickBooksConfig, QuickBooksProvider
from .providers.xero import XeroConfig, XeroProvider
from .sync_engine import SyncEngine
from .token_store import TokenStore

DEFAULT_ADDRESS = "127.0.0.1:50080"


class NoOpFlagChecker:
    """**Unsafe-by-default stand-in, not a real check** — `core/review_flagging/` owns
    the actual flag lifecycle (`contracts.py`, `db.py`, `gateways.py`, `lifecycle.py` are
    all real) but has no gRPC proto/`service.py`/generated stubs of its own at all yet
    (confirmed by directory listing — no `.proto`, no `generated/`). This project's own
    process-topology rule (`docs/PROCESS_TOPOLOGY.md`) means Accounting Sync cannot reach
    into that package's internals directly even though they happen to sit in the same
    repo — every Core API talks to every other one over gRPC only, never a same-process
    import of another API's internals.

    Until Review/Flagging ships a real gRPC surface, this always reports "no open flag" —
    genuinely never excludes anything, the opposite of deep-dive §6/§9's intent. Any real
    deployment MUST inject a real `FlagChecker` once one exists;
    `AccountingSyncServicer.__init__`'s own `flag_checker` parameter exists specifically
    so that wiring is a one-line change here, not a rewrite."""

    async def has_open_flag(self, receipt_id: str) -> bool:
        return False


@dataclass(frozen=True)
class AccountingSyncConfig:
    quickbooks: QuickBooksConfig = field(default_factory=QuickBooksConfig)
    xero: XeroConfig = field(default_factory=XeroConfig)
    #: Fernet key (`cryptography.fernet.Fernet.generate_key()`) — a real deployment's own
    #: secrets-management source supplies this, never a hardcoded default (`token_store.py`).
    token_encryption_key: bytes = b""
    persistence_address: str = "127.0.0.1:50072"


def build_sync_engine(config: AccountingSyncConfig, *, flag_checker: FlagChecker | None = None) -> SyncEngine:
    """The real assembly point (this session's own repeated lesson: a module built and
    tested in isolation is still a gap until something in the real service construction
    calls it) — both providers and the token store are constructed here, once, and shared."""
    token_store = TokenStore(config.token_encryption_key or _dev_only_key())
    providers = {
        AccountingProvider.QUICKBOOKS: QuickBooksProvider(config.quickbooks, token_store),
        AccountingProvider.XERO: XeroProvider(config.xero, token_store),
    }
    return SyncEngine(providers, flag_checker or NoOpFlagChecker())


def _dev_only_key() -> bytes:
    """A real deployment must always supply `token_encryption_key` — this generates a
    fresh, unrecoverable key purely so an unconfigured dev/test instance doesn't crash
    on construction; tokens encrypted under it are unrecoverable across a process
    restart, which is a feature here (never persisted), not a workaround."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key()


class AccountingSyncServicer:
    """Implements `AccountingSyncService`. Registered by name, so importing the generated
    stubs is `serve()`'s business and this class stays importable without them."""

    def __init__(
        self,
        config: AccountingSyncConfig | None = None,
        *,
        engine: SyncEngine | None = None,
        flag_checker: FlagChecker | None = None,
        persistence_client: PersistenceClient | None = None,
    ) -> None:
        config = config or AccountingSyncConfig()
        self._engine = engine or build_sync_engine(config, flag_checker=flag_checker)
        self._persistence = persistence_client or PersistenceClient(config.persistence_address)

    async def InitiateAuth(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import accounting_sync_pb2 as pb

        result = await self._engine.initiate_auth(request.user_id, AccountingProvider(request.provider))
        response = pb.InitiateAuthResponse(url=result.url, state=result.state)
        if result.error is not None:
            response.error_code = result.error.code.value
            response.error_detail = result.error.detail
        return response

    async def CompleteAuth(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import accounting_sync_pb2 as pb

        response = pb.CompleteAuthResponse()
        try:
            connection = await self._engine.complete_auth(
                request.user_id, AccountingProvider(request.provider), dict(request.callback_params),
            )
            response.external_account_id = connection.external_account_id
        except AuthenticationFailed as exc:
            response.error_code = "auth_failed"
            response.error_detail = str(exc)
        except NotConnected as exc:
            response.error_code = "not_connected"
            response.error_detail = str(exc)
        return response

    async def GetSyncStatus(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import accounting_sync_pb2 as pb

        connected = await self._engine.is_connected(request.user_id, AccountingProvider(request.provider))
        return pb.SyncStatusResponse(connected=connected)

    async def Disconnect(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import accounting_sync_pb2 as pb

        await self._engine.disconnect(request.user_id, AccountingProvider(request.provider))
        return pb.DisconnectResponse()

    async def PushReceipt(self, request, context=None):  # noqa: N802 - gRPC naming
        from .generated import accounting_sync_pb2 as pb

        response = pb.PushReceiptResponse()
        try:
            receipt = await self._persistence.get_receipt(request.user_id, request.receipt_id)
        except ReceiptNotFound as exc:
            response.error_code = "not_connected"
            response.error_detail = str(exc)
            return response

        result = await self._engine.push_receipt(
            request.user_id, AccountingProvider(request.provider), receipt,
            vendor_display_name=request.vendor_display_name or None,
        )
        response.external_record_id = result.external_record_id
        if result.error is not None:
            response.error_code = result.error.code.value
            response.error_detail = result.error.detail
        return response


async def serve(address: str = DEFAULT_ADDRESS, *, config: AccountingSyncConfig | None = None):
    """Start the servicer on `address`. Imports gRPC lazily — see the module docstring."""
    import grpc

    from .generated import accounting_sync_pb2_grpc

    server = grpc.aio.server()
    accounting_sync_pb2_grpc.add_AccountingSyncServiceServicer_to_server(
        AccountingSyncServicer(config), server
    )
    port = server.add_insecure_port(address)
    host = address.rsplit(":", 1)[0]
    server.bound_address = f"{host}:{port}"  # type: ignore[attr-defined]
    await server.start()
    return server


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def _main() -> None:
        addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
        srv = await serve(addr)
        print(f"BOUND_ADDRESS={srv.bound_address}", flush=True)
        print(f"listening on {srv.bound_address}", file=sys.stderr)
        from common.watchdog_client import start_kicking_for_service, stop_kick_loop
        kick_task = start_kicking_for_service('accounting_sync')
        try:
            await srv.wait_for_termination()
        finally:
            await stop_kick_loop(kick_task)

    asyncio.run(_main())
