# Export Framework

**Sub-API of Persistence API** (`core/persistence/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Export Framework owns the **Provider Registry mechanism for exports** and each concrete export provider's own format logic.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. Producing the Excel ledger was V1's entire output (workbook, sheet, and column mapping all configured up front) and V2's too, with a derived Transactions sheet on top (`excel_writer.py`, `transactions_sheet.py`). What changes in V3 is that the workbook stops being the store and becomes one registered provider among several. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-31-export-framework.md`](../../../docs/apis/v3-deepdive-31-export-framework.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own canonical data** — every provider reads from Persistence's own tables; none maintains its own copy or cache of business data.
- **decide when an export happens** — a user/staff action or Account Guardian's data-portability flow triggers a given provider; this framework just runs whichever one was asked for.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

V2's live-formula technique is worth keeping and is: the print-friendly summary sheet is built as Excel formulas pulling from the raw data sheet, rebuilt only when structure actually changes rather than on every value edit. V2's file-open-tolerance requirement is **not** carried forward and should not be reintroduced — the server generates a file, the user downloads their own copy, so there is no file the server and the user's Excel are ever both touching. The field-level format of the SLSP and audit-package exports is still unspecified; the home is settled, the content is not.
