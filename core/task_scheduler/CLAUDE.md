# Task Scheduler

Task Scheduler owns **letting an owner/staff user configure their own recurring actions** through a real UI — "run a full rescan every Sunday at 2am," "email the SLSP export automatically every quarter" — without editing raw config or code.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's idle jobs ran on fixed internal intervals set in code; no user could define a recurring action, and there was no trigger provider abstraction. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.02`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

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

Yes, and specifically: `UserScheduledTask.action_params` is the `FrozenDict`-typed field this
applies to, and `errors.py`'s `ERROR_CODES`/`ERROR_SUMMARIES` are the module-level constant
tables §2.1.1 reaches. Any `isinstance` check against one must test `collections.abc.Mapping`,
never `dict` — the 3.15 builtin is not a `dict` subclass, and here that failure would silently
run a scheduled action with none of its parameters (a rescan losing its `since` bound is a
materially different job, not a smaller one). `tests/unit/core/task_scheduler/test_contracts_and_store.py`
carries the `@pytest.mark.forward_compat` assertions.

The mutable structures here are deliberately **not** `FrozenDict` and the distinction is visible
in the type: `SchedulableActionRegistry`'s own action map and `TriggerRegistry`'s provider map
are genuinely mutable internal state populated at startup, which §2.1.1 does not reach — both
guarded by a real lock rather than relying on the GIL, since this project targets free-threaded
3.14t (§3.3.1).

Per the deep-dive's own §8 forward-compatibility note, this sub-API introduces **no new
native/C-extension dependency**: the cron parser is pure Python written here rather than a
`croniter` dependency, so there is no new Telemetrees tracking entry either.

## Real gotchas specific to this folder

This has its own top-level folder rather than living inside Background Workers, and that is the correction rather than an accident: burying it as a subsection of Background Workers' own document is one of the two real instances that caused `docs/PRINCIPLES.md` §1.8 to be written as a hard rule. Scheduling arbitrary code is prohibited — the allowlist of schedulable actions is a hard requirement, not a convenience.

**Missed runs never catch up** (§10's resolved open question). A task whose occurrence passed
while the instance was down does not fire on return — it waits for the next scheduled
occurrence. This looks like data loss and is deliberate: the alternative releases a flood of
simultaneous catch-up jobs the moment the instance comes back, competing for resources exactly
when the system is already recovering. `FireDecision.missed` reports it as a fact worth logging,
not as an error.

**The allowlist starts empty, and that is the safe state.** No Core API is wired to register a
real schedulable action in this build yet, so `default_registry()` rejects every `action` at
creation time — the same posture `core/health/resource_ledger.py` takes toward Setup's
not-yet-existing hardware profile. An empty allowlist that denies is correct; an absent
allowlist that permits would invert §4 during exactly the window where nothing has constrained
it yet.

**Rejection happens at creation, never at dispatch.** Both an unregistered action and a
malformed cron expression fail when the user submits them (§9's own two hooks). The failure this
prevents is not "the wrong thing happens" but "the wrong thing happens *later*, somewhere the
user cannot connect back to what they did" — a task that fails at 2am on a Sunday is a support
ticket; one rejected in the form is a form error.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `cron.py` — §7's surface takes a `cron_expression` and §9 requires malformed ones rejected at
  the boundary, but the layout names no module to do it in. Kept separate from `firing.py` so
  parsing (a pure, total function over a string) is testable without any notion of time.
- `firing.py` — §10's missed-run policy made a checkable value rather than a side effect buried
  in whatever loop happens to call it. Splitting it out is what let the catch-up-flood case be
  tested directly instead of inferred.
- `store.py` — §3 says schedule data lives in the owning user's own Persistence database; this
  is the adapter that puts it there, kept out of `registry.py` because the allowlist is global
  and process-wide while this is per-user (`docs/PRINCIPLES.md` §1.5).

**The `.proto` gap this section used to describe is now closed.** `task_scheduler.proto`
defines the five RPCs the deep-dive names (`CreateScheduledTask`/`UpdateScheduledTask`/
`DeleteScheduledTask`/`ListScheduledTasks`/`ListSchedulableActions`). Two new files carry
the real assembly: `service.py`'s `TaskSchedulerService` combines `TaskStore` (per-user
persistence), `SchedulableActionRegistry` (the allowlist), and `cron.parse`/
`enforce_task_cap` (creation-time validation) into one operations surface; `grpc_servicer.py`'s
`TaskSchedulerServicer` wires that to the wire. Confirmed live: an owner creating a task
against a registered action and valid cron expression; a `client`-role caller and an
unresolvable session both denied `ROLE_FORBIDDEN`; an unregistered action and a malformed
cron expression both rejected at creation, never accepted; an update changing only the
field actually supplied; a delete that removes the real row; and `ListScheduledTasks`
correctly scoped per user (two different owners each seeing only their own tasks).

**`errors.RoleForbidden` is a real addition, made alongside the servicer.** This package's
own opening line ("letting an owner/staff user configure their own recurring actions")
implies a role gate `contracts.py`'s own docstring already promised (mirroring
`core/audit/service.py`'s injected, fail-closed `role_resolver`), but no error code existed
for it until the servicer needed one — added to `errors.ERROR_CODES`/`ERROR_SUMMARIES` the
same append-only way every other error code in this project is added.

**`GrpcSessionResolver` (`grpc_servicer.py`) is genuinely synchronous, matching
`core/support_ticketing/service.py`'s own equivalent** — a plain `grpc.insecure_channel`,
not `grpc.aio`, since nothing here requires an async resolver signature.
