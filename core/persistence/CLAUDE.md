# Persistence API

Persistence owns **all disk access** — nothing else in this system touches disk directly. Two storage mechanisms: a canonical per-user SQLite database (structured records, WAL mode) and a content-addressable blob store (raw/archival images).

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 stored transactions directly in an Excel workbook and archived images into flat or per-vendor folders. V2 kept that shape and added real machinery around it (`excel_writer.py`, `archiver.py`, `excel_backup.py`, `transactions_sheet.py`). V3 is the generation where SQLite becomes canonical and Excel demotes to a generated export. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-13-persistence-api.md`](../../docs/apis/v3-deepdive-13-persistence-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what schema/taxonomy exists** — that's Architect API's registry (file 01 #25, rule #7's binding constraint); Persistence stores instance values against whatever types Architect has registered, never invents its own parallel taxonomy.
- **implement search logic beyond hosting the tables** — Search/Query API (its own future deep-dive) owns the actual FTS5 query logic; the tables live in Persistence's own database because a separate synced copy would be redundant infrastructure, not because Persistence owns search.
- **decide export *content*** — Export Framework (§7) provides the mechanism; what a given export actually contains is each export provider's own concern.
- **decide group access rules** — a receipt row carries an optional `group_id` column, stamped at write time from Groups' own `GetEffectiveGroup()` call (its deep-dive §5), but *who's allowed to query across a group* is Groups' own permission rule (§4.1 there) and Search/Query's own enforcement (its deep-dive §4), not something Persistence itself gates — Persistence just stores the tag faithfully.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

`logical_id` (SHA-256 of the *original uploaded bytes*, before any re-encoding) and `physical_hash` (the hash of whatever is actually stored right now) are deliberately two different values, resolved through a mapping table. Collapsing them back into one is the exact bug that was caught before it shipped: retention deletes the original upload, so a storage filename derived from the identity hash would stop matching its own contents. Nothing else in the system touches disk — if you are reaching for `open()` outside this package, that is the bug.
