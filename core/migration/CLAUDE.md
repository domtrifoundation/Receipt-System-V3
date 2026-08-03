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

`a02.00.02`

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

N→N+2 is always N→N+1→N+2. A shortcut migration means two code paths can produce the same end state, which is a real correctness risk, not a performance trade. **Rejected at registration, not at run time** (`MultiVersionStep`): the two paths only disagree once someone edits one of them, which is far too late to discover the shortcut exists. V2's explicit-user-confirmation UX is deliberately not carried forward: migrations write through Persistence's normal path, so each one is already atomic and Historian-revertable.

**This package fails closed harder than most of the repo, and deliberately.** Everywhere else
§4.4's degrade-gracefully posture dominates. Here a missing step **stops the walk**, because a
structure left half migrated — some steps applied, one skipped, later ones applied on top — is
in a state no version number describes and no step was written to expect. The whole value of a
chained registry evaporates the moment a gap is stepped over. `MigrationResult.reached_version`
reports how far it actually got, which is the honest answer to "what state is this structure in
now" and matters more here than almost anywhere: a caller that assumed the target was reached
would then run code against a schema that does not exist.

**Idempotency is the step's contract, not the runner's.** A step returns `True` for "I did real
work" and `False` for "this structure already carried the change". The runner cannot determine
that — only the step knows what to look for — so a step that unconditionally returned `True`
would make an interrupted batch's re-run report a full migration it never performed. That is
the mistake §8's idempotency hook exists to catch, and `steps/v1_to_v2.py` is the worked example
spelling the shape out before anyone has to write the first real one under release pressure.

**Downgrades are refused rather than attempted.** This registry holds forward N→N+1 steps only,
so walking backwards would need inverse steps nobody wrote, and guessing at one is how a
"rollback" silently destroys data. Reverting is Persistence's own Historian-backed job.

**Bulk parallelism is deliberately absent from this package.** §4 routes a multi-tenant batch
through Background Workers' `CPU_PROCESS` class rather than having this API build its own
dispatch, so `migrate_many` is a plain sequential loop such a job calls per structure — not a
pool this module manages (`docs/PRINCIPLES.md` §1.5). One structure failing never stops the
others: a batch halting on the first bad database would leave every user after it un-migrated
with nothing to say which ones those were.

**`steps/` is empty of real steps today, and that is correct rather than unfinished.** Every
structure kind is at version 1 (`contracts.CURRENT_VERSIONS`), so there is no bump to write a
step for. The chain-integrity test asserts the shipped registry against those versions, so the
moment `CURRENT_VERSIONS` moves to 2 without a registered 1→2 step, CI fails — which is exactly
what §8 asks for, rather than the gap being found mid-migration on a live system.

**Files here that the deep-dive's §2 package layout does not list**: none. Every module matches
§2 exactly. `steps/v1_to_v2.py` is named there and is present, deliberately unregistered.

**The `.proto` gap this section used to describe is now closed.** `migration.proto` defines
`RunMigration`/`GetCurrentVersion`, and `service.py`'s `MigrationServicer` wires the real
`MigrationRunner` to both. `GetCurrentVersion` answers "this build's own target version for
`kind`" (`contracts.CURRENT_VERSIONS`) — Migration API does not itself persist a specific
structure's *stored* version (that column lives wherever the structure actually is:
Persistence for `database_schema`, Architect for `vendor_data`), so this is a build-level
answer, not a per-structure query. Confirmed live: a real chain of two registered steps
walked and applied in order; a re-run correctly reporting `already_applied` rather than
`applied`; a real chain gap stopping the walk at `MISSING_MIGRATION_STEP` with
`reached_version` honestly reporting how far it got; a structure already at its target
completing trivially with zero steps; and `target_version=0` correctly deferring to the
build's own default. This joins the same open question `core/tool_call/CLAUDE.md` and
`core/background_workers/CLAUDE.md` still record for themselves.
