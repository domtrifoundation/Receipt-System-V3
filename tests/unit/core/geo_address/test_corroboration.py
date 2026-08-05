"""Multi-provider + multi-candidate corroboration (`v3-deepdive-16-geo-address-api.md` §3, §5).

Three guarantees this module protects, each with its own named test below:

* **A genuine disagreement is surfaced, never silently resolved**
  (`docs/PRINCIPLES.md` §4.3) — `test_genuine_disagreement_is_surfaced_never_silently_resolved`.
* **A missing or failed provider degrades that provider, never the whole run**
  (§4.4) — the single-down and all-down tests.
* **The corroboration fan-out is concurrent, not a sequential loop** (§5) — this is the literal
  V2 bug (`urllib.request.urlopen()` in a `for` loop) this API exists to not repeat, and
  `test_corroboration_scales_with_the_slowest_call_not_the_sum` is its direct regression guard.
"""

from __future__ import annotations

import time

import pytest

from core.geo_address.contracts import AgreementLevel, GeoQuery
from core.geo_address.corroboration import geocode_with_corroboration

from .conftest import FakeProvider, make_address, run

MANILA = make_address("123 Rizal Ave, Manila, Metro Manila, 1000, Philippines")
MANILA_CLOSE = make_address("123 Rizal Avenue, Manila, Metro Manila, 1000, Philippines")
CEBU = make_address("456 Osmena Blvd, Cebu City, Cebu, 6000, Philippines", city="Cebu City")


def test_two_agreeing_providers_produce_unanimous_agreement():
    a = FakeProvider("locationiq", answers={"Sari-Sari Store, Manila": MANILA})
    b = FakeProvider("mapbox", answers={"Sari-Sari Store, Manila": MANILA_CLOSE})
    query = GeoQuery(candidate_strings=("Sari-Sari Store, Manila",))

    result = run(geocode_with_corroboration(query, (a, b)))

    assert result.ok
    assert result.agreement is AgreementLevel.UNANIMOUS
    assert result.normalized_address is not None
    assert result.normalized_address.city == "Manila"
    assert result.degraded_providers == ()


def test_majority_of_three_outvotes_one_outlier():
    candidate = "Sari-Sari Store, Manila"
    a = FakeProvider("locationiq", answers={candidate: MANILA})
    b = FakeProvider("mapbox", answers={candidate: MANILA_CLOSE})
    c = FakeProvider("nominatim_self_hosted", answers={candidate: CEBU})
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (a, b, c)))

    assert result.agreement is AgreementLevel.MAJORITY
    assert result.normalized_address.city == "Manila"
    assert not result.conflict


def test_genuine_disagreement_is_surfaced_never_silently_resolved():
    """`docs/PRINCIPLES.md` §4.3: two providers disagreeing about where a business is must
    never be quietly resolved by picking one — `normalized_address` stays `None` and the
    conflict is reported as data, exactly like Reimport's own three-way-diff conflict case."""
    candidate = "Sari-Sari Store, Manila"
    a = FakeProvider("locationiq", answers={candidate: MANILA})
    b = FakeProvider("mapbox", answers={candidate: CEBU})
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (a, b)))

    assert result.ok  # a conflict is a real answer, not an API-boundary error (§4.1)
    assert result.agreement is AgreementLevel.SPLIT
    assert result.conflict
    assert result.normalized_address is None
    assert "locationiq" in result.conflict_detail and "mapbox" in result.conflict_detail


def test_one_provider_unavailable_degrades_that_provider_not_the_run():
    """§4.4: a provider with no working transport is unavailable, never a failed geocode."""
    candidate = "Sari-Sari Store, Manila"
    up = FakeProvider("locationiq", answers={candidate: MANILA})
    down = FakeProvider("mapbox", available=False)
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (up, down)))

    assert result.ok
    assert result.agreement is AgreementLevel.SINGLE_SOURCE
    assert result.normalized_address.formatted == MANILA.formatted
    assert result.degraded_providers == ("mapbox",)
    assert down.geocode_calls == []  # never called at all, not called-and-failed


def test_one_provider_failing_mid_call_also_degrades_gracefully():
    """Distinct from `available=False`: this provider *is* configured but its own call for
    this candidate fails — still a degradation, not a failed run."""
    candidate = "Sari-Sari Store, Manila"
    up = FakeProvider("locationiq", answers={candidate: MANILA})
    flaky = FakeProvider("mapbox", fail_on=frozenset({candidate}))
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (up, flaky)))

    assert result.ok
    assert result.agreement is AgreementLevel.SINGLE_SOURCE
    assert result.degraded_providers == ("mapbox",)
    assert flaky.geocode_calls == [candidate]  # it *was* called


def test_all_providers_down_is_an_honest_empty_result_not_a_failed_run():
    """§4.4's sharpest case: every provider unavailable is still not an `error` — a caller
    checking `result.ok` sees success with zero corroboration, distinguishable via
    `agreement is NONE` and a full `degraded_providers` list, never an exception or a
    `result.error` that would suggest something crashed."""
    candidate = "Sari-Sari Store, Manila"
    a = FakeProvider("locationiq", available=False)
    b = FakeProvider("mapbox", available=False)
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (a, b)))

    assert result.ok
    assert result.error is None
    assert result.agreement is AgreementLevel.NONE
    assert result.normalized_address is None
    assert sorted(result.degraded_providers) == ["locationiq", "mapbox"]


def test_empty_candidate_strings_is_a_real_invalid_query_error():
    """The one genuine `error` case (§4.1) — a malformed request, not a degraded provider."""
    result = run(geocode_with_corroboration(GeoQuery(candidate_strings=()), (FakeProvider("locationiq"),)))

    assert not result.ok
    assert result.error.code == "INVALID_QUERY"


