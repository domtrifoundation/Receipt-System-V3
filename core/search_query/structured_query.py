"""Filtered/faceted query execution — date range, amount range, vendor, and the FTS5 text
filter combined (`v3-deepdive-21-search-query-api.md` §4, §5, §8).

`SearchExecutor` is this API's real entry point: `search()`, `search_group()`, and
`aggregate()` are the deep-dive's own §4 functions, given a home here rather than in
`service.py` because a future non-Python client, an in-process caller, and the gRPC servicer
must all get identical behaviour rather than three implementations that could drift — the
same reasoning `core/logs/service.py` and `core/groups/service.py` both state for keeping
their own servicers thin.

**Group-scoped search is genuinely one connection per member, fanned out and merged in
Python, never one SQL query with `user_id IN (...)`** — `db.py`'s own docstring explains why:
each user's receipts live in their own physically separate canonical database. Fetching each
member's own top-`limit` rows before merging is sufficient for a correct global top-`limit`:
any receipt that belongs in the merged top-`limit` is necessarily within its own owner's
top-`limit` when ranked among just that owner's receipts, since at most `limit - 1` other
receipts (across every member combined) can rank above it globally, and therefore at most
that many can belong to the same owner.

**Errors are data at this boundary, never exceptions** (`docs/PRINCIPLES.md` §4.1). Every
public method returns a `SearchResult`/`AggregateResult` carrying `error_code`/`error_detail`;
`AccessCheckUnavailable` raised by the permission gate's own checkers is caught there, not
here — this module only ever sees an already-resolved `AuthorizationResult`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role

from .contracts import (
    AggregateBucket,
    AggregateQuery,
    AggregateResult,
    GroupSearchQuery,
    SearchQuery,
    SearchResult,
    SearchResultItem,
)
from .db import ReceiptDatabaseRegistry
from .errors import InvalidQuery, code_for
from .fts_query import text_match_clause
from .metrics import SearchQueryMetricsCollector
from .permission_gate import SearchPermissionGate


@runtime_checkable
class GroupMembersLookup(Protocol):
    """The adapter seam onto Groups' own membership roster (`docs/PRINCIPLES.md` §1.3).

    Deliberately not an import of `core.groups`: this package holds no opinion about
    membership beyond "which user ids does a group-scoped search fan out to."
    """

    async def members_of(self, group_id: str) -> tuple[str, ...]:
        """Every member's `user_id`, in any order. Empty for an unknown or empty group —
        never an error; a group with no members is a real, valid state (§4.4)."""


class DenyAllGroupMembers:
    """The fail-closed default: with no Groups client wired up, a group-scoped search fans
    out to nobody rather than guessing membership, the correct behaviour rather than a
    degraded one."""

    async def members_of(self, group_id: str) -> tuple[str, ...]:
        return ()


class GroupsMembersAdapter:
    """The production wiring onto `core.groups.membership.GroupMembershipService`.

    Membership enumeration is a data lookup, not an authorization decision — `search_group()`
    has already been authorized by `permission_gate.py`'s own live `is_group_manager` check
    by the time this runs, so this adapter answers "who is in the group", nothing more.
    """

    def __init__(self, membership) -> None:
        self._membership = membership

    async def members_of(self, group_id: str) -> tuple[str, ...]:
        try:
            result = await self._membership.list_members(group_id)
        except Exception:  # noqa: BLE001 - an unreachable Groups fans out to nobody
            return ()
        if not result.ok:
            return ()
        return tuple(m.user_id for m in result.members)


def _sort_key(item: SearchResultItem) -> tuple[datetime, str]:
    """Newest first, `None` sorting as oldest. Naive stored timestamps are treated as UTC for
    comparison purposes only — never rewritten — so a merged, multi-database result list
    never raises `TypeError` mixing naive and aware datetimes (the same normalization
    `core/logs/contracts.py`'s own `as_utc` documents for an identical reason)."""
    dt = item.transaction_date
    if dt is None:
        dt = datetime.min.replace(tzinfo=timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return (dt, item.receipt_id)


def _validate_range(
    limit: int, date_from: datetime | None, date_to: datetime | None
) -> InvalidQuery | None:
    if limit < 0:
        return InvalidQuery("limit must not be negative")
    if date_from is not None and date_to is not None and date_from > date_to:
        return InvalidQuery("date_from must not be after date_to")
    return None


def _row_to_item(row: sqlite3.Row) -> SearchResultItem:
    total_amount = row["total_amount"]
    try:
        amount = Decimal(total_amount) if total_amount not in (None, "") else None
    except InvalidOperation:
        amount = None
    fields_json = row["fields_json"]
    return SearchResultItem(
        receipt_id=row["receipt_id"],
        user_id=row["user_id"],
        vendor_name=row["vendor_name"] or "",
        transaction_date=(
            datetime.fromisoformat(row["transaction_date"])
            if row["transaction_date"]
            else None
        ),
        total_amount=amount,
        currency=row["currency"] or "PHP",
        fields=FrozenDict(json.loads(fields_json)) if fields_json else FrozenDict({}),
    )


def _build_where(
    query: SearchQuery | GroupSearchQuery, *, include_fts: bool
) -> tuple[str, list[Any]]:
    """The structured `WHERE` predicate. Every value is a bound parameter — `query_text`
    included, via `fts_query.text_match_clause` — never string-concatenated into the SQL
    text (`docs/apis/v3-deepdive-21-search-query-api.md` §3, §7).
    """
    clauses = ["1 = 1"]
    params: list[Any] = []
    if query.vendor_name:
        clauses.append("vendor_name LIKE ?")
        params.append(f"%{query.vendor_name}%")
    if query.date_from is not None:
        clauses.append("transaction_date >= ?")
        params.append(query.date_from.isoformat())
    if query.date_to is not None:
        clauses.append("transaction_date <= ?")
        params.append(query.date_to.isoformat())
    if query.amount_min is not None:
        clauses.append("total_amount IS NOT NULL AND CAST(total_amount AS REAL) >= ?")
        params.append(float(query.amount_min))
    if query.amount_max is not None:
        clauses.append("total_amount IS NOT NULL AND CAST(total_amount AS REAL) <= ?")
        params.append(float(query.amount_max))
    if include_fts:
        text_clause = text_match_clause(query.query_text)
        if text_clause is not None:
            clause_sql, param = text_clause
            clauses.append(clause_sql)
            params.append(param)
    return " AND ".join(clauses), params


class SearchExecutor:
    """Owns permission-gated read access over Persistence's per-user canonical databases.
    One instance per Search/Query process."""

    def __init__(
        self,
        *,
        registry: ReceiptDatabaseRegistry | None = None,
        gate: SearchPermissionGate | None = None,
        members: GroupMembersLookup | None = None,
        metrics: SearchQueryMetricsCollector | None = None,
    ) -> None:
        self._registry = registry or ReceiptDatabaseRegistry()
        self._gate = gate or SearchPermissionGate()
        self._members: GroupMembersLookup = members or DenyAllGroupMembers()
        self._metrics = metrics or SearchQueryMetricsCollector()

    @property
    def metrics(self) -> SearchQueryMetricsCollector:
        return self._metrics

    # ------------------------------------------------------------------ single-target
    async def search(
        self, query: SearchQuery, *, requesting_user_id: str, requesting_role: Role
    ) -> SearchResult:
        invalid = _validate_range(query.limit, query.date_from, query.date_to)
        if invalid is not None:
            self._metrics.increment("invalid_queries")
            return SearchResult(ok=False, error_code=code_for(invalid), error_detail=str(invalid))

        auth = await self._gate.authorize_search(
            query.target_user_id, requesting_user_id, requesting_role
        )
        if not auth.allowed:
            self._metrics.increment("searches_denied")
            return SearchResult(
                ok=False, error_code=auth.error_code, error_detail=auth.error_detail
            )

        items, degraded = await self._search_one_user(query.target_user_id, query)
        self._metrics.increment("searches_served")
        truncated = len(items) > query.limit
        return SearchResult(
            ok=True, items=tuple(items[: query.limit]), truncated=truncated,
            fts_degraded=degraded,
        )

    # -------------------------------------------------------------------- group-scoped
    async def search_group(
        self, query: GroupSearchQuery, *, requesting_user_id: str, requesting_role: Role
    ) -> SearchResult:
        invalid = _validate_range(query.limit, query.date_from, query.date_to)
        if invalid is not None:
            self._metrics.increment("invalid_queries")
            return SearchResult(ok=False, error_code=code_for(invalid), error_detail=str(invalid))

        auth = await self._gate.authorize_group_search(
            query.group_id, requesting_user_id, requesting_role
        )
        if not auth.allowed:
            self._metrics.increment("group_searches_denied")
            return SearchResult(
                ok=False, error_code=auth.error_code, error_detail=auth.error_detail
            )

        member_ids = await self._members.members_of(query.group_id)
        single = SearchQuery(
            target_user_id="", query_text=query.query_text, vendor_name=query.vendor_name,
            date_from=query.date_from, date_to=query.date_to, amount_min=query.amount_min,
            amount_max=query.amount_max, limit=query.limit,
        )
        merged: list[SearchResultItem] = []
        degraded_any = False
        for member_id in member_ids:
            items, degraded = await self._search_one_user(member_id, single)
            merged.extend(items)
            degraded_any = degraded_any or degraded
        merged.sort(key=_sort_key, reverse=True)

        self._metrics.increment("group_searches_served")
        truncated = len(merged) > query.limit
        return SearchResult(
            ok=True, items=tuple(merged[: query.limit]), truncated=truncated,
            fts_degraded=degraded_any,
        )

    # ------------------------------------------------------------------------ aggregate
    async def aggregate(
        self, query: AggregateQuery, *, requesting_user_id: str, requesting_role: Role
    ) -> AggregateResult:
        if (query.target_user_id is None) == (query.group_id is None):
            exc = InvalidQuery(
                "exactly one of target_user_id/group_id must be set on an AggregateQuery"
            )
            self._metrics.increment("invalid_queries")
            return AggregateResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        auth = await self._gate.authorize_aggregate(
            target_user_id=query.target_user_id, group_id=query.group_id,
            requesting_user_id=requesting_user_id, requesting_role=requesting_role,
        )
        if not auth.allowed:
            self._metrics.increment("aggregates_denied")
            return AggregateResult(
                ok=False, error_code=auth.error_code, error_detail=auth.error_detail
            )

        if query.group_id is not None:
            member_ids = await self._members.members_of(query.group_id)
        else:
            member_ids = (query.target_user_id or "",)

        totals: dict[str, list[Any]] = {}
        for member_id in member_ids:
            rows = await self._registry.run(
                member_id, lambda conn: self._aggregate_rows_sync(conn, query)
            )
            if rows is None:
                continue
            for row in rows:
                vendor = row["vendor_name"] or "(unknown)"
                try:
                    amount = Decimal(row["total_amount"]) if row["total_amount"] else Decimal(0)
                except InvalidOperation:
                    amount = Decimal(0)
                bucket = totals.setdefault(vendor, [0, Decimal(0)])
                bucket[0] += 1
                bucket[1] += amount

        buckets = tuple(
            AggregateBucket(vendor_name=vendor, receipt_count=count, total_amount=total)
            for vendor, (count, total) in sorted(
                totals.items(), key=lambda kv: kv[1][1], reverse=True
            )
        )
        self._metrics.increment("aggregates_served")
        return AggregateResult(ok=True, buckets=buckets)

    # ------------------------------------------------------------------------- internals
    async def _search_one_user(
        self, user_id: str, query: SearchQuery
    ) -> tuple[list[SearchResultItem], bool]:
        def _read(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], bool]:
            fts_ok = self._registry.fts_available(user_id)
            where, params = _build_where(query, include_fts=fts_ok)
            limit = max(query.limit, 0) + 1
            sql = (
                f"SELECT * FROM receipts WHERE {where} "
                "ORDER BY transaction_date DESC, receipt_id DESC LIMIT ?"
            )
            rows = conn.execute(sql, [*params, limit]).fetchall()
            return rows, fts_ok

        result = await self._registry.run(user_id, _read)
        if result is None:
            return [], False
        rows, fts_ok = result
        degraded = bool(query.query_text.strip()) and not fts_ok
        return [_row_to_item(r) for r in rows], degraded

    def _aggregate_rows_sync(
        self, conn: sqlite3.Connection, query: AggregateQuery
    ) -> list[sqlite3.Row]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if query.date_from is not None:
            clauses.append("transaction_date >= ?")
            params.append(query.date_from.isoformat())
        if query.date_to is not None:
            clauses.append("transaction_date <= ?")
            params.append(query.date_to.isoformat())
        sql = f"SELECT vendor_name, total_amount FROM receipts WHERE {' AND '.join(clauses)}"
        return conn.execute(sql, params).fetchall()


__all__ = [
    "DenyAllGroupMembers",
    "GroupMembersLookup",
    "GroupsMembersAdapter",
    "SearchExecutor",
]
