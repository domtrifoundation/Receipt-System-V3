# V3 Deep Dive: Telemetrees API

**Companion files:** every single prior deep-dive — each one deferred at least one dependency-tracking item to "Telemetrees ownership." This session designs the mechanism they were all pointing at.

**Status:** Twenty-eighth and final deep-dive session of this batch. File 02's own rule #8 already establishes the philosophy (day-0 dependency support as a tracked discipline, not a one-time policy statement) — this session designs Dependencies Warden as the concrete system that makes it real.

---

## 1. Scope & boundary

Telemetrees owns **continuous dependency monitoring** via its Dependencies Warden sub-API — tracking every registered dependency's release activity (stable *and* pre-release), surfacing changelogs and compatibility-status changes to developers automatically. It does not:
- **decide whether to adopt a new version** — that's Proving Grounds' job (Update deep-dive §6): Dependencies Warden surfaces "this exists now," Proving Grounds actually tests it against real bench workloads before promotion to any channel.
- **track every dependency uniformly** — different dependencies need different tracked facts (a plain version bump vs. a free-threading-support flag vs. an upstream GitHub issue's open/closed status), a real design requirement worked through in §3, not assumed to be one-size-fits-all.

---

## 2. Package layout

```
core/telemetrees/
  __init__.py
  contracts.py             # TrackedDependency, TrackedFact, ReleaseEvent, error types
  dependencies_warden/         # Sub-API
    __init__.py
    registry.py                 # which dependencies are tracked, and what facts about each
    poller.py                     # scheduled checks — PyPI/GitHub releases, upstream issues
    changelog_surface.py            # what gets shown to developers, and how
  errors.py
  metrics.py
```

---

## 3. Tracked facts aren't uniform — the real design requirement every prior deep-dive's references implied
**Dependencies Warden's own full treatment (the actual monitoring mechanism built on this fact taxonomy) is in `v3-deepdive-37-dependencies-warden.md`.** Summary below.
Collecting every "Telemetrees ownership" note across this whole batch of deep-dives shows tracked dependencies actually need **different kinds of tracked facts**, not just "is there a new version":
```python
class TrackedFactKind(str, Enum):
    RELEASE_VERSION = "release_version"           # standard: new stable/beta/alpha release
    FREE_THREADING_SUPPORT = "free_threading_support"   # a boolean/status flag, not a version number
    UPSTREAM_ISSUE_STATUS = "upstream_issue_status"        # tracks a specific GitHub issue's open/closed state

@dataclass(frozen=True)
class TrackedDependency:
    name: str
    fact_kinds: tuple[TrackedFactKind, ...]
    upstream_issue_refs: tuple[str, ...]    # e.g. "opencv/opencv#27933" — see §3.2
```

### 3.1 The full inventory this session closes the loop on
Collected directly from every prior deep-dive's own deferred items, not invented fresh here — this is the concrete registry `Dependencies Warden` starts with:
- **Free-threading support, per-dependency**: `onnxruntime`/`onnxruntime-genai` (OCR + Inference, shared), `opencv-python` (Preprocessing), `rapidfuzz`/`numpy` (OCR/Matching), `pymupdf`/`pillow-heif` (Ingestion — `pillow-heif` already confirmed to have declared support, a genuinely different starting position worth tracking as a positive data point, not just a gap), `authlib`/`cryptography` (Auth), the PyPI `frozendict` package's own compatibility posture against the 3.15 builtin's exact semantics (Tool Call API deep-dive §6).
- **Specific upstream issue tracking**: `opencv/opencv#27933` and `opencv-python#1051` (the free-threaded-wheel blocker, Preprocessing deep-dive §8.2/§9.2) — a genuinely different tracking shape than "is there a new version," since the thing being tracked is one specific issue's resolution state, not a release stream.
- **Model/preset currency**: RapidOCR's bundled ONNX models potentially lagging PaddleOCR's own newer model generations (OCR deep-dive §9) — a "is our vendored copy stale relative to upstream's own newer releases" check, a third distinct shape again. **ClamAV's virus-definition database freshness** (Content Security deep-dive §5.1) is the same shape of check applied to a security-critical dataset rather than a model — a stale definitions database is a silent security gap distinct from the `pyclamd` package itself being outdated, worth its own tracked fact rather than folded into ordinary release-version monitoring.
- **Python interpreter version itself**: 3.14t/3.15 adoption readiness — tracked as a dependency like any other per file 02's rule #8, not a one-time migration decision.
- **Regulatory-value currency**: whether BIR has revised the SLSP threshold values Export Framework's own `slsp_summary.py` provider uses (`v3-deepdive-31-export-framework.md` §4.1/§10) — a genuinely distinct fact kind again, since what's being tracked here isn't a software release or a security dataset but a government-set numeric threshold that can change independent of anything in this project's own control.

### 3.2 Why upstream issue tracking is a distinct fact kind, not folded into release monitoring
A plain release-version poller (checking PyPI for a new `opencv-python` version) would never surface "the free-threaded-wheel blocker is still open" — that fact lives on a GitHub issue, not in a release changelog, and could resolve either *with* or *independent of* a version bump. Worth its own polling mechanism (`poller.py` checking specific issue URLs' state via GitHub's API) rather than assuming release monitoring alone covers every kind of "should we revisit this decision" signal a prior deep-dive flagged.

---

## 4. Surfacing to developers — the actual point of tracking at all
Tracking that never reaches anyone is pointless. `changelog_surface.py`'s job: when a tracked fact changes (a new release, a free-threading flag flipping, a tracked issue closing), surface it somewhere a developer session will actually see it — the natural integration point is a Claude Code session's own context (a checked-in, regularly-updated summary file Dependencies Warden maintains) rather than only a dashboard a human has to remember to check, given this project's own development model leans heavily on LLM-assisted sessions picking up exactly this kind of "here's what changed since you last worked on this" signal.

---

## 5. Asyncio
Polling PyPI/GitHub APIs and checking issue states is straightforward network I/O — no different in shape from any other I/O-bound API in this batch. No compute-bound work of its own.

---

## 6. gRPC surface

```protobuf
service TelemetreesService {
  rpc GetTrackedDependencies(TrackedDepsRequest) returns (TrackedDepsResponse);
  rpc GetChangelog(ChangelogRequest) returns (ChangelogResponse);
}
```

---

## 7. Config

```
telemetrees:
  poll_interval_hours: 24
  tracked_dependencies:
    - name: opencv-python
      fact_kinds: [release_version, free_threading_support]
      upstream_issue_refs: ["opencv/opencv#27933", "opencv-python#1051"]
    - name: onnxruntime-genai
      fact_kinds: [release_version, free_threading_support]
    - name: pillow-heif
      fact_kinds: [release_version, free_threading_support]
    - name: frozendict
      fact_kinds: [release_version]
```

---

## 8. Testing hooks
- **Issue-state-change detection test**: confirms a tracked GitHub issue transitioning from open to closed actually surfaces as a changelog event, not silently missed by a poller only watching for version bumps.
- **Multi-fact-kind coverage test**: confirms every dependency in the §3.1 inventory actually has the right `fact_kinds` registered, not defaulting to plain `release_version` tracking for something that needed `free_threading_support` specifically — the concrete mechanism that keeps this registry from silently drifting out of sync with what every prior deep-dive actually asked for.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Changelog surfacing format/location, resolved: `docs/CHANGELOG.md`, Keep a Changelog format.** The standard, well-established convention rather than a bespoke format — updated automatically whenever a tracked fact changes state (a new dependency version, a resolved upstream issue), the same event that already triggers Telemetrees' own internal tracking update also appends the human-readable entry, one write path rather than two things to keep in sync manually.
- **Polling frequency, locked in at 24 hours as the reasoned default.** Real data on how quickly tracked facts actually change in practice can tune this later; daily is a sensible starting cadence for the kind of slow-moving facts (dependency releases, upstream issue resolution) this tracks, not a blocking gap.
