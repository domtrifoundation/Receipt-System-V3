# Geo/Address API

Geo/Address API owns geocoding — two genuinely distinct capabilities, not one: **completing or correcting an incomplete/incorrect address** read off a receipt, and **reverse-checking what business is actually located at that address**, as a real cross-corroboration signal for the vendor match itself (an OCR-read vendor name that doesn't match what's actually at the geocoded address is a real, useful discrepancy signal, not just an address-quality check).

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had real geocoding — `geo_lookup.py` with OSM/Nominatim and Google Places providers, forward and reverse lookups. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-16-geo-address-api.md`](../../docs/apis/v3-deepdive-16-geo-address-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide when a geo lookup is worth its cost** — a per-run call budget and whether a given receipt even needs address correction is caller policy, the same boundary every other corroboration-shaped API in this project draws for itself (OCR's cloud tier, Inference's reasoning-preset budget). **This API genuinely has two legitimate callers, not one** — a real correction made after tracing the pipeline found only one connected and assumed that was the whole picture: **Execution Core** calls it synchronously as the `GEOD` stage for new receipts during the live run (`v3-deepdive-10-execution-core-api.md` §3, between `MATCHED` and `INFERRED`); **Reconciliation** calls the identical underlying function against already-written, older receipts during its own idle-time sweep — the concrete case `docs/PRINCIPLES.md` §1.9's own backward-carrying-capability principle was written from. When this API's own provider set or corroboration logic improves, that improvement should be able to reach old receipts too, not just ones processed going forward — which is only actually possible because both callers invoke the same underlying capability rather than each having their own copy.
- **own the address data it corrects into** — the corrected/canonical address becomes part of a receipt's own record via Persistence's normal write path; this API just returns a result.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Same two-caller rule as Matching (`docs/PRINCIPLES.md` §1.9) — Execution Core's `GEOD` stage and Reconciliation's idle sweep call the identical function. A better provider must be able to improve old receipts, not just new ones. Provider responses cache into the canonical SQLite database keyed by normalized query; that cache is what makes the free tiers viable, so bypassing it in a new code path has a real cost.
