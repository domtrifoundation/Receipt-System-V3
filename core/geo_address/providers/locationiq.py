"""LocationIQ provider adapter (`v3-deepdive-16-geo-address-api.md` §3, §6, §7).

One half of the default corroboration pair. LocationIQ is OSM-derived but genuinely
independent of a self-hosted Nominatim extract (a different hosted service, its own free-tier
terms, its own uptime) — real corroboration value alongside Mapbox, not a redundant call to
the same underlying dataset wearing a second API key (§3).

No HTTP client is imported here — see `providers/base.py`'s module docstring for why an
unconfigured provider (no `api_key`) degrades to `is_available() == False` rather than making
a surprise network call, and why every unit test in this package injects a fake
`GeoHttpTransport` instead of touching a real network.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import ProviderCandidateResult
from ..errors import ProviderRequestFailed, ProviderUnavailable
from .base import GeoHttpTransport, RateLimiter, UnavailableTransport, parse_nominatim_style_address, safe_float

#: LocationIQ speaks the Nominatim-compatible `/search`/`/reverse` shape (§3).
SEARCH_URL = "https://us1.locationiq.com/v1/search"
REVERSE_URL = "https://us1.locationiq.com/v1/reverse"


class LocationIQProvider:
    """A registry entry. `api_key` empty is the ordinary unconfigured-install case, not an
    error — `is_available()` reports it, `corroboration.py` skips calling it, and the run
    proceeds with whatever other providers are configured (`docs/PRINCIPLES.md` §4.4)."""

    def __init__(
        self,
        *,
        api_key: str = "",
        transport: GeoHttpTransport | None = None,
        requests_per_second: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._transport: GeoHttpTransport = (
            transport
            if transport is not None
            else UnavailableTransport(
                "no LocationIQ API key configured" if not api_key else "no HTTP transport configured"
            )
        )
        self._limiter = RateLimiter(requests_per_second)

    @property
    def name(self) -> str:
        return "locationiq"

    def is_available(self) -> bool:
        return bool(self._api_key) and not isinstance(self._transport, UnavailableTransport)

    async def geocode(self, candidate_string: str, *, country_code: str) -> ProviderCandidateResult:
        await self._limiter.acquire()
        payload = await self._call(
            SEARCH_URL,
            {
                "key": self._api_key,
                "q": candidate_string,
                "format": "json",
                "countrycodes": country_code.lower(),
                "addressdetails": 1,
                "limit": 1,
            },
        )
        entries = payload if isinstance(payload, list) else []
        if not entries or not isinstance(entries[0], Mapping):
            raise ProviderRequestFailed("no results")
        return _to_candidate_result(self.name, candidate_string, entries[0])

    async def reverse(
        self, latitude: float, longitude: float, *, country_code: str
    ) -> ProviderCandidateResult:
        await self._limiter.acquire()
        payload = await self._call(
            REVERSE_URL,
            {"key": self._api_key, "lat": latitude, "lon": longitude, "format": "json"},
        )
        if not isinstance(payload, Mapping):
            raise ProviderRequestFailed("malformed reverse-geocode response")
        return _to_candidate_result(self.name, "", payload)

    async def _call(self, url: str, params: Mapping[str, Any]) -> Any:
        try:
            return await self._transport.get_json(url, params=params)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure degrades this provider
            raise ProviderRequestFailed(str(exc)) from exc


def _to_candidate_result(
    provider_name: str, candidate_string: str, entry: Mapping[str, Any]
) -> ProviderCandidateResult:
    address = parse_nominatim_style_address(entry)
    matched_name = str(entry.get("name") or "").strip()
    return ProviderCandidateResult(
        provider=provider_name,
        candidate_string=candidate_string,
        address=address,
        confidence=safe_float(entry.get("importance"), default=0.5) or 0.5,
        matched_business_name=matched_name,
    )


__all__ = ["REVERSE_URL", "SEARCH_URL", "LocationIQProvider"]
