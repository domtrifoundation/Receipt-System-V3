# Historian

**Sub-API of Persistence API** (`core/persistence/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Historian owns **two related but structurally distinct tracks**, both append-only, both living in the same database, both queryable together as one chronological per-receipt history:
- **The data-change track** (unchanged from the original design) — table/row/before/after for every logical write to canonical data, atomic with the write itself.
- **The narrative track** (new, this revision) — a quantized, human-readable account of every pipeline stage a receipt passed through: ingestion, preprocessing, each OCR engine's own reading and confidence, corroboration's outcome, matching, geocoding, the LLM's own deliberation and confidence, any flag raised, the final write — starting at first scan and continuing through every subsequent human audit or system-triggered rescan.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 kept a real change history — `excel_backup.py` committed the workbook, archive, and receipts inbox together into one git repo so a vendor correction and its file moves landed as one linked commit, plus per-cell comment trails tagged by which worker wrote them. V3 replaces the mechanism entirely (an in-database append-only table, not a parallel git log) but the function is second-generation. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-29-historian.md`](../../../docs/apis/v3-deepdive-29-historian.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **track privileged/security actions** — still Audit API's job, a structurally separate database for a structurally different kind of event.
- **duplicate Logs API's full verbosity** — this is the load-bearing distinction for the narrative track specifically, worth stating as a hard rule rather than a preference: Historian's narrative is **quantized and summarized by design** — "Tesseract read this receipt at 87% confidence" is a narrative entry; the actual raw OCR text, the full LLM prompt/response, and detailed timing data are Logs' own territory, full-verbosity, gitignored, **origin-server-only, never surfaced to the webapp**. Historian's narrative is deliberately the *readable digest* of what Logs records in exhaustive detail — the two are companions at different resolutions, not competitors, and a developer extending either needs to keep that resolution difference intact rather than letting Historian's narrative creep toward Logs' own verbosity (which would both bloat the canonical database and start leaking server-internal detail to a remote audience).
- **provide disaster recovery** — the day-rotated `.sqlite` snapshot checkpoints are Persistence's own recovery mechanism, unchanged.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Two tracks, one table, deliberately different resolutions. The narrative track is quantized and summarized by design — "Tesseract read this at 87% confidence" belongs here; the raw OCR text, full LLM prompt/response, and timing detail belong in Logs. Letting the narrative creep toward Logs' verbosity both bloats the canonical database and starts leaking server-internal detail to a remote audience, since this track *is* webapp-displayable and Logs deliberately is not. Append-only is structural here too (§2.3).
