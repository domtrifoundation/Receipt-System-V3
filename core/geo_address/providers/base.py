"""Provider Registry foundations — the `GeoProvider` Protocol, the shared HTTP transport
seam, and per-provider rate limiting (`v3-deepdive-16-geo-address-api.md` §3, §5, §7).

**`GeoProvider` is a Protocol, not a base class**, matching Architect's own `VendorSeedSource`
(`vendor_directory/seed_sources.py`) — several independent implementations, registered
together, run in parallel for real corroboration value rather than one config-selected
default (`docs/PRINCIPLES.md` §1.2).

**Every provider's own HTTP client sits behind `GeoHttpTransport`, never imported at module
scope in `locationiq.py`/`mapbox.py`/`nominatim_self_hosted.py`.** This is the identical seam
Architect's `SparqlTransport` already established (`vendor_directory/wikidata_bootstrap.py`)
for the identical reason: swapping the client, recording a fixture, or injecting a fake for a
test are all the same operation — supply a different `GeoHttpTransport` — and an unconfigured
provider degrades to reporting itself unavailable rather than attempting a surprise call to a
paid or rate-limited external service (`docs/PRINCIPLES.md` §1.3, §4.4). This is also why no
unit test in this package needs network access: every test injects a fake transport.

**Rate limiting is a `RateLimiter` instance per provider, never a slowed-down sequential
loop** (§5's own binding requirement — the real V2 bug this API exists to not repeat). The
corroboration fan-out in `corroboration.py` still completes in roughly its slowest single
call's time; a rate-limited provider (self-hosted Nominatim's well-known 1 request/second
courtesy limit) only serializes *its own* calls against itself.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from ..contracts import GeoAddress, ProviderCandidateResult


@runtime_checkable
class GeoHttpTransport(Protocol):
    """The one adapter seam between a provider and any HTTP client (`docs/PRINCIPLES.md`
    §1.3). A provider adapter is pure request-building and response-parsing; nothing in this
    package imports an HTTP client directly."""

    async def get_json(self, url: str, *, params: Mapping[str, Any]) -> Mapping[str, Any]: ...


class UnavailableTransport:
    """The default transport. An unconfigured provider (no API key, no self-hosted endpoint)
    reports itself unreachable rather than making a surprise call to an external service
    (`docs/PRINCIPLES.md` §4.4) — the same default Architect's own `SparqlTransport` uses."""

    def __init__(self, reason: str = "no HTTP transport is configured") -> None:
        self.reason = reason

    async def get_json(self, url: str, *, params: Mapping[str, Any]) -> Mapping[str, Any]:
        from ..errors import ProviderUnavailable

        raise ProviderUnavailable(self.reason)


@runtime_checkable
class GeoProvider(Protocol):
    """One entry in the Geo/Address provider registry.

    `geocode` is the forward half of this API's own two-capability scope (deep-dive §1):
    turn one OCR candidate string into a normalized `GeoAddress`. `reverse` is the second,
    distinct capability — given resolved coordinates, report what business is actually there,
    which is what lets `corroboration.py`'s reverse-check phase cross-corroborate an OCR-read
    vendor name against the geocoder's own answer. Both raise on failure (`errors.
    ProviderUnavailable`/`ProviderRequestFailed`); `corroboration.py` is the one place that
    exception becomes a `ProviderCandidateResult.error` instead of propagating (§4.1, §4.4).
    """

    @property
    def name(self) -> str: ...

    def is_available(self) -> bool: ...

    async def geocode(
        self, candidate_string: str, *, country_code: str
    ) -> ProviderCandidateResult: ...

    async def reverse(
        self, latitude: float, longitude: float, *, country_code: str
    ) -> ProviderCandidateResult: ...


class RateLimiter:
    """A minimal async token-bucket-of-one: at most one call leaves every `1/requests_per_
    second`. `None`/`0` disables limiting entirely (LocationIQ's and Mapbox's own free tiers
    are call-count-bounded, not rate-bounded, so they pass `None`).

    Deliberately not a `asyncio.Semaphore` alone: a semaphore caps *concurrency*, not *rate* —
    N permits all released at once still lets N calls leave in the same instant. Serializing
    on `_last_call` plus `asyncio.sleep` is what actually caps requests/second, which is the
    literal requirement §5 states for Nominatim's 1 req/sec courtesy limit.
    """

    def __init__(self, requests_per_second: float | None) -> None:
        self._min_interval = (1.0 / requests_per_second) if requests_per_second else 0.0
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                wait = self._last_call + self._min_interval - now
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call = time.monotonic()


def safe_float(value: Any, *, default: float | None = None) -> float | None:
    """A provider's own JSON is untrusted input — a missing or non-numeric field degrades to
    `default` rather than raising out of a response parser."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_nominatim_style_address(entry: Mapping[str, Any]) -> GeoAddress:
    """Shared response-shape parser for LocationIQ and self-hosted Nominatim.

    Both providers speak the identical Nominatim-compatible JSON shape (LocationIQ is built
    directly on top of it) — one parser, not two independently-maintained opinions about the
    same wire format, the same reasoning Logs' own `jsonl.py` states for its one codec.
    """
    address = entry.get("address")
    address = address if isinstance(address, Mapping) else {}

    def pick(*keys: str) -> str:
        for key in keys:
            value = address.get(key)
            if value:
                return str(value)
        return ""

    line1 = " ".join(
        part for part in (pick("house_number"), pick("road")) if part
    ).strip()
    country_code = pick("country_code").upper() or "PH"
    return GeoAddress(
        formatted=str(entry.get("display_name") or line1 or pick("city") or "").strip(),
        line1=line1,
        barangay=pick("suburb", "neighbourhood", "quarter", "village"),
        city=pick("city", "town", "municipality"),
        province=pick("county", "state_district"),
        region=pick("state", "region"),
        postal_code=pick("postcode"),
        country_code=country_code,
        latitude=safe_float(entry.get("lat")),
        longitude=safe_float(entry.get("lon")),
    )


def parse_nominatim_style_reverse(provider_name: str, payload: Any) -> ProviderCandidateResult:
    """The reverse-endpoint counterpart: one object, not a results array, otherwise the same
    Nominatim-compatible shape as `parse_nominatim_style_address`."""
    from ..errors import ProviderRequestFailed

    if not isinstance(payload, Mapping):
        raise ProviderRequestFailed("malformed reverse-geocode response")
    address = parse_nominatim_style_address(payload)
    matched_name = str(payload.get("name") or "").strip()
    if not matched_name:
        namedetails = payload.get("namedetails")
        if isinstance(namedetails, Mapping):
            matched_name = str(namedetails.get("name") or "").strip()
    return ProviderCandidateResult(
        provider=provider_name,
        candidate_string="",
        address=address,
        confidence=safe_float(payload.get("importance"), default=0.4) or 0.4,
        matched_business_name=matched_name,
    )


__all__ = [
    "GeoHttpTransport",
    "GeoProvider",
    "RateLimiter",
    "UnavailableTransport",
    "parse_nominatim_style_address",
    "parse_nominatim_style_reverse",
    "safe_float",
]
