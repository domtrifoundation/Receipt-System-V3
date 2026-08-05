# Search/Query API

Search/Query owns full-text and structured search **logic** over data living in Persistence's own canonical SQLite database.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's only search was over menu items (`menu_system.begin_search`, `menus.search`) — that capability is Interface's `find_setting`, not this API. No full-text or structured search over receipt data existed. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-21-search-query-api.md`](../../docs/apis/v3-deepdive-21-search-query-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the tables it queries** — FTS5 and structured search tables live directly in Persistence's database (file 01, deliberately not a separate synced copy) because a second copy would be redundant infrastructure and a real consistency risk; this API is the query layer, Persistence is the storage layer.
- **decide cross-user access policy** — staff cross-user search is break-glass-gated via the exact same mechanism Auth's `check_access()` already provides (Auth deep-dive §6.3), not a parallel permission check invented here.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

The FTS5 and structured tables live *inside* Persistence's own canonical database, not a separate synced copy — a second copy would be redundant infrastructure and a real consistency risk. Staff cross-user search is break-glass-gated through Auth's existing `check_access()`, never a parallel permission check invented here.