def test_requesting_an_unregistered_provider_set_is_a_real_invalid_query_error():
    query = GeoQuery(candidate_strings=("x",), providers=("not_a_real_provider",))

    result = run(geocode_with_corroboration(query, (FakeProvider("locationiq"),)))

    assert not result.ok
    assert result.error.code == "INVALID_QUERY"


def test_provider_filter_narrows_which_providers_are_queried():
    a = FakeProvider("locationiq", answers={"q": MANILA})
    b = FakeProvider("mapbox", answers={"q": MANILA})
    query = GeoQuery(candidate_strings=("q",), providers=("locationiq",))

    run(geocode_with_corroboration(query, (a, b)))

    assert a.geocode_calls == ["q"]
    assert b.geocode_calls == []


# ------------------------------------------------------- the second corroboration axis


def test_second_axis_prefers_stronger_corroboration_over_the_top_ranked_candidate():
    """§3's own second axis, stated explicitly: searching several OCR candidate strings
    against the same providers, not just the top-ranked one, is what catches a top reading
    that every provider either fails on or only one provider can answer. Here the *second*
    candidate string earns genuine two-provider unanimous agreement while the *first*
    (higher-OCR-rank) string only ever gets one provider's answer — the second string should
    win, because "more strongly corroborated" outranks "OCR's own top guess" (`contracts.
    AGREEMENT_RANK`)."""
    top_ranked = "Sari-Sari Stor, Manial"  # the garbled top OCR reading
    second_ranked = "Sari-Sari Store, Manila"  # a lower-ranked but genuinely correct reading

    a = FakeProvider(
        "locationiq",
        answers={top_ranked: MANILA, second_ranked: MANILA},
    )
    b = FakeProvider("mapbox", answers={second_ranked: MANILA_CLOSE})  # cannot resolve the garble
    query = GeoQuery(candidate_strings=(top_ranked, second_ranked))

    result = run(geocode_with_corroboration(query, (a, b)))

    assert result.matched_candidate_string == second_ranked
    assert result.agreement is AgreementLevel.UNANIMOUS


def test_top_ranked_candidate_wins_ties_when_corroboration_is_equally_strong():
    """The tie-break direction matters as much as the override above: OCR's own ranking is
    the deciding factor once corroboration strength is equal, not an arbitrary one."""
    first = "candidate one"
    second = "candidate two"
    a = FakeProvider("locationiq", answers={first: MANILA, second: MANILA})
    b = FakeProvider("mapbox", answers={first: MANILA_CLOSE, second: MANILA_CLOSE})
    query = GeoQuery(candidate_strings=(first, second))

    result = run(geocode_with_corroboration(query, (a, b)))

    assert result.matched_candidate_string == first


# ------------------------------------------------------------------- concurrency


def test_corroboration_scales_with_the_slowest_call_not_the_sum():
    """The direct regression guard for §5: V2's own bug was a sequential `for` loop of
    blocking geocode calls. Four (provider, candidate) pairs at 0.2s each must complete in
    roughly 0.2s total via `asyncio.gather`, not 0.8s summed — the generous ceiling below
    still clearly separates "concurrent" from "sequential" without being flaky on slow CI."""
    candidates = ("q1", "q2")
    a = FakeProvider("locationiq", answers={c: MANILA for c in candidates}, delay=0.2)
    b = FakeProvider("mapbox", answers={c: MANILA for c in candidates}, delay=0.2)
    query = GeoQuery(candidate_strings=candidates)

    started = time.monotonic()
    run(geocode_with_corroboration(query, (a, b)))
    elapsed = time.monotonic() - started

    assert elapsed < 0.5  # sequential would be ~0.8s (4 calls x 0.2s); concurrent is ~0.2s


# ------------------------------------------------------------------- reverse-check


def test_reverse_check_flags_a_vendor_name_discrepancy():
    """The reverse-check half of this API's own two-capability scope (deep-dive §1): an
    OCR-read vendor name that does not match what the geocoder itself found at that address
    is a real corroboration signal for Matching, surfaced rather than silently dropped."""
    candidate = "some address"
    a = FakeProvider("locationiq", answers={candidate: MANILA}, reverse_name="Totally Different Corp")
    query = GeoQuery(candidate_strings=(candidate,), vendor_name_hint="Sari-Sari Store")

    result = run(geocode_with_corroboration(query, (a,)))

    assert result.vendor_name_at_address == "Totally Different Corp"
    assert result.vendor_name_discrepancy


def test_reverse_check_confirms_a_matching_vendor_name():
    candidate = "some address"
    a = FakeProvider("locationiq", answers={candidate: MANILA}, reverse_name="Sari-Sari Store")
    query = GeoQuery(candidate_strings=(candidate,), vendor_name_hint="Sari-Sari Store")

    result = run(geocode_with_corroboration(query, (a,)))

    assert result.vendor_name_at_address == "Sari-Sari Store"
    assert not result.vendor_name_discrepancy


def test_reverse_check_is_skipped_without_a_vendor_hint():
    """No hint means nothing to corroborate against — skipped, not run against nothing."""
    candidate = "some address"
    a = FakeProvider("locationiq", answers={candidate: MANILA}, reverse_name="Whatever Corp")
    query = GeoQuery(candidate_strings=(candidate,))

    result = run(geocode_with_corroboration(query, (a,)))

    assert result.vendor_name_at_address == ""
    assert not result.vendor_name_discrepancy
    assert a.reverse_calls == []
