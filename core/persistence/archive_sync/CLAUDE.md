# Archive Sync

**Sub-API of Persistence API** (`core/persistence/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Archive Sync owns **one-way mirroring** of a user's processed/archived receipts out to an external drive provider.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had both halves — `archiver.py` filed processed receipts into vendor-named folders and `google_drive.py` carried an upload path. V1 archived locally only (flat or per-vendor), which is Persistence's archival concern rather than an outbound mirror, so V1 is not this sub-API's ancestor. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-32-archive-sync.md`](../../../docs/apis/v3-deepdive-32-archive-sync.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **serve as the default browsing experience** — the webapp's "My Files" screen (Interface API, built on Search/Query + Persistence) is that; Archive Sync is strictly additional for users who specifically want their archive visible in their own external Drive too.
- **become a second source of truth** — the external copy is a convenience mirror; if it's ever missing, deleted externally, or out of sync, Persistence's own blob store remains authoritative, full stop.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

One-way, always. The external copy is a convenience mirror — if it is deleted or edited externally, Persistence's blob store is still authoritative, full stop. V2 sorted blobs into vendor-named folders and that is exactly what V3 does not do: two workers correcting vendor identity from different evidence would fight forever over folder placement, which is why storage is content-addressed and foldering is a presentation concern only.
