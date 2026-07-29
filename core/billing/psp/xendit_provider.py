"""The Xendit payment provider — not the default, and fully real anyway (§3).

§3 resolves the either/or explicitly: both providers are "real, concrete implementations — not
a deferred either/or". Xendit "remains genuinely available behind the identical interface for an
owner who wants it (broader SEA reach, built-in recurring billing/disbursement), never requiring
a rewrite to switch." Implementing only the default would have made that claim false the moment
anyone tried to act on it, which is the entire failure mode a Provider Registry exists to
prevent (`docs/PRINCIPLES.md` §1.2).

Everything else matches `paymongo_provider.py` by design rather than by copy-paste laziness: the
credentials are per-instance (§3's hardcoding prohibition), the transport is injected (§1.3, and
so tests never reach a real payment API), and the webhook signature is compared in constant time
(§5). Two providers that verified signatures differently would be two chances to get the one
security-critical operation in this package wrong.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from ..contracts import PaymentEvent, PaymentStatus, utcnow
from ..errors import ProviderUnavailable
from .base import constant_time_signature_matches, hmac_sha256_hex

PROVIDER_NAME = "xendit"

#: Xendit's own status vocabulary. Deliberately its own table rather than shared with PayMongo's
#: — the two really do use different words (`settled` versus `paid`), and one merged table would
#: quietly accept a status from the wrong provider as valid.
STATUS_MAP = {
    "pending": PaymentStatus.PENDING,
    "processing": PaymentStatus.PENDING,
    "settled": PaymentStatus.SUCCEEDED,
    "paid": PaymentStatus.SUCCEEDED,
    "succeeded": PaymentStatus.SUCCEEDED,
    "failed": PaymentStatus.FAILED,
    "expired": PaymentStatus.FAILED,
    "voided": PaymentStatus.FAILED,
    "refunded": PaymentStatus.REFUNDED,
}


@runtime_checkable
class XenditTransport(Protocol):
    """One call out to Xendit, or raise."""

    def post(self, path: str, body: dict) -> dict: ...

    def get(self, path: str) -> dict: ...


class UnavailableXenditTransport:
    """The default: no network configured, so nothing is reachable. Never fabricates."""

    def post(self, path: str, body: dict) -> dict:
        raise ProviderUnavailable(f"no Xendit transport configured (POST {path})")

    def get(self, path: str) -> dict:
        raise ProviderUnavailable(f"no Xendit transport configured (GET {path})")


class XenditProvider:
    """Xendit, behind §3's shared `PaymentProvider` interface."""

    def __init__(
        self,
        *,
        secret_key: str = "",
        webhook_secret: str = "",
        transport: XenditTransport | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._transport: XenditTransport = transport or UnavailableXenditTransport()

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    async def create_charge(self, amount: int, currency: str, method: str) -> PaymentEvent:
        if amount <= 0:
            raise ProviderUnavailable("charge amount must be positive")
        payload = self._transport.post(
            "/charges", {"amount": amount, "currency": currency, "method": method}
        )
        return PaymentEvent(
            event_id=str(payload.get("event_id") or uuid.uuid4().hex),
            provider=PROVIDER_NAME,
            charge_id=str(payload.get("id", "")),
            amount_minor=int(payload.get("amount", amount)),
            currency=str(payload.get("currency", currency)),
            status=STATUS_MAP.get(str(payload.get("status", "")).lower(), PaymentStatus.UNKNOWN),
            method=method,
            occurred_at=utcnow(),
        )

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """§5's hard requirement, in constant time. No secret configured means no trust."""
        if not self._webhook_secret:
            return False
        expected = hmac_sha256_hex(self._webhook_secret, payload)
        return constant_time_signature_matches(expected, signature)

    async def check_status(self, charge_id: str) -> PaymentStatus:
        try:
            payload = self._transport.get(f"/charges/{charge_id}")
        except ProviderUnavailable:
            return PaymentStatus.UNKNOWN
        return STATUS_MAP.get(str(payload.get("status", "")).lower(), PaymentStatus.UNKNOWN)


__all__ = [
    "PROVIDER_NAME",
    "STATUS_MAP",
    "UnavailableXenditTransport",
    "XenditProvider",
    "XenditTransport",
]
