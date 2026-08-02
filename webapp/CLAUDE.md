# Webapp

The Webapp owns the browser-side application itself — routing, page/screen composition, component architecture, and how it consumes Gateway's REST/WebSocket surface.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. Neither V1 nor V2 had a browser surface — V1 ran as a conversational skill, V2 as a terminal dashboard. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-44-webapp.md`](../docs/apis/v3-deepdive-44-webapp.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own how it gets served** — that's Gateway's own build-and-serve mechanism (its deep-dive §4); this document owns what gets built, not how the right version reaches the right user.
- **own how the deployment gets reached from the public internet** — Tunnel Exposure (`v3-deepdive-43-tunnel-exposure.md`) is a separate concern this application doesn't need to know anything about.
- **contain business logic** — every screen is a thin presentation layer over Gateway's own REST/WebSocket translation of the gRPC core; a validation rule, a permission check, a computed value all live at the API layer the webapp calls, never duplicated in frontend code as a second source of truth.
- **decide state-management or framework choices** — already resolved in Interface API's own deep-dive (§4): React, TypeScript, Zustand for client state, TanStack Query for server state. This document builds on those decisions, doesn't re-litigate them.

## Forward-Compatibility Pattern applicability

Not applicable — this is a TypeScript/React tree, not Python. The Forward-Compatibility Pattern (`docs/PRINCIPLES.md` §3.3) governs the Python interpreter and Python dependencies; this folder's own forward-compatibility concerns are its npm dependency set, tracked separately by Dependencies Warden.

## Real gotchas specific to this folder

Runs on the end user's own machine, in their browser — Layer 3 in `docs/PROCESS_TOPOLOGY.md`, genuinely not a process this system manages. It never talks to a Core API directly; Gateway is the only bridge. No business logic here, ever: a validation rule or permission check duplicated in frontend code is a second source of truth, and the server-side one is the real boundary regardless.
