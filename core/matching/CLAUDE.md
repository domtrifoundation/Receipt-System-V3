# Matching API

Matching API owns the **matching/lookup logic** — fuzzy-matching an OCR-extracted vendor/address/TIN string against known-good data and returning ranked candidates.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 matched a receipt to a category against a user-supplied master list, with an explicit closest-match rule when nothing matched exactly. V2 made it real fuzzy matching over a learned vendor canon (`vendors.py`, `parser.py`, `rapidfuzz`). The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-15-matching-api.md`](../../docs/apis/v3-deepdive-15-matching-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the Vendor Directory data itself** — schema, Wikidata bootstrap, aliasing, category taxonomy, and the global contribution/audit mechanism all live in Architect API's registry (file 01 #25) — Matching *consumes* that data, never maintains its own parallel copy or learns from a match itself (that's Architect's `temporal_learning`, invoked separately, not implicit in a match call).
- **decide what to do with a low-confidence match** — returns a ranked candidate list with scores; the actual policy for what happens next is resolved in §5 below, not left as an unspecified "caller policy" the way an earlier version of this document did. **This API genuinely has two legitimate callers, not one** — a real asymmetry found while tracing the pipeline, the mirror image of Geo/Address's own earlier correction (`docs/PRINCIPLES.md` §1.9): an earlier version of this line named only Reconciliation, but `MATCHED` is one of Execution Core's own synchronous per-receipt pipeline stages (`v3-deepdive-10-execution-core-api.md` §3), running before `GEOD`/`INFERRED` for every new receipt — Execution Core is the primary, synchronous caller. Reconciliation is the second, genuine caller, applying the identical underlying matching function retroactively (its own check 4.6, `v3-deepdive-17-reconciliation-api.md`, already consumes this API's own candidate-scoring output against old receipts when vendor/category data has since changed) — both callers invoke the same function, never two separate implementations, the concrete backward-carrying case §1.9 itself was generalized from.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This API has two callers, not one — Execution Core synchronously as the `MATCHED` stage, and Reconciliation retroactively against already-written receipts. Both invoke the same function (`docs/PRINCIPLES.md` §1.9). A capability added here for the live pipeline that cannot be called against old data is a design error, not a scoping choice. V2's hard-learned fuzzy-matching pitfalls (case sensitivity, over-eager collapsing of distinct names, generic words causing false positives, needing multiple sightings before trusting a correction) are documented risks to guard against — and guarding against them is still an open gap here.
