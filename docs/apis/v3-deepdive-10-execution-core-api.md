# V3 Deep Dive: Execution Core API

**Companion files:** all prior deep-dives — this is the API that actually calls OCR, Preprocessing, Inference, Matching, Geo, and Persistence in sequence, so every prior deep-dive's gRPC contract is a direct dependency here.

**Status:** Tenth deep-dive session, prioritized per request alongside Setup API. Unlike most APIs in this plan, Execution Core already has an unusually thorough Decisions Log entry (file 03) from a dedicated session that read V2's `processor.py`/`main.py` in full — this deep-dive formalizes that record into the standard package/contract/concurrency shape rather than re-deriving it from scratch, since the underlying design work is already sound and already grounded in real V2 evidence.

---

## 1. Scope & boundary

Execution Core owns the **run** — the actual pipeline "running loop": scheduling (per-user/global concurrency limits), sequencing (Ingestion → Preprocessing → OCR → Matching → Geo → Inference → Persistence write → Review/Flagging on low-confidence → Notifications on completion), and applying the active tier profile's knobs to a given run. It does not:
- **launch processes** — that's the Supervisor's job (file 01 #21), a structurally separate, more conservative component that exists precisely so the thing deciding "should Execution Core's own release be swapped" is never Execution Core itself.
- **implement any pipeline stage's own logic** — Execution Core calls OCR/Preprocessing/Inference/etc.'s own gRPC contracts; it never reimplements a fragment of what any of them do internally.
- **decide UI/interaction concerns** — V2's `daemon_loop` literally instantiated the menu system, keyboard listener, and dashboard inside the same loop that ran the pipeline; V3's process separation makes that coupling structurally impossible to reintroduce, since Interface only ever reaches Execution Core through its gRPC contract.

---

## 2. Package layout

```
services/execution_core/
  __init__.py
  contracts.py            # Run, RunState, PipelineStage, StageCheckpoint, error types
  service.py                 # thin gRPC service implementation
  scheduler.py                 # per-user/global concurrency, run lifecycle, debounce coalescing — see §5
  pipeline.py                    # stage sequencing, per-receipt orchestration — see §4
  checkpointing.py                # per-stage resumable-retry mechanism — see §6
  retry_policy.py                  # bounded retry with escalation — see §7
  state_machine.py                  # explicit run/receipt states — see §3
  watchdog_hooks.py                   # fine-grained Health API Watchdog kicks — see §9
  errors.py
  metrics.py
```

---

## 3. Data contracts and the explicit state machine

```python
class RunState(str, Enum):
    WAITING_FOR_TRIGGER = "waiting_for_trigger"
    OPEN = "open"                 # accepting new file intake — see §5.2
    CLOSING = "closing"             # finalizing writes, no new intake
    RUNNING = "running"              # legacy-compat alias not used — OPEN/CLOSING already capture the real states a run is in
    PAUSED = "paused"
    SHUTTING_DOWN = "shutting_down"

class ReceiptStage(str, Enum):
    INGESTED = "ingested"
    PREPROCESSED = "preprocessed"
    OCRD = "ocrd"
    MATCHED = "matched"
    GEOD = "geod"
    INFERRED = "inferred"
    WRITTEN = "written"             # terminal — Persistence write + Historian event committed

@dataclass(frozen=True)
class StageCheckpoint:
    receipt_id: str
    run_id: str
    stage: ReceiptStage
    completed_at: datetime
    stage_output_ref: BlobRef | FrozenDict | None   # whatever that stage produced — an image_ref for OCR, a structured result for Inference, etc. FrozenDict per the project-wide policy (Tool Call API deep-dive §6), for stage outputs that are dict-shaped rather than a blob reference.

@dataclass(frozen=True)
class Run:
    run_id: str
    user_id: str
    state: RunState
    opened_at: datetime
    closing_started_at: datetime | None = None
    receipt_count: int = 0
```
Worth being explicit about the `RUNNING` entry above: file 03's own phrasing lists "paused/running/waiting-for-trigger/shutting-down" as the four states, but a run that's actually processing is always more precisely `OPEN` or `CLOSING` (§5.2) — "running" isn't a fifth distinct state, it's what OPEN/CLOSING collectively mean once a run has actually started. Keeping the enum honest about this (rather than having both `RUNNING` and `OPEN`/`CLOSING` as if they were independent) avoids an ambiguous state a future implementer would have to guess the relationship between.

---

## 4. Content-hash-based idempotency, restated precisely
Directly validated by V2's own `_file_fingerprint()` — deliberately not mtime-based, since cloud sync (Drive/OneDrive/Dropbox) touches mtime on unchanged bytes, which would cause false reprocessing. **Two distinct concerns, tracked separately, never conflated**:
- **Blob-level dedup** (same SHA-256 hash = same blob) — Persistence's own concern, already covered in the Ingestion/Preprocessing deep-dives' hash-on-original-bytes discussion.
- **Run-level idempotency** (has this content already been fully processed into a DB row) — Execution Core's own concern: before starting the pipeline for a given `image_ref`, check whether a `WRITTEN`-stage checkpoint already exists for its content hash; if so, skip entirely rather than reprocessing a receipt that's already fully in the system.

---

## 5. Scheduling: concurrency limits and debounce coalescing

### 5.1 Two independent concurrency knobs
```python
class RunScheduler:
    def __init__(self, per_user_limit: int, global_limit: int):
        self._per_user_semaphores: dict[str, asyncio.Semaphore] = {}
        self._global_semaphore = asyncio.Semaphore(global_limit)

    async def acquire(self, user_id: str) -> AsyncContextManager:
        """Acquires both the per-user and global semaphores — a run
        can't start unless there's capacity on both axes. Per-user
        defaults to 1 (doubles as rate limiting, file 03); global
        protects shared OCR/Inference hardware resources regardless of
        how many distinct users are asking for capacity at once."""
```
Every OCR/Preprocessing/Inference call already threads `run_id`/`user_id` context through per each of those APIs' own deep-dives — this scheduler is where that context actually originates.

### 5.2 Debounce-with-max-wait, and the open/closing lifecycle
```python
# scheduler.py — sketch
class RunCoalescer:
    def __init__(self, debounce_window_s: float, max_wait_s: float):
        self._window = debounce_window_s
        self._max_wait = max_wait_s

    async def on_trigger(self, user_id: str, new_files: list[SourceFile]) -> None:
        """First trigger for a user with no open run starts a new Run in
        OPEN state and begins the debounce window. Each subsequent
        trigger arriving within the window resets it — but the ceiling
        (max_wait_s from the run's own open time, not from the most
        recent trigger) forces a transition to CLOSING regardless, so a
        continuous trickle of arrivals never blocks the run forever.
        A late file arriving after the ceiling has already forced
        CLOSING starts a new run instead of joining this one — the
        ceiling is a real boundary, not advisory."""
```
This lives in Execution Core's scheduler, not Ingestion's Webhook Subscription Manager (which only ever emits "new file available" events, file 01) — Execution Core is the one API that decides how those raw events batch into an actual run. `CLOSING` finalizes the batch's Persistence writes (including Historian's event log) and triggers the completion notification; Excel is never generated as part of a run at all, it's an on-demand export entirely decoupled from run lifecycle (Persistence's own deep-dive territory).

