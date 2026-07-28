"""Mapbox provider adapter (`v3-deepdive-16-geo-address-api.md` §3, §6, §7).

The other half of the default corroboration pair. Mapbox's own geocoding dataset is built
independently of OpenStreetMap — genuine corroboration value alongside LocationIQ, not a
second call into the same underlying data wearing a different API key (§3).

No HTTP client is imported here — see `providers/base.py`'s module docstring for the transport
seam every provider adapter shares, and why every unit test in this package injects a fake
`GeoHttpTransport` instead of touching a real network.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import GeoAddress, ProviderCandidateResult
from ..errors import ProviderRequestFailed, ProviderUnavailable
from .base import GeoHttpTransport, RateLimiter, UnavailableTransport, safe_float

#: Mapbox's own Geocoding API v5 shape — `{query}.json` for forward, `{lon},{lat}.json` for
#: reverse, both against the same `mapbox.places` dataset (§3).
GEOCODING_BASE = "https://api.mapbox.com/geocoding/v5/mapbox.places"


class MapboxProvider:
    """A registry entry. `api_key` empty is the ordinary unconfigured-install case, not an
    error (`docs/PRINCIPLES.md` §4.4) — `is_available()` reports it and `corroboration.py`
    skips calling it, proceeding with whatever other providers are configured."""

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
                "no Mapbox API key configured" if not api_key else "no HTTP transport configured"
            )
        )
        self._limiter = RateLimiter(requests_per_second)

    @property
    def name(self) -> str:
        return "mapbox"

    def is_available(self) -> bool:
        return bool(self._api_key) and not isinstance(self._transport, UnavailableTransport)

    async def geocode(self, candidate_string: str, *, country_code: str) -> ProviderCandidateResult:
        await self._limiter.acquire()
        payload = await self._call(
            f"{GEOCODING_BASE}/{candidate_string}.json",
            {"access_token": self._api_key, "country": country_code.lower(), "limit": 1},
        )
        feature = _first_feature(payload)
        if feature is None:
            raise ProviderRequestFailed("no results")
        return _to_candidate_result(self.name, candidate_string, feature)

    async def reverse(
        self, latitude: float, longitude: float, *, country_code: str
    ) -> ProviderCandidateResult:
        await self._limiter.acquire()
        payload = await self._call(
            f"{GEOCODING_BASE}/{longitude},{latitude}.json",
            {"access_token": self._api_key, "types": "poi,address"},
        )
        feature = _first_feature(payload)
        if feature is None:
            raise ProviderRequestFailed("no results")
        return _to_candidate_result(self.name, "", feature)

    async def _call(self, url: str, params: Mapping[str, Any]) -> Any:
        try:
            return await self._transport.get_json(url, params=params)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure degrades this provider
            raise ProviderRequestFailed(str(exc)) from exc


def _first_feature(payload: Any) -> Mapping[str, Any] | None:
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list) or not features or not isinstance(features[0], Mapping):
        return None
    return features[0]


def _context_value(context: list, *id_prefixes: str) -> str:
    for item in context:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("id") or "")
        if any(item_id.startswith(prefix) for prefix in id_prefixes):
            return str(item.get("text") or "")
    return ""


def _country_code_from_context(context: list) -> str:
    for item in context:
        if isinstance(item, Mapping) and str(item.get("id", "")).startswith("country"):
            return str(item.get("short_code") or "").upper()
    return ""


def _address_from_feature(feature: Mapping[str, Any]) -> GeoAddress:
    context = feature.get("context")
    context = context if isinstance(context, list) else []
    properties = feature.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    center = feature.get("center")
    center = center if isinstance(center, list) else []
    return GeoAddress(
        formatted=str(feature.get("place_name") or ""),
        line1=str(properties.get("address") or ""),
        barangay=_context_value(context, "neighborhood", "locality"),
        city=_context_value(context, "place"),
        province=_context_value(context, "district"),
        region=_context_value(context, "region"),
        postal_code=_context_value(context, "postcode"),
        country_code=_country_code_from_context(context) or "PH",
        latitude=safe_float(center[1]) if len(center) > 1 else None,
        longitude=safe_float(center[0]) if len(center) > 0 else None,
    )


def _to_candidate_result(
    provider_name: str, candidate_string: str, feature: Mapping[str, Any]
) -> ProviderCandidateResult:
    properties = feature.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    matched_name = str(feature.get("text") or "") if properties.get("category") else ""
    return ProviderCandidateResult(
        provider=provider_name,
        candidate_string=candidate_string,
        address=_address_from_feature(feature),
        confidence=safe_float(feature.get("relevance"), default=0.5) or 0.5,
        matched_business_name=matched_name,
    )


__all__ = ["GEOCODING_BASE", "MapboxProvider"]
