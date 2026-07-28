# Architect API

Architect owns two related things: the **read registry** (definitions — what taxonomy categories, reference-identifier types, and flag types exist) and **temporal learning** (the write submodule — how the system learns new vendor/branch/taxonomy data over time, staged through review).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new as a consolidated registry. V2 reinvented the extensible-typed-thing pattern ad hoc in several places rather than owning it once — that repetition is what this API exists to stop. Its `temporal_learning` submodule has its own separate V2 lineage; see that folder's own `CLAUDE.md`. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-26-architect-api.md`](../../docs/apis/v3-deepdive-26-architect-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **implement any consuming API's own logic** — Matching does the actual fuzzy-matching, Reconciliation runs the actual checks; Architect only defines what a valid vendor record or flag type looks like, never performs the matching or checking itself.
- **allow any other API to define its own parallel taxonomy** — this is file 02's binding rule #7, no exceptions: any new schema/taxonomy/learned-data type goes through this API's registry, full stop.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

`docs/PRINCIPLES.md` §3.4 is binding and has no exceptions: no API defines its own ad hoc typed thing, spins up its own table for learned/schema data, or invents a parallel taxonomy, even for one narrow case. This rule exists because the same pattern was independently reinvented five separate times before this API was created to consolidate it. Architect defines what is allowed to exist; it never holds instance data.