---

## 6. Per-stage checkpointing — the one genuinely novel technique this session's decision record already identified
V2 retried a whole receipt from scratch on any failure, wasting already-completed expensive steps (especially LLM inference) on retry. **Fix, already decided in file 03, formalized here**: the same principle behind durable workflow-execution systems (Temporal, Prefect, Dagster) adopted as a *technique*, not a framework dependency — consistent with this project's repeated preference for borrowing an idea without taking on the operational weight of the system that popularized it (same reasoning already applied to Tool Call's custom orchestrator over LangChain).
```python
# checkpointing.py — sketch, extended per Historian's own deep-dive (v3-deepdive-29-historian.md §5)
async def run_stage(run_id: str, receipt_id: str, stage: ReceiptStage, fn: Callable) -> Any:
    existing = await get_checkpoint(receipt_id, stage)
    if existing is not None:
        return existing.stage_output_ref    # already done — skip straight to the next stage
    result = await fn()
    await write_checkpoint(run_id, receipt_id, stage, result)   # via Persistence's normal write path — Historian-logged automatically
    await historian.emit_narrative(run_id, receipt_id, stage, result)   # new — see below
    return result
```
A retry after crash/failure resumes from the last completed stage, not from `INGESTED` again — the expensive stages (OCR corroboration, Inference generation) never redo work that already succeeded.

