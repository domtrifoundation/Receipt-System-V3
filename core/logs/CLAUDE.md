# Logs API

Logs owns comprehensive, verbose **operational trace** — OCR engine outputs/timing, LLM prompts/responses/tool calls, preprocessing steps, worker activity, errors — covering every subsystem, stored as day-rotated JSONL files with a lightweight query index over them.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Second generation. V1 had no logging layer worth
the name. V2 did: `receipt_processor/verbosity.py` implemented real verbosity tiers, and V2's
own commit history carries the `str(e)`-instead-of-full-traceback bug that is now an explicit,
unconditional requirement here (§3.3 of the deep-dive) rather than something to rediscover.
V3 is the generation where operational trace becomes its own bounded service with structured
entries, an index, and permission-gated read access instead of tier-filtered console output.
The `.00.00` tail matches the same deliberate-jump discipline `x03.00.00` itself follows.
`MM` increments again on any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-18-logs-api.md`](../../docs/apis/v3-deepdive-18-logs-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **storage through Persistence's Historian** — Logs are gitignored, rotated flat files with their own retention policy, never an events table. Historian is the *data-change* audit trail; Logs is *operational* trace, a genuinely different volume and purpose that does not belong in Historian's atomic-transaction-per-write model.
- **Audit's privileged-action record** — a receipt's OCR timing is Logs' job; a staff member's break-glass grant is Audit's, never both.
- **any rendering or presentation logic** — a `LogEntry`'s level carries a `suggested_style` hint (`LEVEL_STYLE_HINT`) precisely so a renderer does not maintain its own drifting opinion about severity, but Logs itself never renders anything. It is a client-agnostic data service, the same way Persistence is.
- **its own permission model** — cross-user reads go through Auth's existing `check_access()` break-glass gate (`v3-deepdive-05-auth-tenancy-api.md` §6.3), never a second mechanism invented here.

## Forward-Compatibility Pattern applicability

Yes. `LEVEL_STYLE_HINT` is a module-level lookup table and is therefore `FrozenDict`, not a
plain `dict` — `docs/PRINCIPLES.md` §2.1.1 covers this case specifically, and this module is
one of the two instances that section was written from. Any `isinstance` check against it must
test `collections.abc.Mapping`, never `dict`: the 3.15 builtin is not a `dict` subclass. This
API is pure async I/O (`v3-plan-02-architecture.md`'s concurrency table, #13) with no
compute-bound work, so it carries no GIL-protected assumptions of its own.

## Real gotchas specific to this folder

The SQLite index in `index.py` is a **query accelerator over the JSONL files, not a second
source of truth**. It must stay fully rebuildable from the JSONL files alone — there is a
testing hook that deletes it and regenerates it precisely to keep that claim honest. If you
find yourself writing log *content* that exists only in the index, that is the bug.

Full tracebacks are captured unconditionally, independent of verbosity tier. Tiers control the
volume of routine logging; they never gate whether a failure's traceback is recorded. This is a
direct correction of a real V2 bug, not a preference.
