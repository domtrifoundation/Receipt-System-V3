"""Search/Query API data contracts (`v3-deepdive-21-search-query-api.md` §2, §4, §6, §8).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1) and is the only file other
packages import from. Every contract is `@dataclass(frozen=True)`, and every dict-typed field
is a `FrozenDict` (§2.1) — a frozen dataclass holding a plain `dict` is only *shallowly*
immutable, and `SearchResultItem.fields` crosses a process boundary the same way
`core.persistence.contracts.Receipt.fields` does. Any `isinstance` check against it must test
`collections.abc.Mapping`, never `dict` — the Python 3.15 builtin `frozendict` is not a `dict`
subclass. Module-level lookup tables would be `FrozenDict` too (§2.1.1); this module has none.

**Who is asking is never carried on the same object as what is being asked for.**
`SearchQuery`/`GroupSearchQuery`/`AggregateQuery` describe the request; `requesting_user_id`
and `requesting_role` are separate arguments threaded through `permission_gate.py` and
`structured_query.py`'s own public methods. A query object that carried its own claimed
identity would be exactly the kind of caller-asserted fact `docs/PRINCIPLES.md` §4.5 warns
against trusting — the authorization decision must never be reconstructible from data the
caller controls.

`SearchQuery` and `GroupSearchQuery` are deliberately two distinct types rather than one type
with an optional `group_id`, mirroring the deep-dive's own insistence that `search()` and
`search_group()` stay two functions rather than one that silently branches (§4) — the same
discipline applied one level down, to their inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from common.frozen_dict import FrozenDict


@dataclass(frozen=True)
class SearchQuery:
    """One single-target search request (§4, §6's `SearchRequest`).

    `target_user_id` is the subject whose receipts are wanted. `query_text` is optional
    free text matched through FTS5 (`fts_query.py`); the rest are structured filters
    `structured_query.py` applies as ordinary `WHERE` predicates over Persistence's own
    `receipts` table.
    """

    target_user_id: str
    query_text: str = ""
    vendor_name: str = ""
    date_from: datetime | None = None
    date_to: datetime | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    limit: int = 100


@dataclass(frozen=True)
class GroupSearchQuery:
    """The group-scoped equivalent (§4's `search_group()`) — every member of `group_id` at
    once, never one `target_user_id` at a time. See the module docstring for why this is its
    own type rather than an optional field on `SearchQuery`.
    """

    group_id: str
    query_text: str = ""
    vendor_name: str = ""
    date_from: datetime | None = None
    date_to: datetime | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    limit: int = 100


@dataclass(frozen=True)
class SearchResultItem:
    """One matched receipt, projected for a result list rather than a full
    `core.persistence.contracts.Receipt` — this package holds no logic and therefore no
    privilege to redefine what a receipt *is*, so `receipt_id` is the caller's own key back
    into Persistence for the canonical record. `user_id` rides along even on a group result
    so a merged, multi-member result list stays "labeled by who contributed what"
    (`core/groups/CLAUDE.md`'s own framing of what Groups exists to let a manager see).
    """

    receipt_id: str
    user_id: str
    vendor_name: str
    transaction_date: datetime | None
    total_amount: Decimal | None
    currency: str
    fields: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class SearchResult:
    """Errors are data at this boundary, never exceptions (`docs/PRINCIPLES.md` §4.1).

    `fts_degraded=True` means a `query_text` was supplied but the FTS5 index could not be
    used on at least one queried database, so structured filters still ran and `items` may
    be wider than a genuine text match would have returned — reported rather than hidden,
    the same "accelerator degrades, the answer says how" posture `core/logs/query.py`'s own
    `used_index` flag documents (`docs/PRINCIPLES.md` §4.4).
    """

    ok: bool
    items: tuple[SearchResultItem, ...] = ()
    truncated: bool = False
    fts_degraded: bool = False
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class AggregateQuery:
    """§8's resolved open question, made concrete: a real grouped/faceted query alongside
    ordinary search, sharing this API's own permission and scoping model rather than a
    second, parallel query mechanism — the deep-dive is explicit that Export Framework's own
    formal documents are genuinely different territory and this is not one of those.

    Exactly one of `target_user_id`/`group_id` must be set — both or neither is a malformed
    request (`errors.InvalidQuery`), never one silently taking precedence
    (`docs/PRINCIPLES.md` §4.3).
    """

    target_user_id: str | None = None
    group_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True)
class AggregateBucket:
    """One vendor's totals within an `AggregateResult` (§8: "total spend by vendor")."""

    vendor_name: str
    receipt_count: int
    total_amount: Decimal


@dataclass(frozen=True)
class AggregateResult:
    """Errors are data at this boundary, never exceptions (`docs/PRINCIPLES.md` §4.1)."""

    ok: bool
    buckets: tuple[AggregateBucket, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class AuthorizationResult:
    """What `permission_gate.py` hands back for `search()`, `search_group()`, and
    `aggregate()` alike — the identical "allowed, or denied with a reason" shape
    `core/groups/contracts.py`'s own `AuthorizationResult` uses, kept as its own type here
    rather than imported: Groups' own copy is that package's internal contract, not a shared
    type either package should reach across the process boundary for.
    """

    allowed: bool
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class SearchQueryMetrics:
    """An immutable snapshot of the counters `metrics.py` keeps.

    Field names are the counter names — `metrics.py` derives them from this contract so the
    two cannot drift apart, the same convention `core/logs/metrics.py` and
    `core/health/metrics.py` both already use.
    """

    searches_served: int = 0
    searches_denied: int = 0
    group_searches_served: int = 0
    group_searches_denied: int = 0
    aggregates_served: int = 0
    aggregates_denied: int = 0
    access_check_unavailable: int = 0
    fts_degradations: int = 0
    invalid_queries: int = 0


__all__ = [
    "AggregateBucket",
    "AggregateQuery",
    "AggregateResult",
    "AuthorizationResult",
    "GroupSearchQuery",
    "SearchQuery",
    "SearchQueryMetrics",
    "SearchResult",
    "SearchResultItem",
]
