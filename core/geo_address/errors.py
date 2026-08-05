"""Geo/Address API error taxonomy.

These are surfaced as `GeoError.code`/`.detail` on `contracts.GeoResult` and on the wire's
`error_code`/`error_detail` fields, never raised across the gRPC boundary
(`docs/PRINCIPLES.md` §4.1). Geo/Address has no equivalent of Auth's raise-loudly carve-out:
nothing here is a security decision, and a caller that got no address correction this run is
strictly better served by a low-confidence `GeoResult` than by an exception.

The exception classes below exist for the *internal* call path only, where telling them apart
is genuinely useful: a provider adapter with no API key configured degrades that provider,
while a malformed request from a caller is a bug worth surfacing distinctly
(`errors.InvalidQuery`). `corroboration.py` is the one place a provider's raised exception
gets converted into a `ProviderCandidateResult.error`, never re-raised past that point.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class GeoAddressError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class ProviderUnavailable(GeoAddressError):
    """A provider has no working transport configured — no API key, no self-hosted endpoint.

    Distinct from `ProviderRequestFailed`: this is "this provider was never wired up," not
    "this provider was wired up and the call itself failed" — an operator fixes each one a
    different way. Raised by a provider adapter's own `UnavailableTransport` default
    (`providers/base.py`), the same seam Architect's `SparqlTransport`/`UnavailableTransport`
    already established for exactly this reason (`docs/PRINCIPLES.md` §1.3, §4.4): an
    unconfigured install degrades that one provider to unavailable rather than attempting a
    surprise call to a paid or rate-limited external service.
    """


class ProviderRequestFailed(GeoAddressError):
    """A provider was reachable but its own call failed or returned nothing usable — a real
    network error, a malformed response, or (for the self-hosted Nominatim adapter
    specifically) a query outside that deployment's own stated coverage."""


class InvalidQuery(GeoAddressError):
    """A malformed `GeoQuery` — no candidate strings, or a `providers` filter that resolves
    to no registered provider at all."""


class CacheUnavailable(GeoAddressError):
    """The response cache's own SQLite database could not be opened.

    Not fatal by construction (§4.4): the cache is an accelerator that stretches every
    provider's free tier (deep-dive §4), never a source of truth — `cache.py` degrades to
    "treat this as a cache miss" rather than failing the geocode call it was asked to
    accelerate.
    """


#: Stable wire codes for `geo_address.proto`'s own `error_code` field. Field-only-append
#: discipline applies here the same way it does to the `.proto` itself: a code is added,
#: never renamed, because a caller may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        ProviderUnavailable: "PROVIDER_UNAVAILABLE",
        ProviderRequestFailed: "PROVIDER_REQUEST_FAILED",
        InvalidQuery: "INVALID_QUERY",
        CacheUnavailable: "CACHE_UNAVAILABLE",
    }
)

#: Operator-facing one-liners, keyed by the wire code rather than the exception class so a
#: caller holding only a `GeoError.code` string (the common case, once it has crossed the
#: gRPC boundary) still has something to show. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "PROVIDER_UNAVAILABLE": "this provider has no API key or endpoint configured",
        "PROVIDER_REQUEST_FAILED": "the provider was reachable but returned nothing usable",
        "INVALID_QUERY": "the geocode request had no usable candidate strings or providers",
        "CACHE_UNAVAILABLE": "the response cache could not be opened; the run continued uncached",
        "INTERNAL": "an unmapped internal error occurred",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself (the same reasoning Logs' own `code_for` states).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    """Default text for a wire code, or the code itself when it has no registered text."""
    return ERROR_SUMMARIES.get(code, code)


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "CacheUnavailable",
    "GeoAddressError",
    "InvalidQuery",
    "ProviderRequestFailed",
    "ProviderUnavailable",
    "code_for",
    "summary_for",
]
