# V3 Deep Dive: Proving Grounds (Update API sub-API)

**Parent API:** `v3-deepdive-24-update-deployment-api.md` §6. **Companion files:** `v3-deepdive-37-dependencies-warden.md` (the trigger signal), `v3-deepdive-11-setup-api.md` §1 (shares this same testing/download infrastructure for initial installs).

**Status:** Sub-API deep-dive, full treatment.

---

## 1. Scope & boundary

Proving Grounds owns **automated candidate testing** — running a real bench workload against a dependency bump or a code-release channel candidate before it's promoted anywhere. It does not:
- **decide what to test** — Dependencies Warden surfaces "this exists now" (a new dependency release, a flagged pre-release feature); a human judgment call decides what's program-important enough to test (file 02 rule #8); Proving Grounds only executes the test once asked.
- **own the bench suite's own design** — reuses each affected API's own bench workload (OCR's, Inference's, Preprocessing's) as already specified in their own deep-dives' testing-hooks sections, never a separate testing methodology invented here.

---

## 2. Package layout

```
services/update/proving_grounds/
  __init__.py
  contracts.py             # TestCandidate, TestResult, error types
  test_runner.py               # dispatches to the affected API's own bench suite
  download.py                    # shared dependency-download infrastructure — see §3
  promotion.py                     # gates channel promotion on a passing result
  errors.py
```

---

## 3. Shared download infrastructure — one implementation, two consumers
This is the concrete download machinery Setup API's own initial dependency installation (its deep-dive §1) relies on, not duplicated — multithreaded/async downloads, including HF token-auth support for gated models (file 03's own explicit hardening requirement, directly relevant to Inference API's preset resolution, its deep-dive §4.4). One implementation serves both "install this for the first time" (Setup) and "download this candidate to test it" (Proving Grounds) use cases.

---

## 4. Test execution and promotion gating
```python
async def test_candidate(candidate: TestCandidate) -> TestResult:
    """Downloads the candidate dependency version into an isolated test
    environment, then dispatches whatever bench workload actually
    exercises it (an OCR engine bump runs OCR's own bench suite per its
    deep-dive's testing hooks, an ONNX Runtime bump runs Inference's) —
    never a generic smoke test standing in for real exercise of the
    actual code path affected."""

async def gate_promotion(channel: str, candidate: TestCandidate, result: TestResult) -> bool:
    """A candidate only promotes to a channel if its test result passes
    the same health-check discipline a code release's own rollout
    cutover already uses (Update deep-dive §5's Supervisor logic) — not
    a separate, looser bar just because it's a dependency bump rather
    than a code change."""
```

---

## 5. Asyncio
Downloads and bench-dispatch orchestration are I/O-bound; the actual bench workload's own concurrency model is whatever that workload's own deep-dive already specifies (Update's own parent-level conclusion, its deep-dive §7) — Proving Grounds doesn't impose its own concurrency shape on tests it triggers.

---

## 6. gRPC surface

```protobuf
service ProvingGroundsService {
  rpc TestCandidate(TestCandidateRequest) returns (TestResultResponse);
  rpc GetTestHistory(HistoryRequest) returns (TestHistoryResponse);
}
```

---

## 7. Testing hooks
- **Isolation test**: confirms a failing candidate test never affects the currently-running stable instance — the same crash-isolation principle already established as a structural architecture property (file 02), applied here to dependency testing specifically.
- **Promotion-gate bypass test**: confirms there's no code path that promotes a candidate to a channel without a passing `TestResult` on record.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **Test environment isolation mechanism, resolved: containerization (Docker).** Genuinely lighter-weight than a fully separate machine while still providing real isolation a shared venv doesn't — the same tool this project already reaches for elsewhere (the Nominatim self-hosting guide, `docs/SELF_HOSTED_NOMINATIM.md`), not a new pattern introduced just for this.
