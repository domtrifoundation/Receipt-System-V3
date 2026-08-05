"""Search/Query API error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts rather than raised
across the API boundary (`docs/PRINCIPLES.md` §4.1). They exist as real types because the
*internal* call path still benefits from telling them apart — a caller denied for lacking a
break-glass grant and one denied for not managing the relevant group are different problems
with different operator responses, even though both surface as an ordinary denial.

Search/Query has no equivalent of Auth's raise-loudly carve-out. The one place this API is
deliberately *not* graceful is `permission_gate.py`'s own authorization decision: with no
checker wired up, or a checker that cannot be reached, a cross-user or cross-group read is
denied, never allowed (`docs/PRINCIPLES.md` §4.2 — fail closed on security checks). Everything
else — an FTS5 index that could not be provisioned, a per-user database that does not exist
yet — degrades gracefully (§4.4): a query still runs, just with less of it available, and the
result says so rather than the call failing outright.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class SearchQueryError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class CrossUserAccessDenied(SearchQueryError):
    """A staff/owner search of another user's receipts without an active break-glass grant.

    Search reads carry the same real receipt content Logs' own operational trace does, so
    this follows the identical model, gated through Auth's own `check_access()`
    (`docs/apis/v3-deepdive-21-search-query-api.md` §4) rather than a second mechanism
    invented here.
    """


class GroupAccessDenied(SearchQueryError):
    """A non-staff/owner caller with no `is_group_manager` standing over the relevant group.

    Covers both shapes §4 names: a single-target `search()` where the requester manages no
    group the target belongs to, and a `search_group()` where the requester is not that
    specific group's own manager.
    """


class AccessCheckUnavailable(SearchQueryError):
    """Auth's break-glass ledger or Groups' own manager check could not be evaluated.

    Treated as denial, never as permission (`docs/PRINCIPLES.md` §4.2) — an unreachable
    security check means unsafe, never a silent bypass. Kept distinct from the ordinary
    denial types because an outage and a refusal call for different operator responses.
    """


class InvalidQuery(SearchQueryError):
    """A malformed request — a negative `limit`, an inverted date range, or an
    `AggregateQuery` naming both `target_user_id` and `group_id` (or neither), which
    `docs/PRINCIPLES.md` §4.3 rules out resolving by silently picking one.
    """


class FTSUnavailable(SearchQueryError):
    """`receipts_fts` could not be provisioned or opened against a given user's canonical
    database on this interpreter/SQLite build.

    Never fails the surrounding query (§4.4): structured filters still run, and
    `SearchResult.fts_degraded` reports that a supplied `query_text` could not narrow the
    answer, so a slow or unexpectedly wide result is diagnosable rather than mysterious —
    the same posture `core/logs/query.py`'s own `used_index` flag documents.
    """


#: Stable wire codes for the `.proto` surface's own `error_code` fields (§6). Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        CrossUserAccessDenied: "CROSS_USER_ACCESS_DENIED",
        GroupAccessDenied: "GROUP_ACCESS_DENIED",
        AccessCheckUnavailable: "ACCESS_CHECK_UNAVAILABLE",
        InvalidQuery: "INVALID_QUERY",
        FTSUnavailable: "FTS_UNAVAILABLE",
    }
)

#: One-line operator-facing summaries, keyed by wire code. Kept beside the codes so a caller
#: rendering an error never has to invent its own wording for a condition this API named.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "CROSS_USER_ACCESS_DENIED": (
            "no active break-glass grant covers this cross-user read"
        ),
        "GROUP_ACCESS_DENIED": (
            "the caller is not owner/staff and is not the relevant group's own manager"
        ),
        "ACCESS_CHECK_UNAVAILABLE": (
            "Auth or Groups could not be reached to evaluate this access check"
        ),
        "INVALID_QUERY": "the query was malformed",
        "FTS_UNAVAILABLE": (
            "full-text search could not run against at least one queried database; "
            "structured filters were still applied"
        ),
        "INTERNAL": "an unmapped internal error occurred",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself (the same posture `core/logs/errors.py`'s `code_for` takes).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    """The operator-facing summary for a wire code, or a generic line for an unknown one."""
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "AccessCheckUnavailable",
    "CrossUserAccessDenied",
    "FTSUnavailable",
    "GroupAccessDenied",
    "InvalidQuery",
    "SearchQueryError",
    "code_for",
    "summary_for",
]
