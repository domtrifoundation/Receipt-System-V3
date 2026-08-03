# Review/Flagging API

Review/Flagging owns the **flag lifecycle** — creation, assignment, resolution, dismissal — for every flag type Architect's registry has defined.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 produced real flags and quarantined receipts — the flag-only discipline for anything the LLM wrote that was not arithmetic-verifiable or majority-gated, plus the quarantine path in `processor.py`/`llm_worker.py`. V3's flag *taxonomy* was independently re-derived and now lives in Architect. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-25-review-flagging-api.md`](../../docs/apis/v3-deepdive-25-review-flagging-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the flag taxonomy itself** — VAT math mismatch, malformed TIN, implausible date, and the rest of the real inventory (Reconciliation deep-dive §4) are defined in Architect's registry; this API manages instances of those types, never invents a new type inline.
- **run the checks that produce flags** — Reconciliation's own domain logic (its deep-dive) is the primary producer; this API is where a flag lives once created, not what creates it.
- **redesign Logs API** — the per-receipt audit screen (§3) pulls a readable slice of Logs' own data; this API is a workflow layer on top of Logs, not a competing log store.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This is also the system's general in-browser edit entry point — a flag or a notification quick-action deep-links straight into an edit form for one field, writing through the normal Persistence path. There is deliberately no separate inline-edit-grid feature to build.

**`.proto`/`service.py`/generated stubs did not exist at all until this session — a real, complete gap, not a documented placeholder.** `contracts.py`, `db.py`, `lifecycle.py`, `gateways.py`, `errors.py`, and `metrics.py` were all real and independently tested, but there was no gRPC surface for anything outside this process to call. This was the concrete blocker `core/accounting_sync/service.py`'s own `NoOpFlagChecker` documented by name — Accounting Sync could not build a real client against a service that did not exist yet. `review_flagging.proto` now defines `CreateFlag`/`AssignFlag`/`ResolveFlag`/`DismissFlag`/`GetAuditView`/`ListFlags`; `ReviewFlaggingServicer` wires `lifecycle.FlagStore` and `audit_screen.build_audit_view` to it for real. `AssignFlag` is a genuine addition beyond the deep-dive's own §6 sketch — `FlagStore.assign_flag` was a real, tested capability with no RPC to reach it at all.

**`audit_screen.py` and `edit_entry_point.py` were both 0-byte scaffolds until this session**, despite being named in the deep-dive's own §2 package layout and referenced by `contracts.py`'s `AuditView`/`EditLink` types. `build_audit_view()` is real: it reads every flag raised for a receipt from the real `FlagStore`, plus a Logs trace via `GrpcLogsTraceSource`. **`logs.proto`'s own `LogQueryRequest` has no `receipt_id` filter** — a real, structural limitation, not an oversight here: the trace source queries Logs scoped to the receipt's own `user_id` (resolved from the flags already found for it) and filters the returned stream client-side for entries whose `context_json` names the receipt id. This is a real call against a real running Logs service, confirmed live, but it is an unindexed per-user scan, not a receipt-indexed lookup — a genuine fix would add a field to `logs.proto`, which is Logs API's own change to make. `edit_entry_point.py`'s `build_edit_link()` is a pure, no-I/O lookup table (`FLAG_TYPE_EDIT_FIELD`) mapping a handful of common flag types to their conventional single-field deep-link target; it is deliberately not exhaustive, and an unlisted flag type falls back to "open the receipt generally" rather than this module guessing at a field.

**Confirmed live, both ways**: a full `CreateFlag` -> `ResolveFlag` round trip through a real in-process gRPC server showing the flag self-assigns to the resolving staff member and becomes terminal; a `client`-role/unresolvable-session attempt denied with `ROLE_FORBIDDEN`; a second resolution attempt on an already-terminal flag rejected with `INVALID_STAGE_TRANSITION`; an owner reassigning an already-assigned flag while a non-owner staff member attempting the same is denied with `OWNERSHIP_DENIED`; and `core/accounting_sync/flag_checker.py::GrpcFlagChecker` genuinely calling `ListFlags` over a real socket and correctly reporting `True`/`False` before and after a flag exists — the loop this gap was blocking is now closed end to end.
