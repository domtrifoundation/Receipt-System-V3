# Migration API

Migration owns the **schema-version chain** — every persisted structure (config, vendor/branch data, database schema) carries a `schema_version`; this API owns the registry of N→N+1 migration steps and the logic that walks a structure from its current version to the target.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had real migrations — `migrate.py` (consolidating the split folder layout) and `sheet_migrate.py`. They were one-time, hand-written, user-confirmed scripts with no `schema_version` field anywhere, which is precisely the gap V3's chained registry closes. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-23-migration-api.md`](../../docs/apis/v3-deepdive-23-migration-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own rollback machinery separately** — migrations write through Persistence's normal path (its deep-dive §3.2), meaning every migration is automatically an atomic, Historian-logged, revertable event with no separate rollback mechanism needed here.
- **jump versions directly** — N→N+2 is always N→N+1→N+2, chained, never a shortcut migration written to skip a step, since that would mean two different code paths could produce the same end state, a real correctness risk.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

N→N+2 is always N→N+1→N+2. A shortcut migration means two code paths can produce the same end state, which is a real correctness risk, not a performance trade. V2's explicit-user-confirmation UX is deliberately not carried forward: migrations write through Persistence's normal path, so each one is already atomic and Historian-revertable.
