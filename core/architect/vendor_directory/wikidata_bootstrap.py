"""Wikidata vendor seeding (`v3-deepdive-26-architect-api.md` §3, §3.1, §3.2).

**The bug this file exists to not repeat.** V2's bootstrap returned only ~2,600 entries
and missed real PH SMBs. The root cause is identified and confirmed against Wikidata's own
tutorial documentation, not suspected: a bare `wdt:P31 wd:Q4830453` clause matches only
items tagged with that *exact* class and silently misses everything classified under a
more specific subclass — which is what a real fast-food or retail chain almost always is.
The fix is subclass traversal, `wdt:P31/wdt:P279* wd:Q4830453`, combined with a location
filter (P17 country or P159 headquarters) rather than name-matching.

**What is still genuinely open** (deep-dive §9): nobody has run the corrected query
against the live endpoint yet to confirm the resulting entry count or spot-check that real
PH SMBs now appear. That is hands-on verification work, not a design question, and this
file does not pretend it has happened.

**Scope is name and category only.** Wikidata is a reasonable source for "this business
exists and is roughly this kind of business" and is genuinely unreliable for TIN and
franchise data — which is why `VendorSeedRecord` has no field to put those in rather than
having optional ones nobody should trust.

**Transport is behind one adapter** (`docs/PRINCIPLES.md` §1.3). Nothing in this module
imports an HTTP client at module scope; the endpoint is reached through a
`SparqlTransport`, and the default one is deliberately `UnavailableTransport` so an
unconfigured instance degrades to "this source contributed nothing" instead of making a
surprise network call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from common.frozen_dict import FrozenDict

from ..contracts import BootstrapResult, SparqlFilter, VendorSeedRecord
from ..errors import ErrorCode, SeedSourceUnavailable, message_for

SOURCE_NAME = "wikidata"

#: The public endpoint. One constant, because a self-hosted install pointing at its own
#: Wikibase mirror should change it in exactly one place.
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

#: Config defaults for the recurring poll (deep-dive §3.2). A monthly default is a
#: courtesy to a public endpoint other projects rely on, and Wikidata's business listings
#: genuinely do not change fast enough to justify tighter. `query_version` is bumped when
#: the query itself changes, so a re-pull caused by this fix is distinguishable from a
#: routine scheduled one. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1.
WIKIDATA_CONFIG_DEFAULTS = FrozenDict({"poll_interval_days": 30, "query_version": 2})

#: Wikidata class QID -> this registry's own category code. Only classes with a confident
#: mapping are listed; anything else seeds with `category_code=None` rather than being
#: guessed into a category, because a wrong category propagates into Matching's own
#: items-vendor mismatch check and produces a flag nobody can explain.
WIKIDATA_CLASS_TO_CATEGORY = FrozenDict(
    {
        "Q18534542": "restaurant",
        "Q11707": "restaurant",
        "Q38076": "fast_food",
        "Q11707649": "fast_food",
        "Q507619": "retail",
        "Q11315": "retail",
        "Q3257686": "convenience_store",
        "Q180846": "supermarket",
        "Q13107184": "pharmacy",
        "Q154136": "fuel_station",
    }
)


def build_sparql_query(query_filter: SparqlFilter | None = None) -> str:
    """The corrected query (deep-dive §3.1).

    Two things carry the fix and both matter: `wdt:P31/wdt:P279*` traverses the class
    hierarchy transitively, and the location clause accepts *either* P17 (country) or P159
    (headquarters location) so a business whose country is only recorded on its
    headquarters is still caught. `OPTIONAL` on the class binding means an item with no
    mappable class still comes back, uncategorised, rather than being dropped.
    """
    f = query_filter or SparqlFilter()
    return f"""SELECT ?item ?itemLabel ?class WHERE {{
  ?item wdt:P31/wdt:P279* wd:{f.root_class_qid} .
  {{ ?item wdt:P17 wd:{f.country_qid} }} UNION {{ ?item wdt:P159/wdt:P17 wd:{f.country_qid} }}
  OPTIONAL {{ ?item wdt:P31 ?class }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{f.language}" }}
}}
LIMIT {f.limit}"""


def _qid_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def _cell_value(row: Mapping[str, Any], key: str) -> str:
    """One SPARQL result cell's `value`, or `""` for anything not shaped like one."""
    cell = row.get(key)
    if not isinstance(cell, Mapping):
        return ""
    value = cell.get("value")
    return str(value) if value is not None else ""


def parse_bindings(payload: Mapping[str, Any]) -> tuple[VendorSeedRecord, ...]:
    """Turn a SPARQL JSON response into seed records.

    Deduplicated by QID, keeping the first row that supplies a mappable category — an item
    with several P31 values comes back as several rows, and taking the first row blindly
    would drop a usable category for an arbitrary reason.

    A malformed payload yields no records rather than raising: this runs inside a
    scheduled background job, and an endpoint returning something unexpected is a reason
    for that run to contribute nothing, never a reason for the job to die.
    """
    results = payload.get("results") if isinstance(payload, Mapping) else None
    bindings = results.get("bindings") if isinstance(results, Mapping) else None
    if not isinstance(bindings, list):
        return ()

    by_qid: dict[str, VendorSeedRecord] = {}
    for row in bindings:
        if not isinstance(row, Mapping):
            continue
        # Each cell is read through `_cell_value`, never `row.get(k, {}).get("value")` —
        # a cell that is a bare string rather than the `{"value": ...}` object SPARQL
        # normally returns would make the chained `.get` raise `AttributeError`, which is
        # exactly the "malformed payload" case this function promises not to raise on.
        qid = _qid_from_uri(_cell_value(row, "item"))
        name = _cell_value(row, "itemLabel").strip()
        if not qid or not name or name == qid:
            continue
        class_qid = _qid_from_uri(_cell_value(row, "class"))
        category = WIKIDATA_CLASS_TO_CATEGORY.get(class_qid)
        existing = by_qid.get(qid)
        if existing is not None and (existing.category_code is not None or category is None):
            continue
        by_qid[qid] = VendorSeedRecord(
            source=SOURCE_NAME,
            external_id=qid,
            name=name,
            category_code=category,
            raw=FrozenDict({"class_qid": class_qid}) if class_qid else FrozenDict({}),
        )
    return tuple(by_qid.values())


class SparqlTransport(Protocol):
    """The one adapter seam between this module and any HTTP client.

    Swapping the client, pointing at a self-hosted Wikibase, or replaying a captured
    response in a test are all the same operation: supply a different implementation of
    this Protocol. No call site in this package touches a network library directly.
    """

    async def query(self, endpoint: str, sparql: str) -> Mapping[str, Any]: ...


class UnavailableTransport:
    """The default. Reports itself unreachable instead of making a surprise network call.

    A fresh install that has never configured outbound access should degrade to "the
    Wikidata source contributed nothing this run" — not attempt an unannounced request to
    a public endpoint, and not fail the bootstrap job either (`docs/PRINCIPLES.md` §4.4).
    """

    def __init__(self, reason: str = "no SPARQL transport is configured") -> None:
        self.reason = reason

    async def query(self, endpoint: str, sparql: str) -> Mapping[str, Any]:
        raise SeedSourceUnavailable(self.reason)


class WikidataSeedSource:
    """One entry in the vendor seed-source registry (`seed_sources.py`).

    Registered alongside any other seed source rather than being *the* bootstrap: the
    Provider Registry pattern applies here in its genuinely-parallel form, since several
    independent sources corroborating that a business exists is worth more than one source
    chosen from a config value (`docs/PRINCIPLES.md` §1.2).
    """

    name = SOURCE_NAME

    def __init__(
        self,
        transport: SparqlTransport | None = None,
        endpoint: str = WIKIDATA_SPARQL_ENDPOINT,
    ) -> None:
        # `is None`, never a truthiness test — this package's own convention, and a
        # transport implementation defining `__len__` or `__bool__` would otherwise be
        # silently swapped for the unavailable default.
        self._transport: SparqlTransport = (
            transport if transport is not None else UnavailableTransport()
        )
        self._endpoint = endpoint

    def is_available(self) -> bool:
        return not isinstance(self._transport, UnavailableTransport)

    async def fetch(self, query_filter: SparqlFilter | None = None) -> BootstrapResult:
        """Pull seed records. Never raises — an unreachable source is data, not an error."""
        sparql = build_sparql_query(query_filter)
        try:
            payload = await self._transport.query(self._endpoint, sparql)
            # Parsing is inside the `try` deliberately: a payload the endpoint returned in
            # an unexpected shape is a failure *of this source*, exactly like an unreachable
            # endpoint, and this method's contract is that it never raises. Parsing outside
            # the guard made "the response was malformed" the one way a monthly background
            # job could still die (`docs/PRINCIPLES.md` §4.4).
            records = parse_bindings(payload)
        except SeedSourceUnavailable as exc:
            return BootstrapResult(source=self.name, degraded_reason=str(exc))
        except Exception as exc:  # noqa: BLE001 - a background job never dies on a source
            return BootstrapResult(
                source=self.name,
                degraded_reason=f"{message_for(ErrorCode.SEED_SOURCE_FAILED)}: {exc}",
            )
        return BootstrapResult(source=self.name, records=records)


__all__ = [
    "WIKIDATA_CLASS_TO_CATEGORY",
    "WIKIDATA_CONFIG_DEFAULTS",
    "WIKIDATA_SPARQL_ENDPOINT",
    "SOURCE_NAME",
    "SparqlTransport",
    "UnavailableTransport",
    "WikidataSeedSource",
    "build_sparql_query",
    "parse_bindings",
]