**This wrapper is also the emission chokepoint for Historian's narrative track** (its own deep-dive §5), not a coincidence but a deliberate reuse: since every pipeline stage's call and output already flow through `run_stage()` for checkpointing purposes, extending it to also call `historian.emit_narrative()` means every stage automatically produces its own quantized, webapp-displayable narrative entry ("OCR (Tesseract) read this receipt at 87% confidence," one per engine plus the corroborated outcome) without needing OCR, Preprocessing, Inference, Matching, or Geo/Address (`v3-deepdive-16-geo-address-api.md` — the `GEOD` stage's own owning API, a cross-reference genuinely missing until a full pipeline walkthrough found it) to individually remember to call Historian themselves — each stays focused on its own domain logic, narrative summarization lives in one small module (`historian/narrative/summarizers.py`) that knows how to turn each stage's own result type into a readable line, and coverage is structural (every stage passes through this one wrapper) rather than dependent on N different APIs' own discipline.

---

## 7. Bounded retry with escalation
V2's `.failed_attempts.json` sidecar + quarantine-after-max-attempts (the real motivating bug: "one bad scan produced 57 identical warnings in a single session") becomes, in V3, **escalation to a Review/Flagging flag** ("processing failed repeatedly") after N failed attempts, rather than a physical `failed/` folder move that doesn't fit the folderless, content-addressable blob model at all.
```python
async def attempt_stage(run_id: str, receipt_id: str, stage: ReceiptStage, fn: Callable, max_attempts: int) -> Any:
    attempts = await get_attempt_count(receipt_id, stage)
    if attempts >= max_attempts:
        await review_flagging.create_flag(receipt_id, "processing_failed_repeatedly", details={"stage": stage, "attempts": attempts})
        return None   # this receipt stops retrying — a human resolves it via the flag, not an infinite loop
    try:
        return await run_stage(run_id, receipt_id, stage, fn)
    except Exception:
        await increment_attempt_count(receipt_id, stage)
        raise
```

---

## 8. Fine-grained, responsive cancellation
V2's real bug — a 156-receipt EXTREME-mode run kept going for minutes after a stop request — is fixed by checking the cancellation signal **per-receipt within a run**, not just between runs. Concretely: the per-receipt orchestration loop in `pipeline.py` checks a `run.state == RunState.SHUTTING_DOWN` (or a dedicated cancellation flag) at the top of every receipt's processing, not only at the top of the whole run — a stop request takes effect within one receipt's processing time, not the whole batch's.

---

## 9. Watchdog integration and config hot-reload
Kicks Health API's Watchdog (its own deep-dive, not yet written) at multiple points within the loop — start of each cycle and throughout any idle wait — matching V2's own proven wiring, so a genuinely hung run is caught, not just a hung idle loop. Config changes apply to the *next* run without a full service restart, tracked via a reload counter for observability (so a support/debug session can confirm "yes, this run definitely picked up the config change made five minutes ago," not just assume it did).

---

## 10. Asyncio, free-threading, and profiling

### 10.1 Where asyncio is load-bearing
Execution Core is fundamentally an **orchestrator of other APIs' async gRPC calls** — every pipeline stage call (Ingestion, Preprocessing, OCR, Matching, Geo, Inference, Persistence) is itself already async per each of those deep-dives, so this API's own hot path is `await`-all-the-way-down coordination logic, not a new source of blocking calls. The scheduler's semaphores (§5.1) and the debounce coalescer (§5.2) are pure `asyncio` primitives, no executor dispatch needed anywhere in this API's own code.

### 10.2 Free-threading
Minimal relevance for the same reason as every thin-orchestration-layer API in this batch (Tool Call, Account Guardian, Notifications) — no compute-bound pure-Python hot path exists here to begin with; this API's job is coordinating *other* APIs' work, not doing work of its own.

### 10.3 Profiling
The one genuinely valuable profiling target specific to this API is **run-level latency breakdown** — how much of a run's total wall-clock time is spent in each pipeline stage, across many concurrent runs — which is squarely Health API's live-diagnostic territory (its own future deep-dive) rather than a `py-spy`/Tachyon GIL-contention question, consistent with every other I/O-bound orchestration API's own conclusion in this batch.

---

## 11. gRPC surface (`.proto` sketch)

```protobuf
service ExecutionCoreService {
  rpc StartRun(StartRunRequest) returns (RunResponse);              // triggered by direct upload, scanner finalize, or a webhook-driven event
  rpc GetRunStatus(RunStatusRequest) returns (stream RunProgress);    // server-streaming — live progress to Interface/webapp
  rpc CancelRun(CancelRunRequest) returns (RunResponse);
  rpc PauseRun(PauseRunRequest) returns (RunResponse);
}

message RunProgress {
  string run_id = 1;
  string state = 2;                 // waiting_for_trigger | open | closing | paused | shutting_down
  int32 receipts_total = 3;
  int32 receipts_completed = 4;
  string current_stage_summary = 5;  // e.g. "12 of 40 receipts at OCR stage"
}
```
Server-streaming for `GetRunStatus` directly answers V2's "results only show at end of run" bug (file 03's own IPC-architecture reasoning for choosing gRPC in the first place) — live progress, not a single response at the end.

