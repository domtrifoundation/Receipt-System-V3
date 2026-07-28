# Status Page API

Status Page owns a public, unauthenticated page showing the hosted service's own uptime and incident history — for DOMTRI's hosted multi-tenant service specifically; a self-hosted install has no public audience to show this to and doesn't run this API at all (the same "doesn't apply to self-hosted, skip it" pattern Gateway itself already established for a different reason, `v3-deepdive-19-gateway-api.md` §1).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new — surfaced as a blind spot during a corpus-wide sweep. No V1 or V2 equivalent; neither generation had a hosted service to publish status for. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-51-status-page.md`](../../docs/apis/v3-deepdive-51-status-page.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **expose anything Health API's own live-diagnostic layer wouldn't already share internally** — this is a *public, summarized* republishing of a subset of already-existing health signals, never a second, independent monitoring system with its own opinion about what's healthy.
- **replace the internal Fleet screen** — Fleet (`v3-deepdive-14-interface-api.md` §3.3) is owner/staff-facing, per-service, real-time, and detailed; this is public-facing, aggregated, and deliberately coarse (a customer doesn't need or want to know which of 28 internal services is degraded, only whether *the product* is working).
- **auto-detect and publish incidents** — an incident entry is a deliberate, staff-authored action (§4), never an automatic consequence of a health check flipping red, since a transient blip that self-resolves in ten seconds shouldn't become a public incident record just because it crossed a threshold for a moment.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

Infrastructurally independent on purpose — it has to stay reachable when the main product is not, which is why it keeps its own small local cache and can render a last-known state even if the core gRPC fleet is genuinely unreachable. Incidents are staff-authored, never auto-generated from a health check flipping red. Public component groups are deliberately coarse and never leak internal API names.
