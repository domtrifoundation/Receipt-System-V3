# V3 Deep Dive: Update/Deployment API

**Companion files:** `v3-deepdive-11-setup-api.md` (shares the bootstrap/distribution model's origin), `v3-deepdive-20-health-api.md` (Watchdog's version tracking gates rollout cutover here), `v3-deepdive-38-supervisor.md` (the actual arbiter this API's own releases get consumed by — a real package-layout bug caught and fixed in this revision, see §2).

**Status:** Twenty-fourth deep-dive session, revised. Already extensively specified across file 01/02/03 — this session formalizes the release-directory model, Keymaster licensing, and Proving Grounds into the standard deep-dive shape. Supervisor itself was corrected out of this document's own package layout during a later double-check pass — it never belonged nested here, see §2 and §5.

---

## 1. Scope & boundary

Update/Deployment owns **no-downtime releases** — named, multi-channel release directories, health-gated cutover, and (via Proving Grounds) automated dependency-update testing. It does not:
- **launch or supervise processes, decide which release is active, or drive rollback** — that's Supervisor's own job entirely (its own dedicated deep-dive, `v3-deepdive-38-supervisor.md`), a structurally separate process living outside every release clone, specifically so the thing deciding "should this release swap happen" is never the release being swapped in. This API's own job stops at *producing* a cloned, ready release directory — what happens to it after that is Supervisor's call, not this API's.
- **validate self-hosted license keys itself** — Keymaster (§4) is a genuinely separate, closed external system; this API only calls out to it before a clone attempt.
- **decide rollout health criteria** — Health API's own status/diagnostic layer (its deep-dive) is what actually gates cutover; this API consumes that signal, doesn't define what "healthy" means.

---

## 2. Package layout — corrected: Supervisor removed, it was never structurally valid here

```
services/update/
  __init__.py
  contracts.py             # ReleaseDirectory, Channel, KeymasterToken, error types
  release_manager.py          # clone-into-named-directory, garbage collection
  keymaster_client.py           # licensing gate for self-hosted clones — see §4
  proving_grounds/            # Sub-API — dependency-update testing — see §6
    __init__.py
    test_runner.py
    changelog_watcher.py
  errors.py
  metrics.py
```
**A real bug caught during a double-check pass, not just a stale reference: an earlier version of this package layout nested `supervisor/` as a subdirectory here.** That's structurally impossible given `docs/PROCESS_TOPOLOGY.md` §1's own established model — every Core API, including this one, runs as its own process from inside a versioned release clone. Supervisor is the one thing that has to live *outside* every clone permanently (`v3-deepdive-38-supervisor.md` §2) — nesting it inside `services/update/`'s own package would mean Supervisor's code gets replaced every time Update API's own release gets cloned into a new directory, which is exactly the self-replacement problem Supervisor's own separate update mechanism exists to avoid (that document's §4.1). Fixed: Supervisor has its own top-level package, entirely outside this one.

---

## 3. Named, multi-channel release directories
`<version>_<commit-hash>` directories, garbage-collected past a retention window (always keeping the current release plus at least one prior for rollback safety) rather than a fixed slot count. Every update is a genuinely fresh `git clone` into a new named directory — never a pull, never in-place mutation, which is what makes concurrent multi-channel operation possible at all (a release directory being actively served is never being mutated underneath its own running process). **In hosted multi-tenant mode, multiple channels are a standing state, not a transient rollout window** — since each user picks their own channel (LTSC/Stable/Beta/Alpha, plus an owner-only Latest-Commit channel), several release directories can be genuinely, simultaneously serving real traffic at once as ongoing normal operation.

**Every clone this API performs also runs through the same `strip_development_content()` step Setup API's own first-clone finalize routine uses** (Setup deep-dive §4.1) — a shared function, not a second, independently-maintained stripping list, reading the persistent `dev_mode` flag set once at first install. A normal-mode instance stays free of `docs/`/`tests/`/CONTRIBUTING.md bloat across every subsequent update, not just the initial install; a developer-mode instance keeps the full corpus across every update the same way.

---

## 4. Keymaster — self-hosted licensing, structurally separate for a real reason
Modeled as a subscription gating *updates*, not the software's ability to keep running once cloned — the code repo must be private (a public repo would have nothing to intercept), and this API calls out to Keymaster for a short-lived, scoped GitHub token before each clone attempt.
```python
async def clone_new_release(channel: str, target_version: str) -> ReleaseDirectory:
    token = await keymaster_client.get_scoped_clone_token()   # fails open — see below
    return await _git_clone(token, target_version, target_dir=f"releases/{target_version}_{commit_hash}")
```
**Fail-open, always**: a Keymaster outage or check error never blocks the already-running instance — only blocks fetching something *new*. A lapsed license simply means the next clone fails at GitHub's own auth step; the currently-running instance and its data are entirely unaffected. Instance-bound activation (a random instance ID generated on first run, deliberately not a hardware fingerprint — hardware changes are legitimate, and a fingerprint-based lockout risks false-positive customer lockout) tracks which installation(s) a key is activated on, allowing legitimate transfers while flagging rapid instance-switching as the pattern actual key-sharing would look like. Full enforcement-philosophy detail (rate-limiting the validation endpoint, generic rejection messages that never leak *why* a key failed, encryption at rest) already specified in file 02 — this API's own scope is just the clone-gating integration point, not Keymaster's internal design.

---

## 5. Supervisor
**Full treatment in `v3-deepdive-38-supervisor.md`** — the multi-clone arbiter, Boot Sequence, Supervisor's own two-phase self-update mechanism, and the new sleep/wake capability for idle services. This API's own relationship to it is narrow and one-directional: `release_manager.py` produces a cloned, ready release directory; Supervisor decides what to do with it. Nothing about Supervisor's own internals lives in this document anymore.

---

## 6. Proving Grounds sub-API — automated dependency-update testing
**Full treatment in `v3-deepdive-36-proving-grounds.md`.** Summary below.
Shared with Setup API's own initial dependency installation (its deep-dive §1) — one testing/download infrastructure, not duplicated. Consumes Telemetrees' Dependencies Warden pre-release/changelog monitoring (its own future deep-dive) as the trigger signal — a newly detected dependency version doesn't get adopted blindly, it runs through the actual bench workload it affects (an OCR engine bump runs OCR's own bench suite, an ONNX Runtime bump runs Inference's) before being promoted to any channel, gated the same health-check discipline as a code release. Multithreaded/async model and dependency downloads, including HF token-auth support for gated models (file 03's own explicit hardening requirement) — this is the concrete download infrastructure Inference API's own preset-resolution (its deep-dive §4.4) relies on.

---

## 7. Asyncio and profiling
Release-directory operations and health-check polling are I/O-bound — file 02's own table already classifies this API as async orchestration. Dependency-bump tests inherit whatever concurrency model the bench workload they're running actually has (OCR's, Inference's, Preprocessing's own classification) — this API doesn't impose its own concurrency shape on the tests it triggers.

---

## 8. gRPC surface

```protobuf
service UpdateService {
  rpc CloneRelease(CloneRequest) returns (ReleaseDirectoryResponse);
  rpc GetActiveChannels(ChannelRequest) returns (ChannelListResponse);   // which channels have configured/active usage — distinct from Supervisor's own GetActiveRelease, which answers "which specific directory is live for a channel right now"
}
```
**`TriggerRollback` removed from this surface during the same double-check pass that fixed §2's package layout** — rollback means changing which release directory is *active*, a decision that belongs entirely to Supervisor (its own deep-dive §3.3, §6), not to the API that merely produces cloned directories in the first place. An earlier version of this document defined the RPC in both places, a real duplicate-responsibility bug, not just redundant documentation — worth being explicit that it's gone from here, not just silently dropped.

---

## 9. Testing hooks
- **Fail-open verification**: a simulated Keymaster outage during an active instance's normal operation confirms zero impact on already-running services — direct validation of §4's core safety claim.
- **Garbage-collection safety test**: confirms the currently-active release and at least one prior are never collected, even under aggressive retention-window settings.
- (Boot Sequence dependency-order testing now lives in `v3-deepdive-38-supervisor.md` §9, alongside the rest of the launch/arbitration mechanism it actually validates — removed from here during the same double-check pass that fixed §2's package layout, not silently dropped.)

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- (Exact retention window for old release directories — resolved, no longer open. Already has a real answer elsewhere that just needed connecting: Background Workers' own consolidated job registry states this precisely — "keeps current + 1 prior floor" (`v3-deepdive-12-background-workers-api.md` §6.1) — one prior release kept as an immediate rollback target, older ones garbage-collected. Not a separate open number, the same answer this document's own release-directory GC already implements.)
- (Cross-channel rollback semantics moved to `v3-deepdive-38-supervisor.md` §10, since rollback is now clearly Supervisor's own responsibility, not this API's — removed from here rather than answered in the wrong document.)
