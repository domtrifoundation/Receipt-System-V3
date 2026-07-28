# Background Workers API

Background Workers exists because of a genuinely V3-native architectural fact, independent of anything V2 did: **this project's own design lets the system's rules, taxonomy, and models keep improving after data has already been processed** — Architect's registry evolves (a vendor's TIN gets corrected, a new flag type gets added), Update API/Proving Grounds promotes better OCR engines and Inference models to a channel over time, Reconciliation's own check inventory can grow (the still-open ATP check, for instance). Every one of these creates the same structural gap: **data processed correctly under yesterday's rules can silently fall behind today's**, and nothing else in this system's design notices that on its own. Background Workers is the generic scheduling/dispatch substrate that exists to close that gap — domain APIs register work (both the fresh maintenance-sweep triggers this creates, §4, and unrelated one-off jobs), this API decides *how and when* it runs.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had a real idle-job substrate — `llm_worker.py` ran numbered jobs 1–21 whenever the daemon was idle, with its own interval/tick/config-gate anatomy documented in V2's `docs/BACKGROUND_WORKERS.md`. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-12-background-workers-api.md`](../../docs/apis/v3-deepdive-12-background-workers-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own any business logic** — a job that checks VAT math or backfills a field belongs to Reconciliation/Review-Flagging's own domain logic; this API only provides the scheduling/execution mechanism that logic runs on top of, already stated plainly in file 03's own correction ("clarified as the generic execution substrate that domain APIs run on top of, not a competing owner of business logic").
- **own LLM-driven background work as a separate subsystem** — an idle-time job that needs the LLM is just a batch Inference API call (prompt + tool calls) dispatched through the normal Inference contract, not a distinct "AI worker" concept living in this API.
- **run a separate worker-server process** — non-LLM workers run in-process within Execution Core's own process (thread/process pool), per file 03's explicit decision; this API is a contract and scheduling logic, not new infrastructure to deploy and monitor separately.
- **decide what counts as "worth a sweep"** — §4's trigger taxonomy defines *when* Background Workers notices something changed; whether a given change actually warrants re-touching historical data is each domain API's own judgment call (Architect deciding a taxonomy change is sweep-worthy, Reconciliation deciding a new rule should run against old data too), never assumed automatically by this API.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

V2's known failure mode — a permanently-failing job retrying forever — is an open, unclosed gap for *registered background jobs specifically*, distinct from Execution Core's own per-stage bounded retry which only covers pipeline stages. Do not assume a retry cap exists here; see the deep-dive before adding a job that can fail permanently.
