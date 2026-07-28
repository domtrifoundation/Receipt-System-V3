# V3 Deep Dive: Background Workers API

**Companion files:** all prior deep-dives — this is the generic execution substrate several of them already assumed exists (Ingestion's Webhook Subscription Manager renewal, Setup's dependency install, Tool Call's idle-worker tool category).

**Status:** Twelfth deep-dive session, corrected in a later revision. **A real violation of `docs/PRINCIPLES.md` §0 (the V2 Rule) was caught and fixed here, not just a wording issue**: an earlier version of this document's entire "job list" was V2's own idle-job inventory with new V3 API names attached to each line — never an independently-designed V3 job model at all. §4 below is the actual fix: Background Workers' real reason to exist, reasoned fresh from what V3's *own* architecture requires (evolving taxonomy, evolving models, evolving rules), not from what V2 happened to have. §7 keeps the V2 inventory as exactly what it honestly is — a precedent check confirming nothing V2 already learned the hard way got silently dropped — clearly separated from and never confused with V3's own design again.

---

## 1. Scope & boundary

Background Workers exists because of a genuinely V3-native architectural fact, independent of anything V2 did: **this project's own design lets the system's rules, taxonomy, and models keep improving after data has already been processed** — Architect's registry evolves (a vendor's TIN gets corrected, a new flag type gets added), Update API/Proving Grounds promotes better OCR engines and Inference models to a channel over time, Reconciliation's own check inventory can grow (the still-open ATP check, for instance). Every one of these creates the same structural gap: **data processed correctly under yesterday's rules can silently fall behind today's**, and nothing else in this system's design notices that on its own. Background Workers is the generic scheduling/dispatch substrate that exists to close that gap — domain APIs register work (both the fresh maintenance-sweep triggers this creates, §4, and unrelated one-off jobs), this API decides *how and when* it runs. It does not:
- **own any business logic** — a job that checks VAT math or backfills a field belongs to Reconciliation/Review-Flagging's own domain logic; this API only provides the scheduling/execution mechanism that logic runs on top of, already stated plainly in file 03's own correction ("clarified as the generic execution substrate that domain APIs run on top of, not a competing owner of business logic").
- **own LLM-driven background work as a separate subsystem** — an idle-time job that needs the LLM is just a batch Inference API call (prompt + tool calls) dispatched through the normal Inference contract, not a distinct "AI worker" concept living in this API.
- **run a separate worker-server process** — non-LLM workers run in-process within Execution Core's own process (thread/process pool), per file 03's explicit decision; this API is a contract and scheduling logic, not new infrastructure to deploy and monitor separately.
- **decide what counts as "worth a sweep"** — §4's trigger taxonomy defines *when* Background Workers notices something changed; whether a given change actually warrants re-touching historical data is each domain API's own judgment call (Architect deciding a taxonomy change is sweep-worthy, Reconciliation deciding a new rule should run against old data too), never assumed automatically by this API.

---

## 2. Package layout

```
core/background_workers/
  __init__.py
  contracts.py            # JobRegistration, JobClass, ScheduledJob, IdleWindow, error types
  registry.py                # which jobs are registered, by which domain API
  scheduler.py                 # routes each job to the right pool per its declared class — see §3
  idle_detection.py              # "is the system otherwise quiet right now" — see §4
  errors.py
  metrics.py
```

---

## 3. Per-worker classification — routing is a real requirement, not a detail
File 02's own Concurrency Model table states this as a design requirement, not an afterthought: **each registered job declares its own nature, and the scheduler routes accordingly** — an async event loop task for I/O-bound jobs, a thread-pool dispatch for native/GIL-released work, a process-pool dispatch for genuine CPU-bound pure-Python work. This mirrors the same `run_in_executor` pattern already used across OCR, Preprocessing, and Execution Core's own deep-dives for dispatching blocking work off the event loop — worth being precise that Inference API's own equivalent is a partial cousin, not an identical instance: its heavy blocking work (actual generation) now runs in a genuinely separate process, not via `run_in_executor`, though `run_in_executor` still wraps the lighter IPC hop to that process (its own deep-dive §6.1). Background Workers is the place the general "route each job by its declared nature" pattern gets applied *generically*, for any domain API's registered job, rather than each API hand-rolling its own dispatch.
```python
class JobClass(str, Enum):
    ASYNC_IO = "async_io"           # network calls, disk waits — runs directly on the event loop
    NATIVE_THREAD = "native_thread"   # C/C++-backed blocking calls — thread-pool dispatch
    CPU_PROCESS = "cpu_process"        # genuine CPU-bound pure Python — process-pool dispatch

@dataclass(frozen=True)
class JobRegistration:
    job_id: str
    owning_api: str            # which domain API registered this — for observability/debugging, not enforcement
    job_class: JobClass
    idle_only: bool              # see §4
    interval_seconds: int | None   # None = event-triggered, not timer-based
```