---

## 12. Config surface

```
execution_core:
  concurrency:
    per_user_limit: 1
    global_limit: 8
  debounce:
    window_seconds: 10
    max_wait_seconds: 120
  vendor_match:
    corroboration_policy: always          # always | below_threshold | never — see v3-deepdive-15-matching-api.md §5.2
    below_threshold_bar: 0.75               # only meaningful when corroboration_policy is below_threshold
  retry:
    max_attempts_per_stage: 3
  cancellation_check_interval: per_receipt   # not configurable to anything coarser — this is a hard requirement, not a tunable
```

---

## 13. Testing hooks
- **Checkpoint-resume test**: a simulated crash mid-pipeline (after `OCRD`, before `MATCHED`), confirming a retry resumes from `MATCHED` onward without re-running OCR or Inference — the concrete validation of §6's entire value proposition.
- **Debounce ceiling test**: a continuous trickle of triggers that never lets the debounce window elapse naturally, confirming the run still transitions to `CLOSING` once `max_wait_seconds` is hit — direct validation of §5.2's "never waits forever" claim.
- **Per-receipt cancellation test**: a run cancelled mid-batch, confirming the currently-in-flight receipt finishes (or aborts) within one receipt's processing time, not the whole batch's — the concrete fix for V2's 156-receipt bug.
- **Escalation test**: a stage forced to fail `max_attempts_per_stage` times, confirming a Review/Flagging flag is created and no further retry attempts occur.

---

## 14. Open questions for this deep-dive (logged, not guessed at)
- **Exact debounce/max-wait default values** (§12): reasonable, reasoned starting placeholders — locked in as the shipping default; a bench pass once real traffic data exists can tune them, not a blocking gap in the meantime.
- **Whether `PAUSED` is owner/staff-initiated only, or a client can pause their own run — resolved: a client can pause their own run; owner/staff can pause any run.** No real reason to restrict a user from pausing their own in-progress work — the broader admin capability (pausing anyone's run) is the one that needs the role-check wiring via Auth & Tenancy, not the self-service case.
- **Stage-output storage cost for `StageCheckpoint.stage_output_ref`, resolved with a real retention policy.** Intermediate stage outputs serve their purpose (resume-without-repeating) only while a run is still in progress — once a run reaches `WRITTEN`, they're purged after a 30-day retention window (long enough to debug something recently completed, short enough not to accumulate indefinitely), registered as a real Background Workers job (its own consolidated registry, `v3-deepdive-12-background-workers-api.md` §6.1) rather than left to grow unbounded. Historian's own narrative track (its deep-dive §5) is what preserves the durable, human-readable record of what happened — the raw intermediate blobs were never meant to be that record.
