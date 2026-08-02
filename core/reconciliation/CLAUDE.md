# Reconciliation API

Reconciliation owns two related things: **propagating corrections** (when Architect's registry data changes — a vendor's TIN gets fixed, a branch gets merged — pushing that correction to every affected receipt already in the canonical database) and **running validation checks** (VAT math, TIN format, date plausibility, and the rest of V2's real check inventory) that surface a Review/Flagging flag on a hit.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2's `reconcile.py` (121 KB, its single largest module) did exactly this — VAT math, duplicate detection, field backfill, and the rest of the check inventory V3's own twelve checks were independently re-derived from. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-17-reconciliation-api.md`](../../docs/apis/v3-deepdive-17-reconciliation-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the flag taxonomy** — Architect's registry defines what flag types exist (Audit deep-dive §1 already states this distinction); Reconciliation's checks *produce* flags of types Architect already registered, never inventing a new flag type inline.
- **own the learning mechanism** — a vendor's TIN getting corrected happens in Architect's `temporal_learning`; Reconciliation only reacts to that correction already having happened, propagating its consequences.
- **run as a competing scheduler** — every check and propagation batch runs on Background Workers' execution substrate (its own deep-dive), scheduled and routed by that API's per-job classification, not a Reconciliation-owned thread pool.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Checks run on Background Workers' substrate, never a scheduler owned here. A check produces flags of types Architect has already registered — inventing a flag type inline is the specific violation `docs/PRINCIPLES.md` §3.4 exists to prevent.
