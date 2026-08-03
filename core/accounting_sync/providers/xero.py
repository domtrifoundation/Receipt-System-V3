"""Xero provider (deep-dive §3, §10 — "official SDKs where they exist and are actively
maintained"). Built against `xero-python` (`pip install xero-python`), Xero's own official
Python SDK.

**Not live-tested this session** — `xero-python` is not installed in this environment
(confirmed: `import xero_python` raises `ModuleNotFoundError` here), and there are no real
Xero app credentials to authenticate against even if it were. Built directly from the
SDK's own published API shape, same honesty posture as `quickbooks.py`'s own module
docstring.

A Xero `BankTransaction` (type `SPEND`) is the real record shape for "money already
spent" — Xero's own accounting model distinguishes this from an `Invoice`/`Bill`, which
represents an unpaid liability still owed, the same distinction `quickbooks.py`'s own
choice of `Purchase` over `Bill` makes for QuickBooks.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AccountingProvider, AuthUrl, MappedRecord, SyncConnection, SyncedRecord, SyncError, SyncErrorCode
from ..errors import AuthenticationFailed, PushFailed, SyncRateLimited
from ..token_store import TokenStore

__all__ = ["XeroConfig", "XeroProvider"]

_SCOPES = "accounting.transactions offline_access"


@dataclass(frozen=True)
class XeroConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""


class XeroProvider:
    def __init__(self, config: XeroConfig, token_store: TokenStore) -> None:
        self._config = config
        self._token_store = token_store

    @property
    def provider(self) -> AccountingProvider:
        return AccountingProvider.XERO

    async def is_available(self) -> bool:
        if not (self._config.client_id and self._config.client_secret and self._config.redirect_uri):
            return False
        try:
            import xero_python  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def authenticate(self, user_id: str) -> AuthUrl:
        if not await self.is_available():
            return AuthUrl(
                url="", state="",
                error=SyncError(SyncErrorCode.AUTH_FAILED, "Xero is not configured/installed"),
            )
        try:
            import secrets
            from urllib.parse import urlencode

            state = secrets.token_urlsafe(32)
            # Xero's own OAuth2 authorization endpoint — a plain, well-documented
            # authorization-code-grant URL; `xero_python`'s own `OAuth2Api` wraps the
            # token exchange but the authorize redirect itself is a standard URL build,
            # no SDK object needed to construct it.
            params = {
                "response_type": "code",
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "scope": _SCOPES,
                "state": state,
            }
            url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
            return AuthUrl(url=url, state=state)
        except Exception as exc:  # noqa: BLE001 - any failure here means auth can't start
            raise AuthenticationFailed(f"{type(exc).__name__}: {exc}") from exc

    async def complete_auth(self, user_id: str, callback_params: dict) -> SyncConnection:
        code = callback_params.get("code", "")
        if not code:
            raise AuthenticationFailed("Xero callback carried no code")

        try:
            from xero_python.api_client import ApiClient  # noqa: PLC0415
            from xero_python.api_client.configuration import Configuration  # noqa: PLC0415
            from xero_python.api_client.oauth2 import OAuth2Token  # noqa: PLC0415
            from xero_python.identity import IdentityApi  # noqa: PLC0415

            oauth2_token = OAuth2Token(
                client_id=self._config.client_id, client_secret=self._config.client_secret,
            )
            api_client = ApiClient(Configuration(oauth2_token=oauth2_token))
            token = oauth2_token.get_token_from_code(code, self._config.redirect_uri)  # unverified exact method name — see module docstring

            identity_api = IdentityApi(api_client)
            connections = identity_api.get_connections()
            tenant_id = connections[0].tenant_id if connections else ""
        except Exception as exc:  # noqa: BLE001 - a failed token exchange is an auth failure
            raise AuthenticationFailed(f"{type(exc).__name__}: {exc}") from exc

        await self._token_store.store_tokens(
            user_id, self.provider.value,
            {
                "access_token": token.get("access_token", ""),
                "refresh_token": token.get("refresh_token", ""),
                "tenant_id": tenant_id,
            },
        )
        return SyncConnection(user_id=user_id, provider=self.provider, external_account_id=tenant_id)

    async def push_record(self, connection: SyncConnection, record: MappedRecord) -> SyncedRecord:
        tokens = await self._token_store.load_tokens(connection.user_id, self.provider.value)
        if tokens is None:
            return SyncedRecord.failure(
                record.receipt_id, self.provider,
                SyncError(SyncErrorCode.NOT_CONNECTED, "no stored Xero connection for this user"),
            )

        try:
            from xero_python.accounting import AccountingApi, BankTransaction, LineItem  # noqa: PLC0415
            from xero_python.api_client import ApiClient  # noqa: PLC0415
            from xero_python.api_client.configuration import Configuration  # noqa: PLC0415
            from xero_python.api_client.oauth2 import OAuth2Token  # noqa: PLC0415

            oauth2_token = OAuth2Token(
                client_id=self._config.client_id, client_secret=self._config.client_secret,
            )
            oauth2_token.set_token(
                {"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"]}
            )
            api_client = ApiClient(Configuration(oauth2_token=oauth2_token))
            accounting_api = AccountingApi(api_client)

            transaction = BankTransaction(
                type="SPEND",
                line_items=[LineItem(description=record.vendor_name, line_amount=float(record.total_amount))],
            )
            response = accounting_api.create_bank_transactions(
                tokens["tenant_id"], bank_transactions=[transaction],
            )
            created = response.bank_transactions[0]
        except Exception as exc:  # noqa: BLE001 - classify below; any other failure is a push failure
            if _looks_like_rate_limit(exc):
                raise SyncRateLimited(str(exc)) from exc
            raise PushFailed(f"{type(exc).__name__}: {exc}") from exc

        return SyncedRecord(
            receipt_id=record.receipt_id, provider=self.provider,
            external_record_id=str(getattr(created, "bank_transaction_id", "")),
        )

    async def is_connected(self, user_id: str) -> bool:
        return await self._token_store.load_tokens(user_id, self.provider.value) is not None

    async def disconnect(self, user_id: str) -> None:
        await self._token_store.delete_tokens(user_id, self.provider.value)


def _looks_like_rate_limit(exc: Exception) -> bool:
    detail = str(exc).lower()
    return "429" in detail or "rate limit" in detail or "throttl" in detail
