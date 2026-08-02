# Disaster Recovery

**Sub-API of Persistence API** (`core/persistence/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Disaster Recovery owns **full-instance restore** — rebuilding a working instance from the B2/Storj blob backups and SQLite snapshot backups after catastrophic disk loss. Restated precisely from the parent document, since these three are easy to conflate: distinct from the backup *mechanisms* (Persistence §4.4 — replication, not restore), distinct from Reimport (single-user data reconciliation against canonical state, not instance-level rebuild), distinct from Historian (an audit trail, not a restore procedure).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new — stated as such in `docs/apis/v3-plan-01-core-apis.md` #5 and confirmed against V2, whose `excel_backup.py` is a replication mechanism with no restore procedure behind it. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-33-disaster-recovery.md`](../../../docs/apis/v3-deepdive-33-disaster-recovery.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the backup *mechanisms*** — replication to B2/Storj and the day-rotated SQLite snapshots are Persistence's own §4.4 concern; this sub-API owns the restore procedure that consumes them.
- **own single-user data reconciliation** — that is Reimport, a different problem at a different scale.
- **serve as an audit trail** — that is Historian. A restore procedure and a record of what changed are not the same artifact.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

Restore order is blobs before SQLite, then hash verification against orphaned-reference detection — not an implementation preference, it is what makes a partial restore detectable rather than silently wrong. Partial/single-user restore is genuinely open in the deep-dive and should not be assumed either way.
