# Blockers: what stalled and crashed Receipt-System V3

This file records what went wrong in the V3 coding sessions, why it happened, and what to do differently. It was written before the repo was wiped for a fresh start, so none of this knowledge is lost.

Sources: the `origin/main` history of this repo (through `0ae4d63`, 2026-08-05), the project audit notes, and the commit log of the unpushed local branch `claudi/wave-2-hardware-validation` on the developer's PC (about 50 commits, subjects only; those commits are not on GitHub).

## Summary

Most stalls and crashes came from a small set of causes:

1. **Silent failures.** Errors were swallowed or returned as "empty success," so the system looked fine while doing nothing.
2. **Environment and install assumptions.** The installer, dependency pins, and Python version choices were tested only on the developer's own machine and broke on fresh installs.
3. **Blocking and resource exhaustion under load.** Cold starts, OpenCL and worker-pool limits, and LLM prefill cost stalled or crashed the pipeline when several receipts ran at once.
4. **Path and URL construction.** The same double-slash bug came back three times in model provisioning.
5. **Process and version hygiene.** Version bumps and CI gates lagged behind the code, and CI guards were added only after a problem had already shipped.

## Blockers in detail

### 1. Silent failures that looked like hangs or "nothing happened"
- **What:** An empty OCR `engines` request ran zero engines and returned `merged_text=""` with no error (`cef8246`). Every receipt in a full-fleet concurrent test landed in Persistence with empty OCR text.
- **What:** Content Security denied every upload forever on a fresh install because no scan provider was registered. The fail-closed default was correct, but nothing wired the documented default in (`d700a40`).
- **What:** The installer silently stalled all ~30 service venvs when `python` resolved to Python 3.15, where `grpcio` has no prebuilt wheel (`73eeadf`).
- **Why:** Fail-closed and degrade-gracefully defaults were implemented, but the failure paths were not observable.
- **Lesson:** Every empty or defaulted result needs an explicit path. Add a CI guard against silent `except` blocks early (the repo later added one in `29664d3`). Test each default end to end on a fresh install, not just in unit tests.

### 2. Installer and environment assumptions
- **What:** `winsdk>=1.0` matched nothing, and `grpcio` version floors were too low for the checked-in generated stubs (`f87335f`, `45bc5a8`).
- **What:** `bootstrap.py` needed `frozendict` on the bare pre-venv interpreter, and the default Python was not pinned (`924bcb1`, `e4aee9a`).
- **What:** The first-run install was tested on the developer's machine, then broke on other machines, including a `.gitignore` rule that silently excluded `core/logs/` from git (`886f85b`, `2fc461e`).
- **Why:** Dependencies and install paths were implicit, and nothing exercised a clean machine.
- **Lesson:** Pin the Python version and minimum dependency floors explicitly. Run a clean-machine install in CI on each supported platform. Add a check that no source package is ignored by git.

### 3. Platform-specific bugs (Windows and ClamAV)
- **What:** `NamedTemporaryFile` kept its handle open during the scan, so `clamscan` failed with `WinError 32` on every Windows scan (`40eb641`).
- **What:** The Supervisor's default listen port fell inside Windows' dynamic-port-exclusion range (`27c3c87`).
- **Lesson:** Test on the real target OS. Do not hold file handles across a call to an external process.

### 4. Startup order and process boot
- **What:** Fleet boot order was wrong twice: `execution_core` started before its peers, then `ingestion` started before `execution_core` (`4b8d493`, `62ca866`).
- **What:** The boot ownership was inverted (Supervisor and TUI both claimed boot), fixed over several commits in the `x00.00.68`–`x00.00.69` range.
- **Lesson:** Write the process topology down once and enforce it in tests. Ownership of boot must have exactly one owner.

### 5. Message size and transport limits
- **What:** gRPC's default 4 MiB message ceiling broke the direct-upload path, and the same limit was then found in Persistence's blob write path (`45cff5e`, `8155ef3`).
- **Lesson:** Set explicit size limits for every gRPC channel at design time, and test with real receipt files, which are large scans.

### 6. Under-load stalls and crashes
- **What:** A cold-start stall appeared after the worker-pool change, fixed by warming presets at startup (`e220683`, local only).
- **What:** An OpenCL resource-exhaustion crash appeared under concurrent-receipt Preprocessing load (`e0af136`, local only).
- **What:** A single unprovisioned preset killed the whole process inside `warm_up()` (`a0db7cb`, local only).
- **What:** OCR readings sent to the LLM had an unbounded prefill cost, fixed by capping distinct readings (`cdd7259`).
- **Lesson:** Load-test with several concurrent receipts before calling a pipeline done. Bound every per-request cost (prefill tokens, OCR readings, workers). A missing model must degrade one preset, not kill the process.

### 7. Path and URL construction (the repeated bug)
- **What:** The double-slash bug in the flat-repo model download URL was fixed three separate times. The `variant=""` case built `.../variant//file` and Hugging Face returned 404 (`30ee90c` and two earlier fixes).
- **Why:** Each fix patched one call site. The URL builder itself was never centralized, so the next call site reintroduced the bug.
- **Lesson:** Build outbound URLs and filesystem paths in one helper. When a bug appears at a second call site, fix the helper, not the caller.

### 8. Model integration against real APIs
- **What:** Two `onnxruntime-genai` API-shape bugs in the vision/multimodal path (`8fc4574`).
- **What:** A false `cpu` variant hint for `phi4-vision`, when no CPU-ready variant exists in the real repo (`d3e3ec0`).
- **What:** DirectML timing was unstable and OpenVINO needed an explicit CPU device type (`45e2cdd`).
- **Lesson:** Verify model and runtime API shapes against the installed library version with a real run before building on them. Record hardware-specific findings in the docs at the time they are found.

### 9. Process and version hygiene
- **What:** `PROGRAM_VERSION` lagged by 15 commits, and the PR template and checklist check were not always enforced (`1ab977b`, `7fb975e`).
- **What:** The forward-compatibility gate was broken for an entire wave before anyone noticed (`e265cce`).
- **What:** Required CI checks failed on PR #9 and had to be fixed inside the same PR (`7fb975e`).
- **Lesson:** Run the full CI gate locally before pushing. A gate that is broken is worse than no gate, because it trains people to ignore red.

### 10. Scope and sprawl
- **What:** Many sub-APIs were scaffolded in one phase with no real implementation behind them. Phase 1 scaffolded 31 of 32 Core APIs, and the Logs API had no package for a whole phase (`886f85b`).
- **What:** Work was pushed through many long single-purpose branches (`claudi/wave-0`, `wave-1`, `wave-2`, `phase-1.5`, `phase-2`) with several unmerged, and the working tree on the developer's PC drifted from `origin/main` by about 50 commits.
- **Lesson:** Ship one vertical slice end to end before scaffolding the next. Merge or delete branches on a fixed cadence. Keep the local working tree and `origin` in sync at least daily.

## Local-only work

The developer's PC has an unpushed branch, `claudi/wave-2-hardware-validation`, with roughly 50 commits (from `7fb975e` through `30ee90c`). They are not on GitHub and are not affected by this cleanup. If that work is still wanted, push it to a separate branch before deleting the local folder.

## Standing rules that held up

- Fail closed on security checks, and degrade gracefully on everything else.
- Errors are data at API boundaries, not exceptions across gRPC.
- Real features get their own sub-API document.
- Test with real receipts on a fresh install, not only in mocks.