---

## 4. Idle-time execution class — yields to active foreground work
An idle-time job only runs when the system is genuinely otherwise quiet — concretely, when Execution Core reports no `OPEN` or `CLOSING` runs currently in progress (its own deep-dive §3's `RunState`) for whichever scope the job cares about (a given user's own idle time, or system-wide idle time for global maintenance jobs). This directly matches V2's own proven behavior (idle-time jobs yielding to active foreground scans) — worth keeping exactly, since it's a genuinely good, already-validated design, not something needing rederivation.
```python
async def is_idle(scope: str = "global") -> bool:
    """Checked by the scheduler before dispatching any idle_only job.
    Queries Execution Core's current run states for the relevant scope —
    Background Workers doesn't track run state itself, it asks the API
    that owns it."""
```

### 4.1 Timer-based "next due" visibility — a real, worth-keeping UX detail from V2
V2's dashboard could show which timer-based idle job would fire next and in how many seconds, even though the actual fire time also depends on `idle_only` conditions and the job's own finder returning real work — an approximate, best-effort estimate, not a hard guarantee. Worth preserving as a genuinely useful piece of operator-facing transparency for Interface API's own future "Workers" status view, rather than leaving background work as an opaque black box.

---

## 5. Task Scheduler
**Extracted to its own dedicated document, `v3-deepdive-39-task-scheduler.md`** — its scope is system-wide (any registered schedulable action across any API), not specific to this API's own maintenance-sweep domain, so it never belonged as a subsection here. Uses this API's per-job classification/routing (§3) as its execution substrate, nothing more.

---

## 6. The consolidated job registry — the actual V3 job list, corrected and substantially expanded

**This section did not exist in an earlier version of this document.** What existed instead was a table mapping V2's own job names to which V3 API now owns each concept — real, useful precedent-checking, but never an independently-designed V3 job list, and presenting it as one was a real violation of `docs/PRINCIPLES.md` §0 caught late. This section is the actual fix: every job this API's registry genuinely dispatches, compiled from every deep-dive that mentions one, cross-checked against a real prior inventory pass rather than reconstructed from memory. **Revised again after a direct challenge that this list looked too short given how much a system this size genuinely has to do in the background** — that challenge was right: three jobs were already fully designed in their own owning documents but never actually connected to this table, and five more genuinely didn't exist anywhere yet. §6.4 covers the newly-designed ones; §6.5 states plainly that this list is expected to keep growing.

### 6.1 Jobs with a fully resolved design today

| Job | Owner | Trigger shape |
|---|---|---|
| Webhook Circadian renewal | Ingestion (`v3-deepdive-35-webhook-subscription-manager.md` §3) | Proactive, ahead of known channel expiry |
| Release directory garbage collection | Update API (`v3-deepdive-24-update-deployment-api.md` §3) | Interval, keeps current + 1 prior floor |
| Dependencies Warden polling | Telemetrees (`v3-deepdive-37-dependencies-warden.md` §4) | Interval (`poll_interval_hours`), per tracked dependency |
| Archive Sync execution | Persistence (`v3-deepdive-32-archive-sync.md` §4) | Idle-time, per-user cursor-resumable |
| Reconciliation's real check inventory | Reconciliation (`v3-deepdive-17-reconciliation-api.md` §4) | Idle-time sweep, dispatched per §6.3 below |
| **Log retention purge** | Logs (`v3-deepdive-18-logs-api.md` §5) | Interval, past `retention_days` |
| **Capability drift periodic check** | Health (`v3-deepdive-20-health-api.md` §4.2) | Interval, `capability_drift.periodic_check_interval_hours` |
| **Bulk migration dispatch** | Migration (`v3-deepdive-23-migration-api.md` §4) | Event-triggered, a schema-version bump, `CPU_PROCESS` class |
| **Stage-checkpoint purge** | Execution Core (`v3-deepdive-10-execution-core-api.md` §14) | Interval, 30-day retention past a run reaching `WRITTEN` |
| **Standalone integrity spot-check** | Disaster Recovery (`v3-deepdive-33-disaster-recovery.md` §9) | Interval, weekly, small random sample |
| **Wikidata vendor directory poll** | Architect (`v3-deepdive-26-architect-api.md` §3.2) | Interval, owner-configurable, 30 days default |

