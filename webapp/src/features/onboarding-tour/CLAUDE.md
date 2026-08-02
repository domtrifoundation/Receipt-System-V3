# Guided Onboarding Tour

**Sub-API of Webapp** (`webapp/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

This document owns the first-time guided tour experience — step sequencing, animation, sound, skip/resume/replay behavior.

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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-53-guided-onboarding-tour.md`](../../../../docs/apis/v3-deepdive-53-guided-onboarding-tour.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own tour content authorship** — which steps exist and what they say is product content, not a technical design question this document resolves; the *mechanism* for defining and playing a sequence of steps is what's designed here.
- **own the shared overlay/spotlight component itself** — the underlying "highlight this element, show a callout" primitive lives in the Design System (`v3-deepdive-45-design-system.md`), since it's genuinely reusable beyond first-time onboarding (a future feature announcement tour could reuse it); this document owns the *tour-specific* orchestration built on top of that primitive.

## Forward-Compatibility Pattern applicability

Not applicable — TypeScript/React. See `webapp/CLAUDE.md`.

## Real gotchas specific to this folder

Which steps exist and what they say is product content, not a technical question this folder resolves — what is designed here is the mechanism for defining and playing a sequence.
