# Review/Flagging API

Review/Flagging owns the **flag lifecycle** — creation, assignment, resolution, dismissal — for every flag type Architect's registry has defined.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 produced real flags and quarantined receipts — the flag-only discipline for anything the LLM wrote that was not arithmetic-verifiable or majority-gated, plus the quarantine path in `processor.py`/`llm_worker.py`. V3's flag *taxonomy* was independently re-derived and now lives in Architect. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

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
