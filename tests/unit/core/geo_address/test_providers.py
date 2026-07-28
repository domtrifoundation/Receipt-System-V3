"""The three provider adapters (`v3-deepdive-16-geo-address-api.md` §3, §6, §7).

**No test in this file touches the network.** Every provider is driven through `FakeTransport`
— a `GeoHttpTransport` Protocol implementation returning a canned, hand-written payload shaped
like the real service's own JSON — exactly the seam `providers/base.py`'s module docstring
describes, and the same reason `core/architect/vendor_directory/wikidata_bootstrap.py` needed
no network access either.
"""

from __future__ import annotations

import time

import pytest

from core.geo_address.contracts import ProviderCandidateResult
from core.geo_address.errors import ProviderRequestFailed, ProviderUnavailable
from core.geo_address.providers.base import RateLimiter, UnavailableTransport
from core.geo_address.providers.locationiq import LocationIQProvider
from core.geo_address.providers.mapbox import MapboxProvider
from core.geo_address.providers.nominatim_self_hosted import NominatimSelfHostedProvider

from .conftest import FakeTransport, run

NOMINATIM_STYLE_SEARCH_RESPONSE = [
    {
        "lat": "14.5995",
        "lon": "120.9842",
        "display_name": "123 Rizal Ave, Poblacion, Manila, Metro Manila, 1000, Philippines",
        "name": "Sari-Sari Store",
        "importance": 0.73,
        "address": {
            "house_number": "123",
            "road": "Rizal Ave",
            "suburb": "Poblacion",
            "city": "Manila",
            "state": "Metro Manila",
            "postcode": "1000",
            "country_code": "ph",
        },
    }
]

NOMINATIM_STYLE_REVERSE_RESPONSE = {
    "lat": "14.5995",
    "lon": "120.9842",
    "display_name": "123 Rizal Ave, Manila",
    "name": "Sari-Sari Store",
    "importance": 0.5,
    "address": {"city": "Manila", "country_code": "ph"},
}

MAPBOX_STYLE_RESPONSE = {
    "features": [
        {
            "place_name": "123 Rizal Ave, Manila, Metro Manila 1000, Philippines",
            "text": "Sari-Sari Store",
            "relevance": 0.87,
            "center": [120.9842, 14.5995],
            "properties": {"address": "123 Rizal Ave", "category": "grocery"},
            "context": [
                {"id": "neighborhood.123", "text": "Poblacion"},
                {"id": "place.456", "text": "Manila"},
                {"id": "region.789", "text": "Metro Manila"},
                {"id": "postcode.012", "text": "1000"},
                {"id": "country.345", "text": "Philippines", "short_code": "ph"},
            ],
        }
    ]
}


# --------------------------------------------------------------- unconfigured defaults


@pytest.mark.parametrize(
    "provider",
    [
        LocationIQProvider(),
        MapboxProvider(),
        NominatimSelfHostedProvider(),
    ],
)
def test_an_unconfigured_provider_is_unavailable_by_default(provider):
    """§4.4: no API key or endpoint means unavailable, never a surprise network call."""
    assert not provider.is_available()
    with pytest.raises(ProviderUnavailable):
        run(provider.geocode("q", country_code="PH"))


# --------------------------------------------------------------------- LocationIQ


def test_locationiq_parses_a_search_response_into_a_ph_shaped_address():
    transport = FakeTransport(NOMINATIM_STYLE_SEARCH_RESPONSE)
    provider = LocationIQProvider(api_key="key123", transport=transport)

    assert provider.is_available()
    result = run(provider.geocode("Sari-Sari Store, Manila", country_code="PH"))

    assert isinstance(result, ProviderCandidateResult)
    assert result.address.city == "Manila"
    assert result.address.barangay == "Poblacion"
    assert result.address.province == "Metro Manila" or result.address.region == "Metro Manila"
    assert result.address.country_code == "PH"
    assert result.address.latitude == pytest.approx(14.5995)
    assert result.matched_business_name == "Sari-Sari Store"
    assert transport.calls[0][1]["q"] == "Sari-Sari Store, Manila"


def test_locationiq_reverse_parses_the_single_object_shape():
    transport = FakeTransport(NOMINATIM_STYLE_REVERSE_RESPONSE)
    provider = LocationIQProvider(api_key="key123", transport=transport)

    result = run(provider.reverse(14.5995, 120.9842, country_code="PH"))

    assert result.matched_business_name == "Sari-Sari Store"


def test_locationiq_no_results_raises_provider_request_failed():
    transport = FakeTransport([])
    provider = LocationIQProvider(api_key="key123", transport=transport)

    with pytest.raises(ProviderRequestFailed):
        run(provider.geocode("nonexistent place", country_code="PH"))


def test_locationiq_transport_failure_becomes_provider_request_failed():
    async def _raise(url, *, params):
        raise TimeoutError("connection timed out")

    class RaisingTransport:
        get_json = staticmethod(_raise)

    provider = LocationIQProvider(api_key="key123", transport=RaisingTransport())

    with pytest.raises(ProviderRequestFailed):
        run(provider.geocode("q", country_code="PH"))


# ------------------------------------------------------------------------ Mapbox


