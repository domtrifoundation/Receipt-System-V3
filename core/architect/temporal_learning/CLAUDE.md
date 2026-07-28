# temporal_learning

**Sub-API of Architect API** (`core/architect/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

temporal_learning owns **how the system's vendor/branch/franchiser knowledge changes over time** — every write to the live Vendor Directory, staged through review (with one deliberate exception, §6.2), never direct except for that one case.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had a real learning mechanism — `vendors.py` accumulated a vendor canon with aliases and corrections over time. V3 restages every write through a moderation queue rather than applying it directly, and drops git from the design entirely, but the function is second-generation. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-40-temporal-learning.md`](../../../docs/apis/v3-deepdive-40-temporal-learning.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the Vendor Directory's initial seed data** — that's Architect's own `vendor_directory/wikidata_bootstrap.py` (its deep-dive §3), a one-time/occasional bootstrap concern, genuinely separate from the ongoing learning process this document owns.
- **decide what counts as a valid contribution category** — the taxonomy of what CAN be contributed is Architect's own registry definitions (its deep-dive §1); this sub-API processes contributions of those already-registered types, never invents a new category of fact to learn.
- **perform the actual matching** — Matching API (its own deep-dive) does the fuzzy-matching that determines *which* corporation/branch a receipt refers to; temporal_learning only handles what happens when someone (or the pipeline itself) proposes a *correction or addition* to that data.
- **own the UI itself** — §8 states the requirement precisely; the actual screens are Interface API's own future work.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

The moderation queue is a plain table (`contributions`: old/new values, status, reviewer, timestamps) in the same queryable database — **not git**, which was scoped and deliberately reversed (`docs/MAINTENANCE.md` §4). Wikidata bootstrap is a separate concern living in `vendor_directory/`, and its query must traverse subclasses (`wdt:P31/wdt:P279* wd:Q4830453`) — a bare `wdt:P31` match is the confirmed root cause of V2's bootstrap returning ~2,600 entries and missing real PH SMBs. Scope is name and category only; Wikidata is not a trustworthy source for TIN or franchise data.
