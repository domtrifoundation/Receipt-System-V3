"""QuickBooks Online provider (deep-dive §3, §10 — "official SDKs where they exist and
are actively maintained"). Built against `intuitlib` (Intuit's own OAuth2 client,
`pip install intuit-oauth`) for the authorization flow and `python-quickbooks`
(`pip install python-quickbooks`) for the Purchase-record push, both the actively
maintained official/community-standard choices per the deep-dive's own resolved decision.

**Not live-tested this session** — neither SDK is installed in this environment
(confirmed: `import intuitlib`/`import quickbooks` both raise `ModuleNotFoundError`
here), and there are no real QuickBooks app credentials to authenticate against even if
they were. Built directly from each library's own published API shape, the same honesty
posture `core/inference/backends/onnx_genai_backend.py`'s own module docstring takes for
its own unverified library calls — say plainly what was and wasn't run for real.

A `Purchase` object (not `Bill`) is the real QuickBooks Online record shape for "money
already spent," per QuickBooks' own accounting model — a `Bill` represents an *unpaid*
liability still owed to a vendor, which is the wrong shape for a receipt that documents
money already spent at the point of purchase.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AccountingProvider, AuthUrl, MappedRecord, SyncConnection, SyncedRecord, SyncError, SyncErrorCode
from ..errors import AuthenticationFailed, PushFailed, SyncRateLimited
from ..token_store import TokenStore

__all__ = ["QuickBooksConfig", "QuickBooksProvider"]

_SCOPES = ["com.intuit.quickbooks.accounting"]
_DISCOVERY_DOCUMENT_URL = "https://appcenter.intuit.com/connect/oauth2"


@dataclass(frozen=True)
class QuickBooksConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    #: `"sandbox"` or `"production"` — QuickBooks' own environment split, threaded
    #: through both the OAuth client and the `python-quickbooks` client construction.
    environment: str = "sandbox"


class QuickBooksProvider:
    def __init__(self, config: QuickBooksConfig, token_store: TokenStore) -> None:
        self._config = config
        self._token_store = token_store

    @property
    def provider(self) -> AccountingProvider:
        return AccountingProvider.QUICKBOOKS

    async def is_available(self) -> bool:
        if not (self._config.client_id and self._config.client_secret and self._config.redirect_uri):
            return False
        try:
            import intuitlib  # noqa: F401, PLC0415
            import quickbooks  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    async def authenticate(self, user_id: str) -> AuthUrl:
        if not await self.is_available():
            return AuthUrl(
                url="", state="",
                error=SyncError(SyncErrorCode.AUTH_FAILED, "QuickBooks is not configured/installed"),
            )
        try:
            import secrets

            from intuitlib.client import AuthClient  # noqa: PLC0415
            from intuitlib.enums import Scopes  # noqa: PLC0415

            state = secrets.token_urlsafe(32)
            auth_client = AuthClient(
                self._config.client_id, self._config.client_secret,
                self._config.redirect_uri, self._config.environment,
            )
            url = auth_client.get_authorization_url([Scopes.ACCOUNTING], state_token=state)
            return AuthUrl(url=url, state=state)
        except Exception as exc:  # noqa: BLE001 - any SDK/config failure means auth can't start
            raise AuthenticationFailed(f"{type(exc).__name__}: {exc}") from exc

    async def complete_auth(self, user_id: str, callback_params: dict) -> SyncConnection:
        code = callback_params.get("code", "")
        realm_id = callback_params.get("realmId", "")
        if not code or not realm_id:
            raise AuthenticationFailed("QuickBooks callback carried no code/realmId")

        try:
            from intuitlib.client import AuthClient  # noqa: PLC0415

            auth_client = AuthClient(
                self._config.client_id, self._config.client_secret,
                self._config.redirect_uri, self._config.environment,
            )
            auth_client.get_bearer_token(code, realm_id=realm_id)
        except Exception as exc:  # noqa: BLE001 - a failed token exchange is an auth failure
            raise AuthenticationFailed(f"{type(exc).__name__}: {exc}") from exc

        await self._token_store.store_tokens(
            user_id, self.provider.value,
            {
                "access_token": auth_client.access_token,
                "refresh_token": auth_client.refresh_token,
                "realm_id": realm_id,
            },
        )
        return SyncConnection(user_id=user_id, provider=self.provider, external_account_id=realm_id)

    async def push_record(self, connection: SyncConnection, record: MappedRecord) -> SyncedRecord:
        tokens = await self._token_store.load_tokens(connection.user_id, self.provider.value)
        if tokens is None:
            return SyncedRecord.failure(
                record.receipt_id, self.provider,
                SyncError(SyncErrorCode.NOT_CONNECTED, "no stored QuickBooks connection for this user"),
            )

        try:
            from intuitlib.client import AuthClient  # noqa: PLC0415
            from quickbooks import QuickBooks  # noqa: PLC0415
            from quickbooks.objects.purchase import Purchase  # noqa: PLC0415

            auth_client = AuthClient(
                self._config.client_id, self._config.client_secret,
                self._config.redirect_uri, self._config.environment,
                access_token=tokens["access_token"], refresh_token=tokens["refresh_token"],
            )
            client = QuickBooks(
                auth_client=auth_client, refresh_token=tokens["refresh_token"],
                company_id=tokens["realm_id"],
            )

            purchase = Purchase()
            purchase.TotalAmt = record.total_amount
            purchase.PaymentType = "Cash"
            purchase.PrivateNote = record.notes
            saved = purchase.save(qb=client)
        except Exception as exc:  # noqa: BLE001 - classify below; any other failure is a push failure
            if _looks_like_rate_limit(exc):
                raise SyncRateLimited(str(exc)) from exc
            raise PushFailed(f"{type(exc).__name__}: {exc}") from exc

        return SyncedRecord(
            receipt_id=record.receipt_id, provider=self.provider,
            external_record_id=str(getattr(saved, "Id", "")),
        )

    async def is_connected(self, user_id: str) -> bool:
        return await self._token_store.load_tokens(user_id, self.provider.value) is not None

    async def disconnect(self, user_id: str) -> None:
        await self._token_store.delete_tokens(user_id, self.provider.value)


def _looks_like_rate_limit(exc: Exception) -> bool:
    detail = str(exc).lower()
    return "429" in detail or "rate limit" in detail or "throttl" in detail
