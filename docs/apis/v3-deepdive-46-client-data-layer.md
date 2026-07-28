# V3 Deep Dive: Client Data Layer (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` §6 (the section this document expands and replaces the brief version of).

**Companion files:** `v3-deepdive-19-gateway-api.md` §12 (the WebSocket reconnection/backoff open question this document resolves the client-side half of), `v3-deepdive-10-execution-core-api.md` (the streaming `GetRunStatus` RPC this layer's real-time integration is built around), `v3-deepdive-29-historian.md` §6 (the narrative-track query this layer serves to the Receipt Detail screen).

**Status:** New dedicated document, extracted per `docs/PRINCIPLES.md` §1.8's threshold — its own real interface (typed query/mutation hooks), consumed by every screen in the application, and the direct owner of a real, previously-unresolved cross-document open question.

---

## 1. Scope & boundary

The Client Data Layer owns everything between a screen component and Gateway's own REST/WebSocket surface — typed query hooks, caching, streaming consumption, and reconnection behavior. It does not:
- **own the gRPC-Web client generation itself** — `lib/grpc-web-client.ts` (the webapp's own package layout, `v3-deepdive-44-webapp.md` §2) is generated tooling from each API's `.proto` definitions; this document owns how that generated client gets *used*, not how it's produced.
- **duplicate server-side validation or business logic** — a query hook fetches and caches; it never re-implements a check the API layer already performs.

---

## 2. Package layout

```
webapp/src/queries/
  files.ts                    # My Files — wraps Search/Query's own REST surface
  receipts.ts                    # receipt detail + Historian narrative — see §4
  runs.ts                          # streaming run status — see §3
  logs.ts                            # streaming log tail, ATTENTION-level aware
  groups.ts
  vendors.ts                           # temporal_learning's own entity CRUD
  mutations/
    __init__.ts
    schedule-tasks.ts
    reimport.ts
```

---

## 3. Streaming integration — the actual answer to Gateway's own open question
**Gateway's own deep-dive (§12) flagged WebSocket reconnection/backoff policy as a real, undesigned UX detail — this is the client-side half of that answer, previously missing entirely.** TanStack Query's own architecture wasn't built primarily for streaming data, so this needs a real, deliberate pattern rather than assuming the library handles it automatically:
```typescript
// queries/runs.ts — sketch
function useRunStatus(runId: string) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => subscribeToRunStatus(runId),   // opens the WebSocket, feeds incoming
                                                       // messages into the query cache via
                                                       // queryClient.setQueryData, not a
                                                       // one-shot fetch
    staleTime: Infinity,   // the WebSocket itself is the source of truth once connected;
                              // TanStack Query's own refetch-on-stale logic would fight it
  });
}
```
**Reconnection policy, resolved here**: exponential backoff (starting at 1s, capped at 30s) on an unexpected socket close, with a visible-but-unobtrusive UI state (§3.1) — never a silent, invisible retry loop the person watching a live run has no way to know is happening. On reconnect, the hook re-subscribes and Execution Core's own `GetRunStatus` RPC returns full current state (not just a delta), so a missed message during the gap self-heals on the next successful message rather than needing its own gap-filling logic.

### 3.1 What the screen actually shows during a reconnect attempt
A small, persistent status indicator (not a full-screen error, not a silent nothing) — "Reconnecting…" during backoff, reverting to normal the moment a message arrives. This is the concrete UX answer to Gateway's own "what does a screen actually show mid-reconnect" open question (its deep-dive §12) — resolved here rather than left open a second time.

---

## 4. Historian narrative consumption — powering the Receipt Detail screen
```typescript
function useReceiptHistory(receiptId: string) {
  return useQuery({
    queryKey: ['receipt-history', receiptId],
    queryFn: () => fetchReceiptHistory(receiptId),   // Persistence's GetReceiptHistory RPC,
                                                          // v3-deepdive-13-persistence-api.md §6
  });
}
```
Returns the interleaved data-change/narrative timeline directly as Persistence's own `get_receipt_history()` already produces it (its deep-dive §6) — this layer doesn't re-sort or re-merge the two tracks, since that work is already done server-side; it's a thin typed wrapper, not a second implementation of the interleaving logic. Full rendering detail lives in `v3-deepdive-48-receipt-detail-screen.md`.

---

## 5. Caching and invalidation conventions
A consistent query-key structure across every domain (`['files', userId]`, `['receipt', receiptId]`, `['groups', groupId]`) so a mutation's own invalidation target is always predictable — a group-membership change invalidates `['groups', groupId]` and nothing else, never an overly broad cache-clear that causes every unrelated screen to refetch. Optimistic updates (a mutation immediately updates the local cache before the server confirms) are used only where a failed mutation's rollback is simple and the UX benefit is real — Task Scheduler's own enable/disable toggle is a good fit; anything touching Groups' own access-control state deliberately isn't, since a UI showing access that hasn't actually been granted yet is a worse failure mode than a half-second of latency.

---

## 6. Asyncio/concurrency — not applicable in the Python sense, same as the parent document
Browser-side JavaScript/TypeScript, no Python interpreter concerns. The real concurrency-adjacent design here is request deduplication (TanStack Query's own built-in behavior — two components requesting the same query key in the same render cycle share one network call, not two) — a library-provided behavior, not something this document needs to design.

---

## 7. Testing hooks
- **Reconnection backoff test**: confirms a simulated socket drop triggers the exact backoff curve specified in §3, not an immediate retry storm.
- **Cache-invalidation scope test**: confirms a mutation only invalidates its own declared query keys, catching an overly broad invalidation before it ships as an unnecessary refetch storm.
- **Historian interleaving passthrough test**: confirms this layer doesn't silently re-sort or drop entries from Persistence's own already-ordered response.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **Offline queueing, resolved: queue for retry, with a visible pending-sync indicator.** Better UX than failing outright — a mutation attempted while genuinely offline queues locally and syncs once connectivity returns, shown as a clear "pending" state so the person knows their action hasn't silently vanished. Applies only to mutations; reads have nothing to queue, they simply refetch on reconnect.
- **Optimistic-update scope, resolved with real named candidates.** Beyond Task Scheduler's own enable/disable toggle (§5's original example): notification read/unread status, and any settings toggle that doesn't touch access-control state — the same exclusion already stated for anything Groups-related stays in force, since a UI showing access that hasn't actually been granted yet remains a worse failure mode than a half-second of latency.