The last three rows are the direct result of the challenge above — each already had a real design in its own owning document explicitly saying "this is a Background Workers job," but none of the three had ever actually been added to this table. Worth naming as its own lesson: a job being correctly designed at its source doesn't mean it's actually discoverable as part of the whole system's background workload unless it's also listed here — this table is the only place someone would look to answer "what does this program do while nobody's watching," and a design that only exists at its own owning document doesn't answer that question by itself.

### 6.2 Jobs still genuinely open — real gaps, not resolved by this correction, tracked at their actual owning document
- **Rescue** (Execution Core/Review-Flagging territory) — one more LLM-assisted attempt at a quarantined/failed receipt before requiring human review. **Now has a real registry entry here** (it didn't before — this was the actual gap, not the ordering question itself, which was already tracked): the job exists in principle, dispatchable once Reconciliation's own still-open ordering question (its deep-dive §8 — rescue-first vs. flag-immediately) is resolved. Not schedulable yet for that reason, not because it was forgotten.
- **Telemetrees' signal-compilation-into-issue step** — takes a raw diagnostic signal (a failed dependency test, a flagged capability drift) and compiles it into a well-formed GitHub Issue. **A real, previously-unconnected gap, now closed**: this is event-triggered, not interval-scheduled — `JobRegistration.interval_seconds: None` (§2's own contract already supports this, it was simply never used for this purpose) — registered here as an event-triggered job fired by whichever API produced the signal (Health's capability-drift finding, Proving Grounds' failed test), rather than each of those APIs needing its own separate issue-filing logic.
- **Notification delivery retry** — Notifications' own deep-dive (its §7) flags outbound-channel delivery failure handling as unresolved; whatever retry policy eventually gets decided there will need a real registered job here, not designed yet since the policy itself isn't.

(Curate — resolved, no longer open. A real self-cleaning mechanism now exists, `v3-deepdive-40-temporal-learning.md` §7, and has its own registry entry in §6.4 below.)

### 6.3 A real, concrete gap this correction found: a missing Reconciliation check
Cross-checking §6.1's Reconciliation row against Reconciliation's own actual nine-check inventory found a real, clean miss — **"orphaned/missing archive-reference detection" was in the original job-inventory discussion and never made it into Reconciliation's own design at all**, not renamed, not folded into something else, just absent. Added as a tenth check to Reconciliation's own deep-dive (`v3-deepdive-17-reconciliation-api.md` §4.10) as part of this same correction — a lighter-weight, ongoing idle-time sweep distinct from Disaster Recovery's own full-instance verification pass (its deep-dive §4), catching the same category of problem (a receipt row with no corresponding blob, or vice versa) at routine operating scale rather than only during a catastrophic-recovery scenario.

### 6.4 Five jobs that genuinely didn't exist anywhere — designed here for the first time

| Job | Owner | Trigger shape | Design |
|---|---|---|---|
| Curate (self-cleaning learned-vendor pass) | Architect | Idle-time, `CPU_PROCESS`-adjacent (near-duplicate scoring) | `v3-deepdive-40-temporal-learning.md` §7 |
| Expired session cleanup | Auth & Tenancy | Interval | See below |
| Break-glass grant cleanliness sweep | Auth & Tenancy | Interval | See below |
| Account deletion grace-period sweep | Account Guardian | Interval | See below |
| Blob backup spot-verification | Persistence | Interval, small random sample | See below |

**Expired session cleanup**: Auth's own session store (its deep-dive §5.2) checks `expires_at` at validation time — a request against an expired session correctly fails — but nothing was ever designed to actually *delete* those rows once they're no longer useful even for a failed-lookup check, meaning the table grows forever. A straightforward interval job (daily is a reasonable starting cadence) deletes sessions past their `expires_at` by some safety margin.

**Break-glass grant cleanliness sweep**: Auth's own deep-dive (§6.3) already states this precisely — "the sweep still exists for cleanliness (marking visibly-expired rows), but the actual security boundary never depends on the sweep having run recently" — but never gave it an actual registered job. Registered here: an interval sweep marking grants past their `expires_at` as visibly expired, purely for a clean audit/reporting view, never load-bearing for the actual access-control decision (which is correctly checked live, §6.3 there).

