# Task Scheduler

Task Scheduler owns **letting an owner/staff user configure their own recurring actions** through a real UI — "run a full rescan every Sunday at 2am," "email the SLSP export automatically every quarter" — without editing raw config or code.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's idle jobs ran on fixed internal intervals set in code; no user could define a recurring action, and there was no trigger provider abstraction. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-39-task-scheduler.md`](../../docs/apis/v3-deepdive-39-task-scheduler.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the actions themselves** — a rescan, an export generation, a report are each some other API's own domain logic; this sub-API only owns *when* a user wants one to run.
- **own job dispatch mechanics** — once a scheduled trigger fires, the actual work routes through Background Workers' existing per-job classification/routing (its own deep-dive §3) like any other job; this sub-API doesn't reimplement that.
- **allow scheduling arbitrary code** — see §4, a curated allowlist is a hard requirement, not a convenience.
- **belong exclusively to Background Workers' own conceptual domain** — Background Workers exists specifically for maintenance-sweep work arising from V3's own evolving taxonomy/models/rules (its own deep-dive §1); Task Scheduler is a genuinely separate, broader concept (anything a user wants to automate) that happens to reuse the same dispatch substrate rather than inventing a second one. Worth stating plainly since conflating the two is exactly the mistake that put this feature in the wrong document in the first place.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This has its own top-level folder rather than living inside Background Workers, and that is the correction rather than an accident: burying it as a subsection of Background Workers' own document is one of the two real instances that caused `docs/PRINCIPLES.md` §1.8 to be written as a hard rule. Scheduling arbitrary code is prohibited — the allowlist of schedulable actions is a hard requirement, not a convenience.
