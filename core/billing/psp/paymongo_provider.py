"""The PayMongo payment provider — §3's resolved default.

§3 picks it for transparent public pricing, PH-first simplicity and the faster solo-dev
integration, the same reasoning file 03 already laid out. Xendit sits behind the identical
interface for anyone who wants it, "never requiring a rewrite to switch".

Credentials are constructor arguments, never module globals. §3's requirement is that they be
"per-install config, never hardcoded to one merchant account (or self-hosted buyers would route
payments through the reference deployment's own account)" — a real architectural constraint that
a module-level secret would violate silently.

**No card data passes through here** (§1). PayMongo is a tokenizing aggregator, which is what
keeps this API out of PCI scope entirely; a method here that accepted a card number would be a
scope change rather than a feature.

The HTTP call sits behind an injected transport for the reason every external service in this
repo does (`docs/PRINCIPLES.md` §1.3) — and so no unit test in this package ever reaches a real
payment API, which for a billing system is a requirement rather than a convenience.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from ..contracts import PaymentEvent, PaymentStatus, utcnow
from ..errors import ProviderUnavailable
from .base import constant_time_signature_matches, hmac_sha256_hex

PROVIDER_NAME = "paymongo"

#: How PayMongo reports a charge's state, mapped onto this API's vocabulary. Read through
#: `.get` so an unrecognised status resolves to `UNKNOWN` rather than being guessed at —
#: guessing costs real money in one direction or the other.
STATUS_MAP = {
    "pending": PaymentStatus.PENDING,
    "processing": PaymentStatus.PENDING,
    "awaiting_payment_method": PaymentStatus.PENDING,
    "paid": PaymentStatus.SUCCEEDED,
    "succeeded": PaymentStatus.SUCCEEDED,
    "failed": PaymentStatus.FAILED,
    "expired": PaymentStatus.FAILED,
    "refunded": PaymentStatus.REFUNDED,
}


@runtime_checkable
class PayMongoTransport(Protocol):
    """One call out to PayMongo, or raise. Narrow on purpose."""

    def post(self, path: str, body: dict) -> dict: ...

    def get(self, path: str) -> dict: ...


class UnavailablePayMongoTransport:
    """The default: no network configured, so nothing is reachable.

    Never fabricates a response. A stub returning a successful charge would grant a paid tier
    nobody paid for — the worst failure mode available to this file.
    """

    def post(self, path: str, body: dict) -> dict:
        raise ProviderUnavailable(f"no PayMongo transport configured (POST {path})")

    def get(self, path: str) -> dict:
        raise ProviderUnavailable(f"no PayMongo transport configured (GET {path})")


class PayMongoProvider:
    """PayMongo, behind §3's shared `PaymentProvider` interface."""

    def __init__(
        self,
        *,
        secret_key: str = "",
        webhook_secret: str = "",
        transport: PayMongoTransport | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._transport: PayMongoTransport = transport or UnavailablePayMongoTransport()

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    async def create_charge(self, amount: int, currency: str, method: str) -> PaymentEvent:
        """Create a charge, in minor units (centavos).

        Integer minor units rather than a decimal: a currency value in binary floating point is
        a rounding bug waiting for a real invoice, and PayMongo's own API takes centavos for the
        same reason.
        """
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
        """§5's hard requirement, in constant time.

        Returns `False` when no webhook secret is configured rather than skipping the check: an
        install that cannot verify has no basis to trust anything, and "unverifiable" must never
        widen into "accepted".
        """
        if not self._webhook_secret:
            return False
        expected = hmac_sha256_hex(self._webhook_secret, payload)
        return constant_time_signature_matches(expected, signature)

    async def check_status(self, charge_id: str) -> PaymentStatus:
        """That charge's status, or `UNKNOWN` when PayMongo cannot be reached.

        Unknown rather than failed. Treating an unreachable PSP as a failed charge would either
        refund money that was taken or re-charge a card that already paid.
        """
        try:
            payload = self._transport.get(f"/charges/{charge_id}")
        except ProviderUnavailable:
            return PaymentStatus.UNKNOWN
        return STATUS_MAP.get(str(payload.get("status", "")).lower(), PaymentStatus.UNKNOWN)


__all__ = [
    "PROVIDER_NAME",
    "STATUS_MAP",
    "PayMongoProvider",
    "PayMongoTransport",
    "UnavailablePayMongoTransport",
]
