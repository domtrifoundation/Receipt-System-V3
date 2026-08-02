# Accounting Sync API

Accounting Sync owns **live, ongoing integration** with a user's own QuickBooks or Xero account — pushing processed receipts as expense/bill records automatically, not a one-time file export.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new — surfaced as a blind spot during a corpus-wide sweep. V2 had no accounting integration; its output was the Excel workbook. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-50-accounting-sync.md`](../../docs/apis/v3-deepdive-50-accounting-sync.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own one-time export generation** — QuickBooks' IIF format and Xero's CSV import format are both genuinely simple, file-based, no-OAuth-needed exports; these live as two new Export Framework providers (`quickbooks_export.py`, `xero_export.py`, `v3-deepdive-31-export-framework.md`'s own package) rather than duplicating Export Framework's own well-established pattern here. This API only owns the *live*, credentialed, ongoing sync case.
- **own the vendor/corporation data model** — reads from temporal_learning's own Corporation/Branch/Franchiser structure (`v3-deepdive-40-temporal-learning.md` §4) to map a receipt to an accounting-software-side vendor record; never maintains a second, parallel vendor concept of its own.
- **attempt full bidirectional sync in this version** — see §4's explicit scoping decision.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

One-way push only. Bidirectional sync against an external system's own schema is a real problem that is explicitly deferred, not overlooked. OAuth connections are per-user, never system-wide, and tokens are stored encrypted and structurally separate from queryable business data. The no-OAuth file exports for the same two platforms are Export Framework providers, not this API.