**Account deletion grace-period sweep**: Account Guardian's own `DeletionStage.GRACE_PERIOD`/`BILLING_HOLD` state machine (its deep-dive §6.3) never specified what actually checks whether a grace period has elapsed and advances a request to `PROCESSING` — without this job, a deletion request would sit in `GRACE_PERIOD` forever regardless of how much time passed. An interval sweep checking every non-cancelled deletion request against its own `grace_period_ends_at`, advancing eligible ones to `PROCESSING` (or `BILLING_HOLD` if Billing still needs to resolve first, exactly as that document's own state machine already specifies) — this job is also what actually performs the real blob/data purge once `PROCESSING` completes, resolving what an earlier pass loosely called "blob store retention-purge enforcement" without ever connecting it to a concrete mechanism.

**Blob backup spot-verification**: Disaster Recovery's own verification (`v3-deepdive-33-disaster-recovery.md` §4) only ever runs *during an actual restore* — there was never a routine, ongoing check that B2/Storj backups are genuinely retrievable before a real disaster forces the question. A periodic job (weekly is a reasonable starting cadence) pulls a small random sample of recently-backed-up blobs from each backup target and confirms they're actually retrievable and hash-correct, reusing Disaster Recovery's own per-blob verification logic at sample scale rather than a full-instance walk — catching a silently-broken backup target long before an actual disaster would.

### 6.5 This list will keep growing, and that's expected — a standing instruction, not a gap to apologize for
A system with this many moving parts (32 Core APIs, a substantial and still-growing set of sub-APIs) genuinely has an open-ended amount of background maintenance work, and this document isn't claiming to have found the last of it. **Any new job — whether designed by a future session, a contributor, or Claude Code working from `docs/templates/new_provider.md`'s own registration discipline — gets added to §6.1's table in the same PR that designs it**, the same "extract it, don't bury it" discipline `docs/PRINCIPLES.md` §1.8 already establishes for oversized features, applied here to background jobs specifically: a job design that only exists at its own owning document and never makes it into this consolidated table isn't actually discoverable as part of the system's background workload, which defeats the point of this table existing at all.

---

## 7. V2 precedent check — explicitly not the V3 design, kept only to confirm nothing V2 already learned got silently lost
**This is the section that was previously, wrongly, presented as if it were §6's job registry.** It is not a design — it is a completeness check against V2's own real job list, the same category of exercise `docs/PRINCIPLES.md` §0 explicitly permits (analyze V2 to know what to fix or avoid) but never treat as a substitute for independently designing V3's own thing, which §6 above now actually does.

**Carries forward, same job, correct V3 owner identified:**
- VAT math check, TIN format check, date plausibility check, account outlier check, items-vendor mismatch check → Reconciliation API's domain logic (its own deep-dive, still flagged as needing a real design pass — file 01), each surfacing a Review/Flagging flag from Architect's registered taxonomy on a hit, scheduled here as `CPU_PROCESS` or `ASYNC_IO` jobs depending on whether the check itself needs a DB round-trip or pure computation.
- Vendor/branch learning, vendor group fix → Architect API's `temporal_learning` submodule (`v3-deepdive-40-temporal-learning.md`), staged through the same contribution-review pipeline Tool Call API's vendor-write tools already reference.
- Field backfill, audit trail backfill, row audit → Execution Core's checkpoint/re-processing mechanism (its own deep-dive §6), triggered here on an idle timer rather than V2's own polling loop.
- Archive sync, archive audit → Persistence's Archive Sync sub-capability (`v3-deepdive-32-archive-sync.md`), scheduled here.

**Don't carry forward — the underlying V2 data structure they targeted no longer exists:**
- **"Empty folder cleanup"** — V2's folder-based archive model doesn't exist in V3's content-addressable blob store at all; there are no empty folders to clean up. Genuinely obsolete, not relocated.
- **"Transactions sheet sync"** — assumed a continuously-live, directly-synced Excel workbook; V3's Excel is generated on-demand from canonical SQLite data (Persistence's Export Framework, already corrected in the Ingestion deep-dive's earlier session), never a background-synced artifact. Obsolete for the same reason V2's `excel_write_row`/`excel_query` tools were dropped in Tool Call API's own deep-dive (§3.2 there).
- **"Duplicate flag"** — V2 detected duplicate rows after the fact via a background scan; V3's content-hash idempotency (Execution Core §4) catches an exact duplicate *before* it's ever written, structurally, not via a periodic sweep looking for ones that already got through. A *near*-duplicate check (same physical receipt, different bytes) is a genuinely different, harder problem not addressed by either V2's or V3's current mechanism — worth flagging as still-open rather than assuming either version solves it.
- **"AI idle attention"** — V2's open-ended "let the LLM look around for anything useful to fix" job. Given Tool Call API's own deep-dive already mapped V2's specific idle-worker *tools* (`find_next_quarantined_receipt`, etc.) to their correct V3 owners individually, a separate open-ended catch-all job on top of those specific, scoped ones risks duplicating work already covered — worth confirming this isn't needed as its own thing rather than assumed necessary by default (§9).

