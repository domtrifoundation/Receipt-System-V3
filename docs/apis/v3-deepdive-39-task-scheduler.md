# V3 Deep Dive: Task Scheduler (sub-API)

**Parent:** Uses Background Workers' dispatch/classification machinery as its execution substrate (`v3-deepdive-12-background-workers-api.md` §3), but is **not** a Background-Workers-specific feature — its own scope is system-wide, any registered schedulable action across any API. Extracted into its own document after being wrongly buried as a subsection, per an explicit standing rule now in `docs/PRINCIPLES.md` §1.8.

**Companion files:** `v3-deepdive-38-supervisor.md` §5 (the wake mechanism this relies on once a dispatching service can sleep), `docs/templates/new_provider.md` (the schedulable-action allowlist follows the same registration discipline).

**Status:** New dedicated document, corrected out of Background Workers' own deep-dive. Real V2 lineage in the *adjacent* sense — nothing in V2 offered a user-facing scheduler, but V2's `reconcile.py`/idle-worker jobs are exactly the kind of action this now lets a user trigger on their own cadence instead of only via V2-style hardcoded intervals.

---

## 1. Scope & boundary

Task Scheduler owns **letting an owner/staff user configure their own recurring actions** through a real UI — "run a full rescan every Sunday at 2am," "email the SLSP export automatically every quarter" — without editing raw config or code. It does not:
- **own the actions themselves** — a rescan, an export generation, a report are each some other API's own domain logic; this sub-API only owns *when* a user wants one to run.
- **own job dispatch mechanics** — once a scheduled trigger fires, the actual work routes through Background Workers' existing per-job classification/routing (its own deep-dive §3) like any other job; this sub-API doesn't reimplement that.
- **allow scheduling arbitrary code** — see §4, a curated allowlist is a hard requirement, not a convenience.
- **belong exclusively to Background Workers' own conceptual domain** — Background Workers exists specifically for maintenance-sweep work arising from V3's own evolving taxonomy/models/rules (its own deep-dive §1); Task Scheduler is a genuinely separate, broader concept (anything a user wants to automate) that happens to reuse the same dispatch substrate rather than inventing a second one. Worth stating plainly since conflating the two is exactly the mistake that put this feature in the wrong document in the first place.

---

## 2. Package layout

```
core/task_scheduler/
  __init__.py
  contracts.py             # UserScheduledTask, ScheduleTrigger, error types
  registry.py                 # the curated schedulable-action allowlist — see §4
  triggers/
    __init__.py
    base.py                     # ScheduleTrigger Protocol
    in_app_timer.py
    supervisor_wake.py            # the correct default — see §5
    os_native.py
  errors.py
```

---

## 3. Data model — where schedule data actually lives

```python
@dataclass(frozen=True)
class UserScheduledTask:
    task_id: str
    created_by: str              # user_id — scoped per-user, not a system-wide setting
    action: str                    # a registered, schedulable action name — see §4
    action_params: FrozenDict
    cron_expression: str
    enabled: bool
```
Lives in the owning user's own Persistence database — this is per-user preference data, structurally the same category as any other user-owned setting, not infrastructure this sub-API stores itself.

---

## 4. The curated schedulable-action allowlist — a hard safety requirement

Only a specific, registered set of actions are exposed to this mechanism at all (a full rescan trigger, a specific export generation, a specific report) — **never arbitrary code, never a raw cron-to-shell-command mapping.** Each schedulable action registers itself here explicitly (the same discipline `docs/templates/new_provider.md` already asks of every other pluggable capability in this project), so the actual allowlist is visible and reviewable in one place, not implicit in whatever happens to read `action` as a string and dispatch on it unsafely.

---

## 5. The trigger mechanism — a Provider Registry, and the bug this design corrects

