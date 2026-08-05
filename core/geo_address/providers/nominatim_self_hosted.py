"""Self-hosted Nominatim provider adapter (`v3-deepdive-16-geo-address-api.md` §3, §5, §7).

The operational setup itself — VPS choice, the `mediagis/nominatim` image, the import and
replication process — is `docs/SELF_HOSTED_NOMINATIM.md`, read by whoever actually stands the
endpoint up. That document is not required reading to implement or test this adapter: the
adapter's own job (build a request, parse a response, respect the deployment's own limits) is
indifferent to how the endpoint underneath it was stood up.

**PH-only by construction, not by convention.** §3's reference deployment is a Philippines-only
OSM extract — asking it about a `country_code` other than `PH` is not a network problem, it is
asking a dataset a question outside its own coverage. `is_scoped_to` reports that honestly
rather than this adapter returning a confident-looking wrong answer for a country its data does
not actually cover (`docs/PRINCIPLES.md` §4.4: an out-of-scope provider degrades to
unavailable-for-this-query, it never guesses).

**Rate limiting is `RateLimiter`, not a slowed-down loop** (§5). Nominatim's well-known 1
request/second courtesy limit is enforced per adapter instance so `corroboration.py`'s own
`asyncio.gather` fan-out still completes in roughly its slowest single call's time — this one
provider's calls serialize against themselves, not against the whole corroboration set.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import ProviderCandidateResult
from ..errors import ProviderRequestFailed, ProviderUnavailable
from .base import (
    GeoHttpTransport,
    RateLimiter,
    UnavailableTransport,
    parse_nominatim_style_address,
    parse_nominatim_style_reverse,
    safe_float,
)

#: Nominatim's own published courtesy limit for a shared instance — this project's self-hosted
#: deployment is unlimited-throughput *for us*, but nothing stops another consumer of the same
#: box, so the adapter still honours it by default rather than assuming exclusive use.
DEFAULT_RATE_LIMIT = 1.0


class NominatimSelfHostedProvider:
    """A registry entry. `endpoint` empty is the ordinary not-yet-configured case
    (`docs/PRINCIPLES.md` §4.4) — `is_available()` reports it, and this provider being off does
    not change LocationIQ's or Mapbox's own corroboration in any way."""

    def __init__(
        self,
        *,
        endpoint: str = "",
        transport: GeoHttpTransport | None = None,
        requests_per_second: float = DEFAULT_RATE_LIMIT,
        covers_only: str = "PH",
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._transport: GeoHttpTransport = (
            transport
            if transport is not None
            else UnavailableTransport(
                "no self-hosted Nominatim endpoint configured"
                if not endpoint
                else "no HTTP transport configured"
            )
        )
        self._limiter = RateLimiter(requests_per_second)
        self._covers_only = covers_only.strip().upper()

    @property
    def name(self) -> str:
        return "nominatim_self_hosted"

    def is_available(self) -> bool:
        return bool(self._endpoint) and not isinstance(self._transport, UnavailableTransport)

    def is_scoped_to(self, country_code: str) -> bool:
        """Whether this deployment's own coverage includes the requested country (§3)."""
        return (country_code or "").strip().upper() == self._covers_only

    async def geocode(self, candidate_string: str, *, country_code: str) -> ProviderCandidateResult:
        self._require_in_scope(country_code)
        await self._limiter.acquire()
        payload = await self._call(
            f"{self._endpoint}/search",
            {"q": candidate_string, "format": "json", "addressdetails": 1, "limit": 1},
        )
        entries = payload if isinstance(payload, list) else []
        if not entries or not isinstance(entries[0], Mapping):
            raise ProviderRequestFailed("no results")
        best = entries[0]
        return ProviderCandidateResult(
            provider=self.name,
            candidate_string=candidate_string,
            address=parse_nominatim_style_address(best),
            confidence=safe_float(best.get("importance"), default=0.5) or 0.5,
            matched_business_name=str(best.get("name") or "").strip(),
        )

    async def reverse(
        self, latitude: float, longitude: float, *, country_code: str
    ) -> ProviderCandidateResult:
        self._require_in_scope(country_code)
        await self._limiter.acquire()
        payload = await self._call(
            f"{self._endpoint}/reverse",
            {"lat": latitude, "lon": longitude, "format": "json"},
        )
        return parse_nominatim_style_reverse(self.name, payload)

    def _require_in_scope(self, country_code: str) -> None:
        if not self.is_scoped_to(country_code):
            raise ProviderRequestFailed(
                f"this self-hosted deployment covers {self._covers_only} only, "
                f"not {country_code!r}"
            )

    async def _call(self, url: str, params: Mapping[str, Any]) -> Any:
        try:
            return await self._transport.get_json(url, params=params)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure degrades this provider
            raise ProviderRequestFailed(str(exc)) from exc


__all__ = ["DEFAULT_RATE_LIMIT", "NominatimSelfHostedProvider"]