def test_mapbox_parses_a_feature_into_a_ph_shaped_address():
    transport = FakeTransport(MAPBOX_STYLE_RESPONSE)
    provider = MapboxProvider(api_key="pk.abc", transport=transport)

    result = run(provider.geocode("Sari-Sari Store, Manila", country_code="PH"))

    assert result.address.city == "Manila"
    assert result.address.barangay == "Poblacion"
    assert result.address.region == "Metro Manila"
    assert result.address.postal_code == "1000"
    assert result.address.country_code == "PH"
    assert result.address.longitude == pytest.approx(120.9842)
    assert result.matched_business_name == "Sari-Sari Store"  # a POI category is present


def test_mapbox_only_reports_a_business_name_for_poi_features():
    """A plain address feature (no `category`) is not a business — reporting one anyway
    would manufacture a false reverse-check signal (`docs/PRINCIPLES.md` §4.3's own spirit:
    do not invent a signal you cannot actually back)."""
    payload = {
        "features": [
            {
                "place_name": "123 Rizal Ave, Manila",
                "text": "Rizal Ave",
                "relevance": 0.6,
                "center": [120.9842, 14.5995],
                "properties": {},
                "context": [],
            }
        ]
    }
    provider = MapboxProvider(api_key="pk.abc", transport=FakeTransport(payload))

    result = run(provider.geocode("123 Rizal Ave", country_code="PH"))

    assert result.matched_business_name == ""


def test_mapbox_no_features_raises_provider_request_failed():
    provider = MapboxProvider(api_key="pk.abc", transport=FakeTransport({"features": []}))

    with pytest.raises(ProviderRequestFailed):
        run(provider.geocode("nowhere", country_code="PH"))


# --------------------------------------------------------- self-hosted Nominatim


def test_nominatim_self_hosted_parses_like_locationiq():
    transport = FakeTransport(NOMINATIM_STYLE_SEARCH_RESPONSE)
    provider = NominatimSelfHostedProvider(
        endpoint="http://10.0.0.5:8080", transport=transport, requests_per_second=0
    )

    result = run(provider.geocode("Sari-Sari Store, Manila", country_code="PH"))

    assert result.address.city == "Manila"
    assert result.matched_business_name == "Sari-Sari Store"


def test_nominatim_self_hosted_is_scoped_to_ph_by_default():
    """The Philippine address specific this adapter exists to get right (deep-dive §3): the
    reference deployment is a PH-only OSM extract. Asking about `country_code="US"` is a
    coverage question, not a network failure, and it degrades honestly rather than guessing."""
    provider = NominatimSelfHostedProvider(endpoint="http://10.0.0.5:8080")

    assert provider.is_scoped_to("PH")
    assert provider.is_scoped_to("ph")  # case-insensitive
    assert not provider.is_scoped_to("US")


def test_nominatim_self_hosted_refuses_out_of_scope_queries_without_a_network_call():
    transport = FakeTransport(NOMINATIM_STYLE_SEARCH_RESPONSE)
    provider = NominatimSelfHostedProvider(
        endpoint="http://10.0.0.5:8080", transport=transport, requests_per_second=0
    )

    with pytest.raises(ProviderRequestFailed):
        run(provider.geocode("123 Main St, Springfield", country_code="US"))

    assert transport.calls == []  # refused before ever reaching the transport


def test_nominatim_self_hosted_covers_only_is_configurable():
    """A self-hosted install is not required to point this at a PH-only extract — the
    coverage claim is a constructor parameter, not a hardcoded assumption."""
    transport = FakeTransport(NOMINATIM_STYLE_SEARCH_RESPONSE)
    provider = NominatimSelfHostedProvider(
        endpoint="http://10.0.0.5:8080",
        transport=transport,
        requests_per_second=0,
        covers_only="US",
    )

    assert provider.is_scoped_to("US")
    assert not provider.is_scoped_to("PH")


def test_nominatim_self_hosted_rate_limit_compliance_under_a_burst():
    """§5, §8's own named testing hook: confirms the token-bucket genuinely caps request
    *rate* even when several corroboration calls burst in at once — a fast interval stands in
    for the real 1 req/sec courtesy limit so this test stays fast without being meaningless."""
    transport = FakeTransport(NOMINATIM_STYLE_SEARCH_RESPONSE)
    interval = 0.05
    provider = NominatimSelfHostedProvider(
        endpoint="http://10.0.0.5:8080", transport=transport, requests_per_second=1.0 / interval
    )

    async def burst():
        import asyncio

        await asyncio.gather(*(provider.geocode("q", country_code="PH") for _ in range(4)))

    started = time.monotonic()
    run(burst())
    elapsed = time.monotonic() - started

    # 4 calls at `interval` apart is at least 3 intervals of enforced spacing.
    assert elapsed >= interval * 3 * 0.8


def test_rate_limiter_with_no_limit_never_waits():
    limiter = RateLimiter(None)

    started = time.monotonic()
    run(limiter.acquire())
    run(limiter.acquire())
    elapsed = time.monotonic() - started

    assert elapsed < 0.05


def test_unavailable_transport_reports_a_specific_reason():
    transport = UnavailableTransport("no LocationIQ API key configured")

    with pytest.raises(ProviderUnavailable, match="no LocationIQ API key configured"):
        run(transport.get_json("https://example.test", params={}))