---

## 8. Asyncio, free-threading, and profiling
This API's own code (the scheduler, the idle-check, the registry) is thin coordination logic — genuinely async by nature (checking Execution Core's run state, dispatching to the right pool). The actual compute/blocking work happens inside whatever job a domain API registered, already classified and routed per §3 — this API doesn't need its own separate free-threading story beyond correctly routing each job to the pool its own declared class calls for. Profiling-wise, the interesting question is pool utilization under real idle-time load, which is Health API's live-diagnostic territory (consistent with every other orchestration-shaped API in this batch) rather than a GIL-contention bench question specific to this API itself.

---

## 9. Testing hooks — a real gap found during a pre-development sweep
- **Consecutive-failure guard test**: confirms a job failing five times in a row genuinely auto-disables and surfaces an `ATTENTION`-level entry (§9's own resolved guard), rather than retrying indefinitely.
- **Idle-scope test**: confirms a per-user-scoped job checks that specific user's idle state while a system-wide job doesn't check any — the distinction §9 resolves is only real if something enforces it.
- **Registry-completeness test**: confirms every job registered in code appears in §6.1's own table and vice versa — the concrete enforcement of §6.5's extensibility clause, which is otherwise honor-system.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **General-purpose "look around for anything useful to fix" job, resolved: no, not needed.** Tool Call API's own specific idle-worker tools already cover the concrete cases V2's `ai_idle_attention` targeted — locking in the leaning rather than leaving it formally unconfirmed. An open-ended catch-all job on top of already-scoped ones would risk duplicating work already covered, not adding real value.
- **Near-duplicate receipt detection, given a real design rather than left flagged indefinitely.** Content-hash idempotency (Execution Core §4) only catches byte-identical uploads; a near-duplicate (the same physical receipt photographed twice, slightly different crop/lighting/angle) needs perceptual similarity, not exact matching. Resolved: a perceptual image hash (`dHash` or `pHash`, both cheap to compute and widely available via `imagehash` or a hand-rolled implementation over the already-normalized base image) computed alongside the exact content hash during Format Normalization (`v3-deepdive-42-format-normalization.md`), with near-duplicate candidates (hash distance under a threshold) surfaced as a Review/Flagging flag rather than auto-merged — the same "find it, don't silently decide for the user" discipline every other check in this project follows. Registered as a real job in §6.1's own table, idle-time class.
- **Per-user vs. system-wide idle scope, resolved.** Jobs touching per-user-scoped resources (archive sync, session cleanup for that user) check that specific user's own idle state — no reason for one user's active session to block another user's unrelated idle-time work. Genuinely system-wide jobs (log retention, Dependencies Warden polling) don't check any user's idle state at all, since they don't touch per-user resources in the first place — the distinction tracks directly with whether a job's own target is per-user or system-wide, not a separate axis needing its own resolution.
- **Permanently-failing registered job retry guard, resolved with a real mechanism.** Every registered job tracks a consecutive-failure counter; after 5 consecutive failures, the job auto-disables and surfaces a real, staff-visible `ATTENTION`-level Logs entry (the same severity tier Health API's own capability-drift findings use, `v3-deepdive-20-health-api.md` §4) rather than retrying forever or failing silently — re-enabling requires an explicit staff action after investigating, never automatic. This is the concrete gap that mattered most once §6.4 added five new interval jobs with real failure modes of their own (a stuck blob-verification job, say) — this guard is what catches one of them going permanently bad rather than quietly retrying into the void.
- **Exact cadences for §6.4's new jobs** — reasoned starting placeholders (daily for session cleanup, weekly for blob backup spot-verification), locked in as the shipping defaults; real operational data can tune them later, not a blocking gap in the meantime.
