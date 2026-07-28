# V3 Deep Dive: Test Orchestration (Agent Control's own sub-API)

**Companion files:** `v3-deepdive-55-agent-control-api.md` (the parent API this belongs under), `v3-deepdive-38-supervisor.md` (the crash-isolation runner needs to coordinate with real process lifecycle), `v3-deepdive-33-disaster-recovery.md` (its own restore test is a real consumer of this), `docs/PRE_STABLE_BENCH_VALIDATION.md` (the bench-suite runner is how that whole checklist actually gets executed, not a separate mechanism), `docs/testing/TOOLKIT.md` (the existing, broader optional-tools reference this sub-API makes MCP-callable rather than replaces).

**Status:** New sub-API, extracted per `docs/PRINCIPLES.md` §1.8 — its own real protocol (multiple test-runner implementations), its own data model (`TestRun`/`TestResult`), and cross-references from at least four other APIs' own testing-hooks sections meets the threshold cleanly.

---

## 1. Scope & boundary

Test Orchestration owns making genuinely complex tests — ones that can't reasonably be "just run a script and check the exit code" — callable through Agent Control's own MCP server and headless CLI, so Claude Code (or any other agent/automation) can run them, get a structured result back, and reason about what happened. It does not:
- **replace `docs/testing/TOOLKIT.md`'s own existing tools** — the bench suite, profiling, fuzzing, and load-testing tools already described there still exist and still work the way they already do; this sub-API is a new, structured *calling convention* on top of them, not a second implementation.
- **decide what a test result means** — a `TestResult` reports what happened (pass/fail, structured detail); whether that's acceptable is still the caller's (a human, or Claude Code interpreting the result) own judgment.
- **replace ordinary unit tests.** A simple, fast, mockable unit test stays exactly what it already is — `pytest`, run directly, no orchestration needed. This sub-API exists specifically for the tests that are hard to run reliably any other way.

---

## 2. Package layout
```
core/agent_control/test_orchestration/
  __init__.py
  contracts.py                 # TestRun, TestResult, error types
  runners/
    __init__.py
    base.py                        # TestRunner protocol
    bench_suite_runner.py             # wraps the OCR/Preprocessing/Inference bench suites
    crash_isolation_runner.py           # deliberately kills a worker process, observes recovery
    pipeline_integration_runner.py        # submits a real test receipt, tracks it through the full pipeline
    environment_reset_runner.py             # wipes a test tenant/database to clean state between runs
```

---

## 3. The `TestRunner` protocol — a real Provider Registry, the same pattern as everything else
```python
class TestRunner(Protocol):
    async def run(self, spec: TestSpec) -> TestResult: ...
    async def is_available(self) -> bool: ...   # a crash-isolation test isn't meaningful against a remote/sandboxed session, say
```

### 3.1 `BenchSuiteRunner` — the actual execution mechanism for `docs/PRE_STABLE_BENCH_VALIDATION.md`
Calls into the bench suite entries each pipeline-stage API's own "Testing hooks" section already defines (OCR §11, Preprocessing §12, Inference §11, Matching §8) — this runner doesn't reimplement those tests, it's the structured, MCP-callable front end onto them. **Inherits the real-receipt-scans requirement directly** (`docs/PRE_STABLE_BENCH_VALIDATION.md`'s own opening rule) — this runner refuses to proceed against a fixture directory it can detect as synthetic/generated (§6 below has the real mechanism for this), rather than silently running against whatever's on disk.

### 3.2 `CrashIsolationRunner` — real process-kill-and-observe testing, genuinely hard to script reliably otherwise
```python
async def run(self, spec: TestSpec) -> TestResult:
    """Deliberately sends SIGKILL to a named service's own worker
    process (not the parent service process — the isolation being
    tested), then observes: (a) the parent service's own health over
    the following N seconds, (b) whether a subsequent request to that
    service triggers a clean reload rather than hanging, (c) whether
    any other service was affected at all. This is exactly the
    Inference API crash-isolation test its own deep-dive §10 already
    specifies — this runner is what actually executes it in a
    repeatable, MCP-callable way instead of a bespoke one-off script
    someone has to remember how to run correctly."""
```
Coordinates with Supervisor's own real process-lifecycle knowledge (`v3-deepdive-38-supervisor.md`) to identify the correct process to kill — never a blind `pkill` by name, which risks killing the wrong process on a system running multiple services.

