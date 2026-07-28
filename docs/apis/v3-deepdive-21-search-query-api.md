# V3 Deep Dive: Search/Query API

**Companion files:** `v3-deepdive-13-persistence-api.md` (hosts the actual FTS5 tables this API queries) and `v3-deepdive-07-tool-call-api.md` (`persistence_query` wraps this API's read side).

**Status:** Twenty-first deep-dive session.

---

## 1. Scope & boundary

Search/Query owns full-text and structured search **logic** over data living in Persistence's own canonical SQLite database. It does not:
- **own the tables it queries** — FTS5 and structured search tables live directly in Persistence's database (file 01, deliberately not a separate synced copy) because a second copy would be redundant infrastructure and a real consistency risk; this API is the query layer, Persistence is the storage layer.
- **decide cross-user access policy** — staff cross-user search is break-glass-gated via the exact same mechanism Auth's `check_access()` already provides (Auth deep-dive §6.3), not a parallel permission check invented here.

---

## 2. Package layout

```
core/search_query/
  __init__.py
  contracts.py           # SearchQuery, SearchResult, error types
  fts_query.py               # FTS5 full-text query construction
  structured_query.py          # filtered/faceted queries (date range, amount range, vendor)
  permission_gate.py             # break-glass check for cross-user search
  errors.py
  metrics.py
```

---

## 3. FTS5 — full-text OCR search, included from v1
Not deferred, per file 01's explicit statement. `CREATE VIRTUAL TABLE receipts_fts USING fts5(...)` living in Persistence's own database (its deep-dive §3), populated at write time as part of the same transaction that writes the receipt's own row — meaning a receipt is searchable the instant it's written, never lagging behind via a separate reindex step. Query construction uses FTS5's own `MATCH` syntax with proper escaping of user input (a real injection surface if user-supplied query text is ever concatenated into an FTS5 query string directly rather than passed as a bound parameter) — worth stating explicitly as a security requirement, not just a correctness one.

---

## 4. Structured queries and the permission gate — now with a third access-control shape
```python
async def search(query: SearchQuery, requesting_user_id: str, requesting_role: Role) -> tuple[SearchResult, ...]:
    if query.target_user_id != requesting_user_id:
        if requesting_role in (Role.STAFF, Role.OWNER):
            if not await auth.check_access(requesting_user_id, query.target_user_id):
                raise PermissionError()   # no active break-glass grant
        elif not await auth.is_group_manager_for(requesting_user_id, query.target_user_id):
            raise PermissionError()       # neither staff-with-break-glass nor a group manager over this specific target
    return await _execute(query)

async def search_group(query: GroupSearchQuery, requesting_user_id: str, requesting_role: Role) -> tuple[SearchResult, ...]:
    """The group-scoped equivalent — queries every member of query.group_id
    at once, not one target_user_id at a time. Gated by Auth's own
    is_group_manager_for-the-whole-group check (Groups' own deep-dive §4.1), or
    staff/owner's existing system-wide privileges — never both paths
    merged into one function, since the single-target and whole-group
    cases have genuinely different permission shapes worth keeping
    visibly distinct rather than one function silently branching."""
    if requesting_role not in (Role.STAFF, Role.OWNER):
        if not await auth.is_group_manager_for_group(requesting_user_id, query.group_id):
            raise PermissionError()
    return await _execute_group(query)
```
Every cross-user query re-checks break-glass status at query time, not once at session start — a grant expiring mid-session correctly blocks a subsequent query without needing the session itself to be revoked, consistent with Auth's own "expiry enforced at check-time, not by a sweep" design (its deep-dive §6.3). **Group access is checked the same way — at query time, against Groups' own live membership/manager state — never cached or assumed stable across a session**, the same discipline applied to a third, structurally different access shape (Groups' own deep-dive §2's own point about not conflating group visibility with break-glass): persistent and structural doesn't mean "never re-checked," it means "no expiry timer," a real distinction worth preserving in the enforcement code, not just the prose describing it.

---

## 5. Asyncio
SQLite FTS5 queries are the same async-wrapped blocking-I/O pattern as every other SQLite consumer in this batch (Auth, Audit, Persistence itself) — file 02's own table already classifies this API as async for exactly this reason.

---

## 6. gRPC surface

```protobuf
service SearchQueryService {
  rpc Search(SearchRequest) returns (SearchResponse);
}

message SearchRequest {
  string query_text = 1;
  string target_user_id = 2;
  string date_from = 3;
  string date_to = 4;
  float amount_min = 5;
  float amount_max = 6;
}
```

---

## 7. Testing hooks
- **FTS5 injection test**: confirms user-supplied query text with FTS5 special characters (`"`, `*`, boolean operators) is properly escaped/bound, never string-concatenated into the query.
- **Break-glass expiry mid-session test**: a search query issued after a grant expires mid-session correctly fails, validating §4's query-time (not session-time) check.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- (Faceted/aggregate query needs — resolved, no longer open. This API owns it, not Export Framework: a "total spend by vendor this quarter" query is the same kind of operation as a search — read-only, ranked/filtered results — just with grouping/aggregation added, not a fundamentally different capability. Export Framework's own `slsp_summary.py` and similar providers stay genuinely different territory — formal, downloadable documents for a specific compliance/business purpose, not ad hoc in-app querying. A real `AggregateQuery` RPC belongs alongside this API's existing search surface, sharing the same permission/scoping model rather than a second, parallel query mechanism.)
