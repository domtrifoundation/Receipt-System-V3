# Support Ticketing API

Support Ticketing owns a real ticket lifecycle — a user or staff member opens a ticket, staff responds, it resolves — genuinely in-app, not a wrapper around an external tool.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new — surfaced when a sweep found Auth's break-glass `reason` field had referenced "a support ticket ref" all along without anything ever building one. No V1 or V2 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-52-support-ticketing.md`](../../docs/apis/v3-deepdive-52-support-ticketing.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own notification delivery** — a new ticket message triggers a Notifications API entry (its deep-dive) the same way any other in-app event does; this API owns ticket state and conversation content, not how a user gets told about it.
- **replace break-glass's own reason field** — break-glass (`v3-deepdive-05-auth-tenancy-api.md` §6) still just takes a free-text reason; this API gives that reason field somewhere real to *point at* when the underlying context is a genuine support interaction, but doesn't require every break-glass grant to have a formal ticket behind it.
- **handle account-recovery case intake** — Account Guardian's own `account_recovery.py` (its deep-dive §5) already owns that specific, higher-stakes staff-mediated queue; a garden-variety support question ("why was my receipt flagged") is this API's job, an identity-verification case is Account Guardian's.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Deliberately simple: open → in progress → resolved → closed, with no routing or SLA machinery, because this project's actual scale does not need it. An identity-verification case is Account Guardian's queue, not this one — the distinction is the stakes, not the format. **Treat the size of `assignment.py` as the design, not as something unfinished** — §4 and §9 both argue explicitly against priority tiers and SLA tracking, and `STAFF_ROLES`/`REASSIGN_ROLES` are asserted as data in the tests so adding one has to break a test naming that reasoning.

**The one routing rule with real teeth is reassignment.** A staff member may take an unassigned
ticket or one they already hold; taking a ticket out of a colleague's hands is an owner action.
Without that line, §4's "any staff member can self-assign" silently means "any staff member can
un-assign anyone", and a thread could be pulled away mid-conversation. Review/Flagging resolves
the structurally identical question the same way (its §8 cites this document by name) — one
routing philosophy across both staff queues, deliberately, rather than two.

**`RESOLVED` and `CLOSED` are separate states because §9's auto-close window lives between
them.** Resolved means staff believe they are done and the user has fourteen days to say
otherwise; closed means that window passed. Only `RESOLVED` tickets auto-close — sweeping from
`OPEN` would shut tickets nobody ever answered, which is the opposite of a convenience and
exactly the behaviour that makes users stop filing them. `_replace` always refreshes
`updated_at`, so a reply on day 13 restarts the window; a path that changed a ticket without
touching that timestamp would close a thread someone just replied to.

**A ticket id carries the `TKT-` prefix, and that is load-bearing rather than cosmetic.** §8's
break-glass hook needs a grant's free-text `reason` to resolve to a real ticket, which is only
possible if an id is findable *inside prose* — a bare UUID in a sentence is not. And the link is
a resolution, never a requirement: §1 forbids making a formal ticket mandatory for a grant, so a
reason naming nothing returns `None` and no grant is ever refused for it.

**That softness is why §8 asks for a regression test at all.** If ticket ids stopped being
extractable, every break-glass grant would keep working exactly as before and the reference
would quietly resolve to nothing. Nothing would fail. `break_glass_refs_resolved` against
`break_glass_refs_unresolvable` is the only signal that would move.

**A denied conversation read raises rather than returning an empty list.** An empty thread and a
forbidden one are different facts, and returning `()` for both would let a caller render "no
messages yet" for someone else's ticket — which looks like a working feature and is a disclosure
that the ticket exists. Support conversations quote receipt details, amounts and vendor names, so
a ticket is per-user data in the same sense a receipt is.

**A client's listing is narrowed rather than refused.** A user asking for "all tickets" obviously
means their own, and an error for a request with an obvious correct answer is just confusing.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `metrics.py` — §2's layout predates the counter convention every other package in this repo
  follows. The counters exist for one specific reason beyond housekeeping: the break-glass
  resolution ratio above is the only observable that would reveal that soft link silently
  breaking.

**Known gap, flagged rather than silently filled**: §7 specifies a five-RPC surface and there is
no `.proto` here yet, and `TicketStore` holds tickets in memory rather than in its own SQLite
store — §6 calls this API "thin CRUD over its own small database", and that persistence adapter
is a later wiring step. Every behaviour above is implemented and tested against the in-memory
store, and swapping in persistence means changing where `_tickets`/`_messages` live, not the
lifecycle around them. This joins the same open `.proto` question `core/tool_call/CLAUDE.md`,
`core/background_workers/CLAUDE.md` and `core/migration/CLAUDE.md` record.
