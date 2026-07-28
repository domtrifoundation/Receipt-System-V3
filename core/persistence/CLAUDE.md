# Persistence API

Persistence owns **all disk access** — nothing else in this system touches disk directly. Two storage mechanisms: a canonical per-user SQLite database (structured records, WAL mode) and a content-addressable blob store (raw/archival images).

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 stored transactions directly in an Excel workbook and archived images into flat or per-vendor folders. V2 kept that shape and added real machinery around it (`excel_writer.py`, `archiver.py`, `excel_backup.py`, `transactions_sheet.py`). V3 is the generation where SQLite becomes canonical and Excel demotes to a generated export. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.02`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

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

**A WAL database's `.sqlite` file is not a backup.** Copying it alone produces a snapshot that opens without error and is missing every committed transaction still sitting in the `-wal` file. `Database.snapshot_to()` uses SQLite's own online-backup API for exactly this reason; Disaster Recovery restores from what that produces, never from a plain file copy.

**`common/async_sqlite.py` does not exist yet.** The deep-dive's §3.1 is right that the `run_in_executor` SQLite wrapper wants exactly one shared implementation rather than one each in Auth, Audit, Logs and here. It currently lives in `db/connection.py` because `common/` was outside this package's write boundary while several APIs were being implemented in parallel. When the shared version lands, `Database` becomes a thin subclass adding this API's own schema and PRAGMAs — nothing outside that one file changes.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `db/receipts.py` — the canonical receipt repository. The layout jumps from `db/schema.py` straight to `service.py`, which is specified as a *thin* servicer; the row mapping and write path have to live somewhere that is not it. **Every write method here takes its `DataChange` and goes through `write_with_history`** — a "just write the row" shortcut is deliberately absent, not missing.
- `exports/providers/common.py` — the shared fetch/build-workbook/store-artifact plumbing all seven providers use. Format logic stays in each provider; only the mechanism is shared.
- `persistence.proto` — the gRPC surface the sub-APIs' own §7/§12 sections each specify a piece of. The layout predates naming a home for the `.proto` itself. `service.py` is transport-agnostic on purpose: the generated servicer is a one-line-per-RPC adapter over it, so behaviour cannot diverge between the gRPC path and an in-process caller.

**Optional dependencies are all lazily imported and all degrade.** `openpyxl` (Excel export and reimport parsing), `b2sdk`, `boto3`, and the Google API client are each imported inside the one adapter that uses them; none is declared in `requirements.txt` yet, and every one of them being absent is a capability reporting itself unavailable, never a crash.
