"""The `GeoAddressService` gRPC servicer (`v3-deepdive-16-geo-address-api.md` §6).

Two things are being protected here, the same shape Health's own `test_service.py` protects
for its surface: **errors are data, never a raised gRPC status** (`docs/PRINCIPLES.md` §4.1),
and **the translation layer is thin** — every real decision lives in `corroboration.py`, so
these tests assert the servicer faithfully passes things through rather than re-deciding
anything.
"""

from __future__ import annotations

import pytest

from core.geo_address.cache import GeoCache
from core.geo_address.service import GeoAddressServicer, to_query, to_response

from .conftest import FakeProvider, make_address

pb = pytest.importorskip(
    "core.geo_address.generated.geo_address_pb2",
    reason="grpcio/protobuf has no wheel on this interpreter yet (docs/MAINTENANCE.md §3)",
)

MANILA = make_address("123 Rizal Ave, Manila")


def test_to_query_reads_candidate_order_and_country_code():
    request = pb.GeocodeRequest(
        candidate_strings=["top guess", "second guess"],
        providers=["locationiq"],
        country_code="PH",
        vendor_name_hint="Sari-Sari Store",
    )

    query = to_query(request)

    assert query.candidate_strings == ("top guess", "second guess")
    assert query.providers == ("locationiq",)
    assert query.vendor_name_hint == "Sari-Sari Store"


def test_to_query_defaults_country_code_to_ph_when_empty():
    query = to_query(pb.GeocodeRequest(candidate_strings=["q"]))

    assert query.country_code == "PH"


def test_geocode_round_trips_a_successful_result():
    provider = FakeProvider("locationiq", answers={"q": MANILA})
    servicer = GeoAddressServicer(providers=(provider,))

    response = servicer.Geocode(pb.GeocodeRequest(candidate_strings=["q"]), None)

    assert response.error_code == ""
    assert response.result.agreement == "single_source"
    assert response.result.normalized_address.city == "Manila"


def test_geocode_reports_a_conflict_on_the_wire_not_an_error():
    """§4.3 across the boundary: a genuine disagreement is `conflict=True` on `result`, and
    `error_code` stays empty — a client reading a conflict as a failure has misread the API."""
    other = make_address("456 Osmena Blvd, Cebu City", city="Cebu City")
    a = FakeProvider("locationiq", answers={"q": MANILA})
    b = FakeProvider("mapbox", answers={"q": other})
    servicer = GeoAddressServicer(providers=(a, b))

    response = servicer.Geocode(pb.GeocodeRequest(candidate_strings=["q"]), None)

    assert response.error_code == ""
    assert response.result.conflict
    assert not response.result.HasField("normalized_address") or response.result.normalized_address.formatted == ""


def test_malformed_request_returns_an_error_code_not_a_raise():
    servicer = GeoAddressServicer(providers=(FakeProvider("locationiq"),))

    response = servicer.Geocode(pb.GeocodeRequest(candidate_strings=[]), None)

    assert response.error_code == "INVALID_QUERY"


def test_cache_hit_is_reported_on_the_wire():
    cache = GeoCache(":memory:")
    try:
        provider = FakeProvider("locationiq", answers={"q": MANILA})
        servicer = GeoAddressServicer(providers=(provider,), cache=cache)
        request = pb.GeocodeRequest(candidate_strings=["q"])

        first = servicer.Geocode(request, None)
        second = servicer.Geocode(request, None)

        assert not first.result.from_cache
        assert second.result.from_cache
        assert provider.geocode_calls == ["q"]  # the second call never re-hit the provider
    finally:
        cache.close()


def test_to_response_omits_provider_error_fields_on_success():
    from core.geo_address.contracts import GeoResult

    response = to_response(GeoResult(), pb)

    assert response.error_code == ""
    assert list(response.result.provider_results) == []
