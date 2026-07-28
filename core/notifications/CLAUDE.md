# Notifications/Inbox API

Notifications/Inbox owns delivering a signal to a user (owner, staff, or client) that something happened — currently in-app only, with outbound channels (email, SMS) as this deep-dive's actual design task per file 01's own framing.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `events.py` is an in-process ring buffer the dashboard renders live — not a durable, per-user, addressable inbox, and it disappears with the process. V2's uses of the word "inbox" refer to the receipts input folder, not notifications. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-09-notifications-inbox-api.md`](../../docs/apis/v3-deepdive-09-notifications-inbox-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what's worth notifying about** — every consumer (Auth's break-glass, Execution Core's run completion, Content Security's rejection, Account Guardian's export/deletion completion, **Review/Flagging's new-flag creation** — `v3-deepdive-25-review-flagging-api.md` §5, a real connection that had only ever been stated from that document's own side until a full pipeline walkthrough found it never actually listed here) decides *when* to notify; this API decides *how* the notification actually reaches the person.
- **own the underlying event** — a notification references what happened (a break-glass grant, a completed run), it doesn't duplicate that event's own record. Auth's `BreakGlassGrant`, Execution Core's run record, and so on remain the source of truth; a `Notification` carries a reference, not a copy.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

A `Notification` carries a *reference* to the underlying event, never a copy of it. Auth's `BreakGlassGrant` and Execution Core's run record stay the source of truth — duplicating their content here creates a second thing that can drift.