### 3.3 `PipelineIntegrationRunner` — submits a real receipt, tracks it through every stage
```python
async def run(self, spec: TestSpec) -> TestResult:
    """Submits spec.test_receipt_path through Ingestion, then polls
    Execution Core's own real GetRunStatus RPC (v3-deepdive-10-
    execution-core-api.md §12) until the run reaches WRITTEN or a
    terminal failure state, recording which stage (if any) failed and
    Historian's own narrative for what happened at each stage along
    the way. The genuinely useful thing this gives an agent that a
    bare script wouldn't: a single structured result summarizing an
    entire multi-service, multi-second pipeline run, rather than the
    agent needing to manually poll and cross-reference logs itself."""
```

### 3.4 `EnvironmentResetRunner` — clean state between test runs, without hand-rolled teardown scripts
Wipes a specifically-designated test tenant's own data back to a known clean state — never touches anything outside that tenant, never usable against a real production tenant (a hard, checked guard, not a documented expectation alone).

---

## 4. gRPC surface
```protobuf
service TestOrchestrationService {
  rpc RunTest(RunTestRequest) returns (TestResult);
  rpc GetTestResult(GetTestResultRequest) returns (TestResult);   // for a long-running test, poll separately rather than block
  rpc ListAvailableRunners(Empty) returns (ListRunnersResponse);    // so an agent can check is_available() before attempting one that won't work in its current environment
}
```

---

## 5. MCP tools exposed through Agent Control
```python
TEST_ORCHESTRATION_TOOLS = [
    "run_bench_suite", "run_crash_isolation_test",
    "run_pipeline_integration_test", "reset_test_environment",
    "get_test_run_result", "list_available_test_runners",
]
```
All `TEST_EXECUTION`-categorized (`v3-deepdive-07-tool-call-api.md` §4, resolved as its own real category rather than folded into `DEV_OBSERVABILITY`) — genuinely distinct from pure-read tools given each one here triggers a real action with real side effects, not just observes existing state.

---

## 6. A real, important safeguard: detecting synthetic fixtures, not just trusting a naming convention
**Directly connects to a real gap found while designing this**: `docs/PRE_STABLE_BENCH_VALIDATION.md` tells Claude Code to ask for real receipt scans rather than generate fakes — but that instruction alone relies on the agent actually following it, with no structural check behind it. `BenchSuiteRunner` adds a real one: a lightweight heuristic check (file metadata patterns consistent with camera/scanner capture — real EXIF data, realistic file-size variance across a batch — versus the uniform, metadata-sparse signature a programmatically generated image tends to have) that flags a fixture directory as *suspicious*, not as a hard block (the heuristic isn't reliable enough to be a hard gate, and a false positive shouldn't block real work) — but a flagged directory surfaces a clear warning in the `TestResult` itself, so a human reviewing results has a real, structural signal to check rather than relying purely on trust that the instruction was followed.

---

## 7. Asyncio, free-threading, and profiling
Orchestration itself is I/O-bound (polling, coordinating). `CrashIsolationRunner`'s own process-signal-and-observe logic briefly touches OS-level process management, not compute-bound in the sense that needs profiling attention — same "not applicable in the Python sense" carve-out already used for the Cloudflare Worker components elsewhere in this corpus, stated explicitly rather than silently skipped.

---

## 8. Testing hooks
- **Wrong-process-killed test**: confirms `CrashIsolationRunner` never targets a process other than the one `spec` actually named, even under a realistic multi-service-running scenario.
- **Tenant-isolation test for `EnvironmentResetRunner`**: confirms a reset against test tenant A never touches tenant B's own data, and confirms the hard guard against ever targeting a real production tenant actually holds, not just documented.
- **Synthetic-fixture-detection false-positive-rate check**: given §6's own heuristic isn't a hard gate, worth a real check that it doesn't flag real, legitimate photographed receipts often enough to become noise nobody reads anymore.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **The exact heuristic for §6's synthetic-fixture detection** — a real starting approach is described, not a finalized, tuned algorithm; needs real calibration against both genuine synthetic images and real photographed receipts before its false-positive rate is actually known.
- (Whether `TEST_EXECUTION` becomes its own real Tool Call category — resolved, no longer open. It is, `v3-deepdive-07-tool-call-api.md` §4.)
- **Long-running test result storage/retention** — `GetTestResult`'s own polling model assumes results persist somewhere between the triggering call and a later poll; the actual storage mechanism (a lightweight table, or Persistence's own general write path) isn't picked here.
