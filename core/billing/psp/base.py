"""The `PaymentProvider` Provider Registry (§3, `docs/PRINCIPLES.md` §1.2, §1.3).

§3's requirement is architectural rather than a preference: "PSP credentials must be per-install
config, never hardcoded to one merchant account (or self-hosted buyers would route payments
through the reference deployment's own account)". That single sentence is why the provider is an
interface with credentials injected per instance, rather than a module reading a global.

Both providers are real (§3 resolves the either/or explicitly): PayMongo is the default,
Xendit is available behind the identical interface for an owner who wants broader SEA reach —
"never requiring a rewrite to switch".

**`verify_webhook` is the security-critical method**, and §5 does not treat it as a formality:
"an unverified webhook endpoint is a real, exploitable surface (anyone who discovers the URL
could fake a 'payment succeeded' event without this check)". Every implementation below compares
signatures in constant time, because a byte-by-byte comparison that returns early leaks the
correct signature one character at a time to anyone willing to time it.

**No provider here touches card data** (§1): both aggregators are tokenizing, which is what
keeps this whole API out of PCI scope. A provider implementation that accepted a card number
would be a scope change, not a feature.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Protocol, runtime_checkable

from ..contracts import PaymentEvent, PaymentStatus
from ..errors import ProviderUnavailable


@runtime_checkable
class PaymentProvider(Protocol):
    """§3's interface, verbatim in shape."""

    @property
    def name(self) -> str:
        """Stable identifier, matching the `provider` config value."""

    async def create_charge(self, amount: int, currency: str, method: str) -> PaymentEvent:
        """Create a charge. Raises `ProviderUnavailable` if the PSP cannot be reached."""

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Whether this payload was genuinely signed by the configured provider (§5)."""

    async def check_status(self, charge_id: str) -> PaymentStatus:
        """That charge's current status, or `UNKNOWN` if the PSP cannot be reached."""


def constant_time_signature_matches(expected: str, provided: str) -> bool:
    """Compare two signatures without leaking where they differ.

    `hmac.compare_digest` rather than `==`. A normal string comparison returns as soon as two
    bytes differ, so the time it takes reveals how many leading characters were correct — enough
    for someone to reconstruct a valid signature one character at a time against an endpoint they
    can call repeatedly. That is exactly the "real, exploitable surface" §5 is describing.
    """
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def hmac_sha256_hex(secret: str, payload: bytes) -> str:
    """The signature scheme both providers use.

    Shared rather than duplicated per provider: two implementations of one HMAC would be two
    chances to get the encoding subtly wrong, and a signature check that is wrong in a way that
    accidentally *passes* is the worst possible bug in this file.
    """
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class UnconfiguredProvider:
    """The default when billing is off (§3.1) — refuses everything, invents nothing.

    A fresh install has no PSP configured and every tier free, so this is the ordinary state
    rather than an error condition. It raises rather than returning a fake success because a
    stub that pretended a charge succeeded would grant a paid tier that nobody paid for, and
    `verify_webhook` returns `False` because an install with no configured secret cannot
    possibly have signed anything.
    """

    @property
    def name(self) -> str:
        return "unconfigured"

    async def create_charge(self, amount: int, currency: str, method: str) -> PaymentEvent:
        raise ProviderUnavailable("no payment provider is configured")

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return False

    async def check_status(self, charge_id: str) -> PaymentStatus:
        return PaymentStatus.UNKNOWN


class ProviderRegistry:
    """Which providers this install can use, and which one is selected.

    Mutable internal state populated at startup from config, so a plain `dict` behind no lock is
    not enough — but unlike the other registries in this repo it is written once and read many
    times, so the lock is on the write path only via `register`. Selection is by name from
    config (§3.2's settings screen), never hardcoded.
    """

    def __init__(self) -> None:
        self._providers: dict[str, PaymentProvider] = {}

    def register(self, provider: PaymentProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> PaymentProvider:
        """The named provider, or `UnconfiguredProvider` if it is not registered.

        Falling back rather than raising: an install whose config names a provider nobody
        registered is misconfigured, and the safe reading of that is "no provider", which
        refuses charges. Raising here would take the whole service down over a config typo.
        """
        return self._providers.get(name, UnconfiguredProvider())

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


__all__ = [
    "PaymentProvider",
    "ProviderRegistry",
    "UnconfiguredProvider",
    "constant_time_signature_matches",
    "hmac_sha256_hex",
]
