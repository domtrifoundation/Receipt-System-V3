"""The response cache over the provider registry (`v3-deepdive-16-geo-address-api.md` §4).

`GeoCache` is what stretches every provider's free tier — a repeated lookup for a common
vendor's address across many receipts should never re-hit a rate-limited provider for data
this build already has. The staleness window is what keeps that promise honest rather than
permanent: a cached answer for a business that has since moved must eventually be refetched.
"""

from __future__ import annotations

import collections.abc

import pytest

from common.frozen_dict import FrozenDict
from core.geo_address.cache import CachePolicy, GeoCache, normalize_query
from core.geo_address.contracts import AgreementLevel, GeoAddress, GeoResult, ProviderCandidateResult

from .conftest import FakeClock, make_address


@pytest.fixture
def cache(tmp_path, clock: FakeClock) -> GeoCache:
    c = GeoCache(tmp_path / "geo_cache.sqlite", policy=CachePolicy(stale_after_days=90), now=clock)
    yield c
    c.close()


def make_result(**overrides) -> GeoResult:
    defaults = dict(
        normalized_address=make_address("123 Rizal Ave, Manila"),
        confidence=0.9,
        agreement=AgreementLevel.UNANIMOUS,
        matched_candidate_string="q",
        provider_results=(
            ProviderCandidateResult(
                provider="locationiq",
                candidate_string="q",
                address=make_address("123 Rizal Ave, Manila"),
                confidence=0.9,
                raw=FrozenDict({"display_name": "123 Rizal Ave, Manila"}),
            ),
        ),
    )
    defaults.update(overrides)
    return GeoResult(**defaults)


def test_a_fresh_lookup_is_a_genuine_miss(cache: GeoCache):
    assert cache.get(cache.normalize(("q",), "PH", ("locationiq",))) is None


def test_put_then_get_round_trips_the_full_result(cache: GeoCache):
    key = cache.normalize(("q",), "PH", ("locationiq",))
    original = make_result()

    cache.put(key, original)
    hit = cache.get(key)

    assert hit is not None
    result, stale = hit
    assert not stale
    assert result.normalized_address == original.normalized_address
    assert result.agreement is original.agreement
    assert result.provider_results[0].provider == "locationiq"
    assert result.from_cache


def test_a_stale_entry_is_reported_as_stale_not_as_a_miss(cache: GeoCache, clock: FakeClock):
    """§4: a repeated lookup past the staleness window is real data, still worth returning as
    a fallback of last resort — `corroboration.py` decides what to do with `stale`, this layer
    just reports it honestly rather than pretending the entry never existed."""
    key = cache.normalize(("q",), "PH", ("locationiq",))
    cache.put(key, make_result())

    clock.advance(days=91)
    hit = cache.get(key)

    assert hit is not None
    result, stale = hit
    assert stale
    assert result.normalized_address is not None


def test_an_entry_within_the_window_is_not_stale(cache: GeoCache, clock: FakeClock):
    key = cache.normalize(("q",), "PH", ("locationiq",))
    cache.put(key, make_result())

    clock.advance(days=89)
    _, stale = cache.get(key)

    assert not stale


def test_normalize_query_is_independent_of_whitespace_and_case():
    a = normalize_query(["  Sari-Sari Store,  Manila  "], "ph", ["LocationIQ"])
    b = normalize_query(["sari-sari store, manila"], "PH", ["locationiq"])

    assert a == b


def test_normalize_query_is_independent_of_provider_order():
    a = normalize_query(["q"], "PH", ["mapbox", "locationiq"])
    b = normalize_query(["q"], "PH", ["locationiq", "mapbox"])

    assert a == b


def test_different_candidate_strings_produce_different_keys():
    a = normalize_query(["123 Rizal Ave"], "PH", ["locationiq"])
    b = normalize_query(["456 Osmena Blvd"], "PH", ["locationiq"])

    assert a != b


def test_a_conflicted_result_still_caches_its_provider_disagreement(cache: GeoCache):
    """A `SPLIT` still cost two real provider calls — worth caching so a repeat lookup for
    the same disagreeing address does not re-spend that budget, even though there is no single
    winning address to hand back."""
    key = cache.normalize(("q",), "PH", ("locationiq", "mapbox"))
    conflicted = make_result(
        normalized_address=None,
        agreement=AgreementLevel.SPLIT,
        conflict=True,
        conflict_detail="locationiq: A; mapbox: B",
        confidence=0.2,
    )

    cache.put(key, conflicted)
    result, stale = cache.get(key)

    assert not stale
    assert result.conflict
    assert result.normalized_address is None


def test_an_unreadable_cache_file_degrades_to_a_miss_not_a_raise(tmp_path):
    """`docs/PRINCIPLES.md` §4.4: a cache read that cannot be trusted must cost a provider
    round-trip, never the whole geocode run it was only ever trying to accelerate."""
    db_path = tmp_path / "geo_cache.sqlite"
    cache = GeoCache(db_path)
    key = cache.normalize(("q",), "PH", ("locationiq",))
    cache.put(key, make_result())
    cache.close()

    # Corrupt the stored JSON directly, simulating a row a newer/older build wrote.
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE geo_cache SET result_json = 'not json' WHERE cache_key = ?", (key,))
    conn.commit()
    conn.close()

    reopened = GeoCache(db_path)
    try:
        assert reopened.get(key) is None
    finally:
        reopened.close()


def test_geo_address_round_trips_every_field_through_json(cache: GeoCache):
    key = cache.normalize(("q",), "PH", ("locationiq",))
    address = GeoAddress(
        formatted="123 Rizal Ave, Barangay Poblacion, Manila, Metro Manila, 1000",
        line1="123 Rizal Ave",
        barangay="Poblacion",
        city="Manila",
        province="Metro Manila",
        region="NCR",
        postal_code="1000",
        country_code="PH",
        latitude=14.5995,
        longitude=120.9842,
    )
    cache.put(key, make_result(normalized_address=address))

    result, _ = cache.get(key)

    assert result.normalized_address == address


@pytest.mark.forward_compat
def test_decoded_provider_results_carry_a_frozen_dict_raw_field(cache: GeoCache):
    key = cache.normalize(("q",), "PH", ("locationiq",))
    cache.put(key, make_result())

    result, _ = cache.get(key)

    raw = result.provider_results[0].raw
    assert isinstance(raw, collections.abc.Mapping)
    assert type(raw) is FrozenDict
    with pytest.raises(TypeError):
        raw["display_name"] = "changed"  # type: ignore[index]
