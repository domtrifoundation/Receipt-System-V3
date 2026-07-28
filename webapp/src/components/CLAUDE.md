# Design System

**Sub-API of Webapp** (`webapp/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

The Design System owns every reusable visual building block the webapp's screens are composed from — form controls, data tables, the diff viewer, layout primitives, theming.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new, alongside the webapp itself. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-45-design-system.md`](../../../docs/apis/v3-deepdive-45-design-system.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own screen-level composition or business logic** — a component here renders what it's given and emits events for what a user does; deciding what data to fetch or what an action means belongs to the screen that uses it, never to the component itself.
- **own routing or data fetching** — components receive data as props (or, for data-aware components, a typed query hook from the Client Data Layer, `v3-deepdive-46-client-data-layer.md`); they don't reach out and fetch their own data.

## Forward-Compatibility Pattern applicability

Not applicable — TypeScript/React. See `webapp/CLAUDE.md`.

## Real gotchas specific to this folder

A component renders what it is given and emits events; it never fetches its own data. The overlay/spotlight primitive lives here rather than in the onboarding tour precisely because it is reusable beyond first-time onboarding.
