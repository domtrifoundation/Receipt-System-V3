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

`a02.00.02`

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

Yes, and specifically at the constant-table level rather than the contract level. The frozen
contracts here (`JobRegistration`, `JobHealth`, `JobRunResult`, `IdleWindow`) carry no dict-typed
field — a job registration is a handful of scalars — so §2.1 has nothing to bite on. What §2.1.1
*does* reach is the module-level tables: `contracts.DEFAULT_CADENCE_SECONDS` and
`registry.KNOWN_JOBS`, both `FrozenDict`. Any `isinstance` check against either must test
`collections.abc.Mapping`, never `dict`: the 3.15 builtin is not a `dict` subclass, and here that
failure would make a job's shipping cadence read as unset and the job never be scheduled — on
unattended work, invisible until someone asks why a sweep never ran.
`tests/unit/core/background_workers/test_contracts.py` carries the `@pytest.mark.forward_compat`
assertions.

The mutable structures are deliberately **not** `FrozenDict` and the distinction is visible in
the type: `JobRegistry`'s own job, handler and health maps are live state populated at startup
and updated on every dispatch, which §2.1.1 does not reach. They are guarded by a real lock
rather than relying on the GIL — this matters more here than in most packages, since the
scheduler dispatches into a thread pool and a process pool and genuinely touches that state from
several threads at once (§3.3.1).

## Real gotchas specific to this folder

**The retry cap now exists — this line previously said it did not, and that was stale.** V2's
known failure mode (a permanently-failing job retrying forever) is closed by the deep-dive's own
§10 resolution, implemented here: every registered job tracks a consecutive-failure counter, and
after `MAX_CONSECUTIVE_FAILURES` (five) the job auto-disables and the tripping dispatch carries
`tripped_failure_guard=True` so a caller surfaces exactly one `ATTENTION`-level Logs entry rather
than five. **Re-enabling is an explicit staff action** (`JobRegistry.enable`) after investigating,
never automatic — and `force=True` on a dispatch deliberately does *not* clear it, since a force
flag that also cleared the guard would be a way to keep a broken job limping without anyone ever
looking at why.

**A skip is not a failure.** Only a genuine `FAILED` outcome increments the consecutive counter;
a job correctly yielding to foreground work every hour for a week has not failed once. Counting
skips would auto-disable the healthiest jobs on the busiest systems, which is precisely backwards.

**Unavailable means not idle.** Execution Core does not exist in this build, so the default
`RunStateReader` raises and every `idle_only` job is held back. That is `docs/PRINCIPLES.md` §4.2
outranking §4.4 in the one place this package lets it: an idle-only job exists specifically to
yield to foreground work, so running one while unable to confirm the system is quiet defeats the
class entirely. Skipping a sweep costs one interval; running a `CPU_PROCESS` sweep during a live
batch costs the user's actual work.

**Per-user and system-wide idle scope are one distinction, not two knobs** (§10). A job touching
per-user resources checks *that user's* idle state — one user's active session has no business
blocking another user's archive sync — while a genuinely system-wide job checks nobody's, because
it touches no per-user resource. The distinction tracks whether the job's target is per-user; it
is not something an operator configures.

**Nothing a registered job does may propagate out of the scheduler.** A job that raises, hangs or
returns nonsense becomes a `FAILED` result and the loop continues to the next job. A scheduler one
bad job could take down would take every other registered job with it, and the resulting silence
across log retention, session cleanup and every maintenance sweep would be far worse than the one
job's own failure.

**`KNOWN_JOBS` mirrors the deep-dive's §6.1/§6.4 tables in code, on purpose.** §6.5 makes keeping
that table current a standing obligation and §9 asks for a test proving code and table agree — but
a table that exists only in Markdown cannot be checked by anything.
`tests/unit/core/background_workers/test_registry_completeness.py` parses the real document and
asserts both directions, so a job added to the doc but not the code fails, and so does the reverse.
§6.1 records that the doc-only direction has already gone wrong once: three jobs were fully
designed in their own documents and never made it into the table at all.

**Files here that the deep-dive's §2 package layout does not list**: none. Every module matches
§2 exactly.

**The conflict this section used to describe is now resolved, deliberately, and the same
decision covers `core/tool_call/CLAUDE.md`'s identical question.** `docs/PROCESS_TOPOLOGY.md`
wins — every Core API gets a real gRPC surface — but *what* that surface exposes differs by
what actually makes sense to call remotely. This API's own §1 boundary is still correct that
non-LLM workers run in-process inside Execution Core: a registered `handler` is a live Python
callable held by whichever process registered it, not something a remote caller could invoke
by name even if there were an RPC for it. So `background_workers.proto` is deliberately
**observability/control only** — `ListJobs`/`GetJobHealth`/`GetNextDue` give a TUI or webapp
real visibility into what is registered and how it is running, and `EnableJob` gives staff the
one explicit action §10's retry guard requires ("re-enabling is an explicit staff action, never
automatic"). Actually running a job (`JobScheduler.dispatch`) stays an in-process call only.

Contrast with Tool Call API's own resolution of the identical conflict: its registered tools
are exactly the kind of thing a *different* process (Inference API's own agentic loop)
genuinely needs to invoke remotely, so its surface exposes real dispatch. Same underlying
decision — every Core API is gRPC-reachable — applied to two structurally different kinds of
registered work.

**`errors.py` gained no new codes for this servicer** — `EnableJob`'s own role gate uses a
servicer-local `RoleForbidden`/`"ROLE_FORBIDDEN"` (`service.py`) rather than a taxonomy
addition, since this package's own error codes are otherwise entirely about job identity and
registration validity, not session/role concerns; `EnableJob` is the one RPC in this surface
that needed one at all.

Confirmed live: a real registered job listed with its class/interval/scope; health read for
both a never-run and a guard-tripped job; a client-role caller and an unresolvable session both
denied `EnableJob`; an owner successfully clearing a tripped failure guard (with the clearing
user id recorded in `disabled_reason`); and `GetNextDue` correctly returning nothing when no
`next_due_source` is wired in versus real estimates when one is.
