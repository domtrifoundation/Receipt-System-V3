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

`a01.00.01`

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

## Real gotchas specific to this folder (continued)

- **QuickBooks (`providers/quickbooks.py`) and Xero (`providers/xero.py`) are NOT
  live-tested this session** — neither `intuitlib`/`python-quickbooks` nor `xero-python`
  is installed in this environment (confirmed: both raise `ModuleNotFoundError` here),
  and there are no real app credentials to authenticate against even if they were. Both
  adapters are built directly from each SDK's own published API shape, the same honesty
  posture `core/inference/backends/onnx_genai_backend.py`'s own module docstring takes
  for its own unverified library calls. What IS live-tested and confirmed real: the
  unconfigured/SDK-missing degrade path (`is_available()` correctly reports `False`),
  `TokenStore`'s real `Fernet` encryption round-trip (including a wrong-key `InvalidToken`
  failure), the flagged-receipt exclusion path, and the full servicer assembly with fake
  provider adapters standing in for the real SDKs.
- **`FlagChecker` has no real implementation — `NoOpFlagChecker` (`service.py`) is the
  shipped default, and it never excludes anything.** `core/review_flagging/` owns the
  real flag lifecycle (`contracts.py`, `db.py`, `gateways.py`, `lifecycle.py` are all
  real) but has no gRPC proto/`service.py`/generated stubs at all yet (confirmed by
  directory listing), and this project's own process-topology rule means Accounting Sync
  cannot reach into another API's internals directly even in the same repo — every
  Core API talks to every other one over gRPC only. This is a real, named, deliberately
  NOT-fabricated gap: deep-dive §6/§9's own flagged-receipt-exclusion rule is
  structurally correct and tested (`test_sync_engine.py`'s
  `test_flagged_receipt_is_excluded_before_touching_the_provider` and
  `test_service.py`'s equivalent servicer-level test both use a real, working
  `FlagChecker` fake), but the *shipped default* used until Review/Flagging ships a
  gRPC surface cannot enforce it at all. `AccountingSyncServicer.__init__`'s own
  `flag_checker` parameter exists specifically so wiring in a real one later is a
  one-line change here, not a rewrite.
- **`Purchase`/`BankTransaction` push is one-way and does not verify the record survived
  a provider-side edit or deletion** — deep-dive §4's own explicit scope boundary,
  confirmed structurally by `test_sync_engine.py`'s
  `test_provider_protocol_exposes_no_pull_or_read_back_method` (fails the moment
  `AccountingSyncProvider` grows a pull/fetch/read-back method).
- **The one-time, no-OAuth QuickBooks IIF / Xero CSV export path is deliberately NOT
  here** — see "What this API explicitly does NOT own" above; that's an Export
  Framework provider pair, not this package.

## Implementation status

Implemented this session — `contracts.py`, `errors.py`, `token_store.py` (real `Fernet`
encryption), `mapping.py`, `providers/base.py` + `quickbooks.py` + `xero.py`,
`metrics.py`, `sync_engine.py` (the real assembly wiring providers + `FlagChecker` +
metrics together), `persistence_client.py`, `service.py` + `accounting_sync.proto` +
generated stubs. 41 tests, all passing, including the three deep-dive §9-named tests
(one-way boundary, flagged-receipt exclusion, credential isolation).
