# Groups

Groups owns letting an owner (or a designated group manager) organize users into teams whose receipts get automatically pooled for aggregate, labeled reporting — the real case this solves: a company self-hosting for its whole team, where employees each upload their own receipts but management wants one combined view across the team, labeled by who contributed what.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no multi-user model at all, so there was nothing to group. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-41-groups.md`](../../docs/apis/v3-deepdive-41-groups.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the actual data being aggregated** — receipts stay in each member's own Persistence database exactly as isolated as they'd otherwise be; Groups only adds a visibility grant and a tagging convention, never a shared data store.
- **replace break-glass** — see §2, a deliberately distinct third access shape, never modeled as "break-glass that never expires."
- **own the export mechanism itself** — `group_export.py` (§6) is Export Framework's own provider, reusing its existing `excel_general.py`-style technique; Groups only supplies the access rule and the data to pull.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

The other real instance behind `docs/PRINCIPLES.md` §1.8 — this was buried inside Auth's deep-dive and had to be extracted later. Groups adds a visibility grant and a tagging convention; it never creates a shared data store. Members' receipts stay in their own Persistence databases exactly as isolated as they would otherwise be, which is structural isolation doing the work rather than a permission check (§4.5). It is a genuinely distinct third access shape, not break-glass that never expires.
