# Tunnel Exposure

**Sub-API of Gateway API** (`services/gateway/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Tunnel Exposure owns getting Gateway reachable from the public internet without the operator opening inbound firewall ports — for a self-hosted install specifically; DOMTRI's own hosted service has its own existing production ingress and doesn't use this sub-API's own provider selection at all.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no public-exposure mechanism of any kind — no tunnel, no reverse proxy, no ingress. It was a local program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-43-tunnel-exposure.md`](../../../docs/apis/v3-deepdive-43-tunnel-exposure.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **cover every use of Cloudflare's platform in this project** — this sub-API is specifically about network exposure (the tunnel); the Webapp Assistant (`v3-deepdive-54-webapp-assistant.md`) separately uses Cloudflare Workers AI and a Cloudflare Worker for a genuinely different purpose (a chat backend), not this sub-API's own concern and not built on top of it.
- **replace Gateway's own defense-in-depth** — Gateway's rate limiting and request validation (its deep-dive §7) stay in place regardless of which tunnel provider is active; the tunnel is network-edge exposure, not the whole security posture.
- **own DNS beyond what a given provider's own setup requires** — Cloudflare Tunnel's own CNAME record creation is part of *that* provider's own config flow, not a generic DNS-management capability this sub-API offers independently of the active provider.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

Scoped to self-hosted installs specifically; DOMTRI's hosted service has its own production ingress and does not use this provider selection at all. Not every use of Cloudflare in this project runs through here — the Webapp Assistant separately uses Workers AI for an unrelated purpose. The tunnel is network-edge exposure, never a substitute for Gateway's own rate limiting and validation.
