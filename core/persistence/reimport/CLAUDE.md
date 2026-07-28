# Reimport

**Sub-API of Persistence API** (`core/persistence/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Reimport owns **ingesting a hand-edited exported file and reconciling it against current canonical state**.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no path for a hand-edited export to flow back in — the workbook *was* the store, so there was nothing to reconcile against. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-30-reimport.md`](../../../docs/apis/v3-deepdive-30-reimport.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the export itself** — that's Export Framework (its own deep-dive); Reimport consumes what that produced, doesn't generate it.
- **own content scanning** — Content Security API scans every reimported file exactly like any other untrusted external upload, no special-cased trust just because it's "the user's own file coming back."
- **silently resolve genuine conflicts** — §4 below is the actual design; the short version is that a real conflict always surfaces to a human, never gets silently picked one way.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

The three-way diff's rules are the whole point and none of them may be softened: a field only the user touched applies cleanly; a field only canonical state touched keeps winning, so a stale export can never silently revert a newer correction; a field *both* touched to different values is a real conflict and always surfaces to a human (`docs/PRINCIPLES.md` §4.3). An uploaded file gets scanned by Content Security exactly like any other untrusted upload — being "the user's own file coming back" earns it no trust.
