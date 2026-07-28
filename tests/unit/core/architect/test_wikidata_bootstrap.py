"""Wikidata seeding (`v3-deepdive-26-architect-api.md` §3.1, §3.2).

The first test is the one with real history behind it: V2's bootstrap returned ~2,600
entries and missed real PH SMBs because a bare `wdt:P31 wd:Q4830453` matches only the exact
class and silently misses every subclass. This asserts the corrected query keeps the
subclass traversal — a regression here reintroduces a bug that took a corpus-wide
investigation to diagnose.

No test here touches the network. The transport is an adapter seam, and the default
transport reports itself unavailable precisely so an unconfigured install never makes a
surprise request to a public endpoint.
"""

from __future__ import annotations

import asyncio

from core.architect.contracts import SparqlFilter
from core.architect.vendor_directory.seed_sources import SeedSourceRegistry, merge_seed_records
from core.architect.vendor_directory.wikidata_bootstrap import (
    WikidataSeedSource,
    build_sparql_query,
    parse_bindings,
)


def _binding(qid: str, label: str, class_qid: str | None = None) -> dict:
    row = {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "itemLabel": {"value": label},
    }
    if class_qid:
        row["class"] = {"value": f"http://www.wikidata.org/entity/{class_qid}"}
    return row


class _StubTransport:
    """A recorded response, standing in for the endpoint. The whole point of the seam."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.queries: list[str] = []

    async def query(self, endpoint: str, sparql: str) -> dict:
        self.queries.append(sparql)
        return self.payload


def test_query_traverses_subclasses_not_just_the_exact_class():
    query = build_sparql_query()
    assert "wdt:P31/wdt:P279* wd:Q4830453" in query
    assert "wdt:P31 wd:Q4830453 ." not in query


def test_query_filters_on_location_by_country_or_headquarters():
    query = build_sparql_query(SparqlFilter(country_qid="Q928"))
    assert "wdt:P17 wd:Q928" in query
    assert "wdt:P159/wdt:P17 wd:Q928" in query


def test_parse_bindings_maps_known_classes_and_leaves_unknown_ones_uncategorised():
    records = parse_bindings(
        {"results": {"bindings": [
            _binding("Q1", "Some Chain", "Q38076"),
            _binding("Q2", "Some Shop", "Q999999"),
        ]}}
    )
    by_id = {r.external_id: r for r in records}
    assert by_id["Q1"].category_code == "fast_food"
    assert by_id["Q2"].category_code is None


def test_parse_bindings_prefers_the_row_that_supplies_a_category():
    """An item with several P31 values arrives as several rows; the useful one wins."""
    records = parse_bindings(
        {"results": {"bindings": [
            _binding("Q1", "Some Chain", "Q999999"),
            _binding("Q1", "Some Chain", "Q38076"),
        ]}}
    )
    assert len(records) == 1
    assert records[0].category_code == "fast_food"


def test_parse_bindings_survives_a_malformed_payload():
    assert parse_bindings({}) == ()
    assert parse_bindings({"results": {"bindings": "nonsense"}}) == ()
    assert parse_bindings({"results": {"bindings": [{"item": {"value": ""}}]}}) == ()


def test_unconfigured_source_degrades_instead_of_failing_or_calling_out():
    source = WikidataSeedSource()
    assert not source.is_available()
    result = asyncio.run(source.fetch())
    assert result.ok
    assert result.records == ()
    assert "transport" in result.degraded_reason


def test_configured_source_returns_seed_records():
    transport = _StubTransport({"results": {"bindings": [_binding("Q1", "Some Chain", "Q38076")]}})
    source = WikidataSeedSource(transport=transport)
    assert source.is_available()
    result = asyncio.run(source.fetch())
    assert [r.name for r in result.records] == ["Some Chain"]
    assert "wdt:P279*" in transport.queries[0]


def test_a_raising_source_never_takes_down_its_siblings():
    class _Boom:
        name = "boom"

        def is_available(self) -> bool:
            return True

        async def fetch(self, query_filter=None):
            raise RuntimeError("endpoint on fire")

    registry = SeedSourceRegistry(
        (
            _Boom(),
            WikidataSeedSource(
                transport=_StubTransport(
                    {"results": {"bindings": [_binding("Q1", "Some Chain")]}}
                )
            ),
        )
    )
    results = asyncio.run(registry.fetch_all())
    by_source = {r.source: r for r in results}
    assert "endpoint on fire" in by_source["boom"].degraded_reason
    assert len(by_source["wikidata"].records) == 1
    assert len(merge_seed_records(results)) == 1


def test_merge_keeps_the_same_business_from_two_sources():
    """Two sources naming the same business is corroboration, not a duplicate to collapse."""
    class _Other:
        name = "other"

        def is_available(self) -> bool:
            return True

        async def fetch(self, query_filter=None):
            from core.architect.contracts import BootstrapResult, VendorSeedRecord

            return BootstrapResult(
                source="other",
                records=(VendorSeedRecord(source="other", external_id="X1", name="Some Chain"),),
            )

    registry = SeedSourceRegistry(
        (
            _Other(),
            WikidataSeedSource(
                transport=_StubTransport(
                    {"results": {"bindings": [_binding("Q1", "Some Chain")]}}
                )
            ),
        )
    )
    merged = merge_seed_records(asyncio.run(registry.fetch_all()))
    assert {r.source for r in merged} == {"other", "wikidata"}


def test_a_malformed_payload_degrades_the_source_instead_of_raising():
    """`fetch` promises it never raises; parsing used to sit outside that guard.

    A cell arriving as a bare string rather than SPARQL's `{"value": ...}` object made the
    chained `.get` raise `AttributeError` straight out of a monthly background job.
    """

    class MalformedTransport:
        async def query(self, endpoint, sparql):
            return {"results": {"bindings": [{"item": "not-a-cell"}, ["not-a-row"]]}}

    result = asyncio.run(WikidataSeedSource(transport=MalformedTransport()).fetch())
    assert result.records == ()
    assert result.ok


def test_parse_bindings_tolerates_a_cell_that_is_not_an_object():
    assert parse_bindings({"results": {"bindings": [{"item": "x", "itemLabel": 3}]}}) == ()