An earlier version of this design assumed the dispatching service reads `UserScheduledTask` rows at its own in-process interval check — but Supervisor's own sleep/wake capability (`v3-deepdive-38-supervisor.md` §5) means that service could genuinely be *asleep* when a scheduled task comes due, and a sleeping process can't run its own polling loop to notice its own schedule. Fixed with a swappable Provider Registry (`docs/PRINCIPLES.md` §1.2):
```python
class ScheduleTrigger(Protocol):
    async def register_trigger(self, task: UserScheduledTask) -> None: ...
    async def deregister_trigger(self, task_id: str) -> None: ...
```
- **`InAppTimerTrigger`** — correct only when the dispatching service is guaranteed awake (`SleepPolicy.NEVER`) or sleep/wake is disabled entirely. Simplest, not safe to assume as the only path.
- **`SupervisorWakeTrigger`** — the correct default once a service can sleep: delegates to Supervisor's own schedule-wake mechanism (its deep-dive §5.4, the same lightweight always-resident timer that already wakes `SCHEDULED_ONLY`-class services like Ingestion for its daily poll) rather than reinventing a second wake mechanism.
- **`OSNativeSchedulerTrigger`** — an optional third provider for self-hosted power users who want OS-level scheduling guarantees independent of this project's own process model — Windows Task Scheduler, a Linux `systemd` timer or `cron` entry — structurally available behind the same interface, not the default.

Once a trigger fires, dispatch routes through Background Workers' existing per-job classification/routing (its own deep-dive §3) — only *what wakes the dispatch* is this sub-API's own concern, never the dispatch mechanism itself.

---

## 6. The Interface screen

A dedicated settings screen (Interface API's own future deep-dive) — genuinely one of the enumerated custom-screen exceptions (`docs/PRINCIPLES.md` §1.4), since "build a cron expression interactively" doesn't reduce to a flat list of labeled menu actions the way most of the TUI does. A friendly schedule-builder (pick a frequency, a time, which registered action) generates the underlying `cron_expression` rather than asking a non-technical owner to write raw cron syntax by hand.

---

## 7. gRPC surface

```protobuf
service TaskSchedulerService {
  rpc CreateScheduledTask(CreateTaskRequest) returns (TaskResponse);
  rpc UpdateScheduledTask(UpdateTaskRequest) returns (TaskResponse);
  rpc DeleteScheduledTask(DeleteTaskRequest) returns (DeleteResponse);
  rpc ListScheduledTasks(ListTasksRequest) returns (ListTasksResponse);
  rpc ListSchedulableActions(ListActionsRequest) returns (ListActionsResponse);   // the allowlist itself, for the Interface screen to populate its picker
}
```

---

## 8. Asyncio

Thin orchestration over Persistence reads/writes and trigger registration — the same I/O-bound, no-compute-of-its-own shape as every other thin-orchestration API in this corpus (Tool Call, Account Guardian). Nothing further to add on the concurrency side. **Forward-compatibility check, explicit rather than assumed**: no new native/C-extension dependency is introduced by this sub-API — `croniter` or an equivalent pure-Python cron-expression parser is the only real addition, no compute-bound work anywhere in scope for free-threading to help with, and nothing here needs its own new Telemetrees tracking entry beyond that one small, pure-Python parsing dependency itself.

---

## 9. Testing hooks
- **Allowlist enforcement test**: confirms `action` values outside the registered allowlist are rejected at creation time, never silently accepted and failing later at dispatch.
- **Sleep/wake correctness test**: a task scheduled against a service currently asleep under `SupervisorWakeTrigger` correctly wakes and dispatches — the concrete validation of §5's entire fix.
- **Cron-expression validation test**: malformed expressions rejected at the API boundary, not surfaced as a confusing failure at the next expected run time.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Per-tier limits on scheduled task count, resolved: yes, tier-dependent caps exist as a real mechanism, exact numbers left to Billing's own tier definitions.** The cap itself (a config-driven per-tier limit) is designed here; the specific numbers for whichever tier names/limits Billing ultimately settles on aren't this document's own call to make.
- **Missed-run behavior, resolved: waits for the next scheduled occurrence, never catches up immediately.** Simpler and more predictable than a catch-up run, and avoids a real, if unlikely, failure mode — an extended outage causing a flood of simultaneous catch-up jobs the moment the instance comes back, competing for resources right when the system is already recovering from downtime.
- **`OSNativeSchedulerTrigger`'s actual registration mechanics, resolved: genuinely separate from `StartupRegistrar`, no integration needed beyond sharing the same underlying pattern.** Both are real Provider Registry entries using similar per-OS primitives, but they register fundamentally different things — "launch this program at boot" versus "run this specific task at a specific time" — and don't actually need to interoperate with each other beyond both existing behind the same kind of swappable interface this project applies consistently.
