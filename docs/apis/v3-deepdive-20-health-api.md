# V3 Deep Dive: Health API

**Companion files:** all prior deep-dives — this is the API OCR (§5.6), Inference (§8.6), and Preprocessing (§6.7) all now depend on for live GPU/resource tracking, per Setup API's own deep-dive §6 resolution.

**Status:** Twentieth deep-dive session. Genuinely important priority given the cross-API dependency Setup's deep-dive just created — this session needs to actually design the live resource ledger those three documents committed to, not just accept the assignment.

---

## 1. Scope & boundary

Health owns two layers: **status** (service up/down, queue depth, per-instance resource utilization, external-dependency reachability) and **live diagnostic** (the bench suite's own empirical classification technique, reused continuously against real traffic). It also now owns the **live resource commitment ledger** (§4, resolved in Setup's deep-dive) — tracking which process currently holds how much VRAM on which device, distinct from Setup's own static `HardwareProfile`. It does not:
- **detect what hardware exists** — that's Setup API's `HardwareProfile` (its own deep-dive §5); Health reads that published profile rather than re-probing.
- **decide rollout cutover policy** — Update API's Supervisor consumes Health's status signal to gate a release swap; Health only reports, it doesn't decide when a rollout proceeds.
- **implement Watchdog's restart mechanism itself** — Watchdog (§5) is Health's own sub-API, but the actual process-restart action is a Supervisor-level capability Watchdog triggers, not something Health performs directly on a process it doesn't own.

---

## 2. Package layout

```
core/health/
  __init__.py
  contracts.py            # ServiceStatus, ResourceReservation, LiveDiagnostic, error types
  service.py                 # thin gRPC service implementation
  status.py                    # up/down, queue depth, dependency reachability
  live_diagnostic.py             # continuous bench-style classification — see §3
  resource_ledger.py              # the live VRAM/resource commitment tracker — see §4
  watchdog/                    # Sub-API — see §5
    __init__.py
    kicks.py
    version_tracking.py
  errors.py
  metrics.py
```

---

## 3. Live diagnostic — the bench suite's technique, running continuously
Reuses the bench suite's own empirical wall-time/CPU-time/RSS classification (established across the OCR/Preprocessing/Inference deep-dives' own testing-hooks sections) against real production traffic, not just at bench time — the payoff is catching **soft degradation**, not just hard failures: an engine that's normally CPU-bound suddenly behaving as if network-bound (a symptom worth investigating — a misconfigured EP falling back to a slower path, a thermal-throttling GPU) is invisible to a simple up/down check but exactly what this continuous classification is built to surface. Feeds Notifications/Logs/Audit; primary consumer is staff/owner via the TUI (Interface deep-dive's fleet screen); gates Update API's rollout health checks.

---

## 4. Version capability drift check — a new pattern, closing a real gap the Forward-Compatibility Pattern left open
`docs/PRINCIPLES.md` §3.3's Forward-Compatibility Pattern is built entirely around *not breaking* on an older Python — feature-detection, environment-marker installs, graceful degradation to the existing safe behavior. **Nothing in that pattern checks the opposite direction**: once an install actually *is* running on a newer interpreter, is the codebase genuinely taking advantage of what that unlocks, or silently still running the old fallback path because nothing ever prompted a check? A shim that gracefully falls back on old Python is also, by construction, capable of silently *staying* on the fallback path forever even after the interpreter's been upgraded, if nothing ever re-evaluates which branch it's actually taking. This is a real, distinct failure mode from anything Telemetrees' Dependencies Warden covers — Dependencies Warden watches for *external* releases becoming available; this checks whether *this specific running process* is actually using what it already has.

### 4.1 What gets checked, concretely
```python
@dataclass(frozen=True)
class CapabilityDriftFinding:
    capability: str            # "frozendict" | "profiling_tool_preference" | ...
    python_version: str
    expected_path: str           # what SHOULD be active given this interpreter
    actual_path: str              # what IS actually active
    drifted: bool

async def check_capability_drift() -> tuple[CapabilityDriftFinding, ...]:
    findings = []

    # frozendict: is the resolved FrozenDict genuinely the 3.15+ builtin,
    # or did the PyPI package end up active anyway (a stale lockfile, a
    # transitive dependency pulling it in despite the environment-marker
    # scoping that should have excluded it)?
    if sys.version_info >= (3, 15):
        from common.frozen_dict import FrozenDict
        is_builtin = FrozenDict.__module__ == "builtins"
        findings.append(CapabilityDriftFinding(
            capability="frozendict", python_version=platform.python_version(),
            expected_path="builtin (PEP 814)", actual_path="builtin" if is_builtin else "PyPI package (unexpected)",
            drifted=not is_builtin,
        ))

    # Profiling tool preference: config still says py-spy even though
    # Tachyon (3.15+) is available and was always meant to supersede it
    # once the interpreter caught up (OCR deep-dive §10.3's own stated
    # intent).
    if sys.version_info >= (3, 15):
        configured = get_config("telemetrees.preferred_profiler")
        findings.append(CapabilityDriftFinding(
            capability="profiling_tool_preference", python_version=platform.python_version(),
            expected_path="tachyon", actual_path=configured,
            drifted=configured != "tachyon",
        ))

    return tuple(f for f in findings if True)   # return all, not just drifted ones — a clean bill of health is itself a useful, loggable fact
```
This list is deliberately small and specific right now — exactly the two Forward-Compatibility-shimmed capabilities the corpus currently has (`docs/PRINCIPLES.md` §3.3's frozendict shim, and OCR/Inference's py-spy→Tachyon profiling transition). **Every future shimmed capability should register its own check here as part of the same PR that introduces the shim** — this is worth being an explicit line item in `docs/templates/new_dependency.md`'s own checklist going forward, not left to be remembered separately.

### 4.2 When it runs
Triggered by Update API's own Boot Sequence (its deep-dive §5) as part of cold-start health-gating — every process launch re-evaluates capability drift, not just once at install time, since a config change or a dependency-lock update between restarts is exactly the kind of thing that could silently introduce drift. Also runs as a Background Workers idle-time job on a periodic interval, catching drift introduced by a config change that didn't require a restart to take effect.

### 4.3 Surfacing — a distinct, high-visibility log tier, not folded into ordinary warnings
A drift finding is genuinely different from an ordinary `WARNING`-level log entry — it's not "something might be wrong," it's "this process is running below its own achievable baseline, on purpose-built infrastructure that exists specifically to prevent exactly this." Logs API's own deep-dive (§3.1 there) adds a distinct `ATTENTION` level with its own rendering hint for exactly this case — not just another line in an `ERROR`-colored stream a busy operator's eye slides past. A drift finding also surfaces through Notifications to the owner (not just buried in Logs), since this is squarely the kind of thing an owner wants to know about without having to go looking for it.

---

## 5. The live resource ledger — designing what Setup's deep-dive committed Health to
OCR (§5.6), Inference (§8.6), and Preprocessing (§6.7) all now check in with this ledger before claiming GPU resources. This section is the actual design, not just accepting the assignment.

### 5.1 The reservation contract
```python
@dataclass(frozen=True)
class ResourceReservation:
    reservation_id: str
    owning_api: str            # "ocr" | "inference" | "preprocessing"
    device_id: str               # from Setup API's HardwareProfile, §3 there
    reserved_mb: int
    reserved_at: datetime
    released_at: datetime | None = None

async def reserve(owning_api: str, device_id: str, mb: int) -> ResourceReservation:
    """Called before a PresetWorker (Inference) or an OCR engine's
    session (RapidOCR) allocates on a GPU device. Checks current total
    commitment against the device's known VRAM (from Setup's
    HardwareProfile) and either grants or rejects — a rejection means
    the caller falls back to CPU or queues, not that the reservation
    call itself fails loudly."""

async def release(reservation_id: str) -> None:
    """Called when the session unloads. See §4.2 for what happens when
    this never gets called."""
```

### 5.2 The failure mode Inference's own deep-dive flagged as unresolved — resolved here
A process crashing without cleanly calling `release()` would leave a stale reservation blocking real capacity forever if nothing else caught it. **Resolution: reservations carry a TTL, refreshed by a heartbeat from the owning session, not held open indefinitely on trust.** A `PresetWorker` or OCR engine session that's still genuinely active periodically calls a lightweight `refresh(reservation_id)` (piggybacking on Watchdog's own kick mechanism, §6, rather than inventing a second heartbeat channel) — a reservation whose TTL lapses without a refresh is treated as abandoned and released automatically. This mirrors Auth's own session-expiry pattern (its deep-dive §5) applied to a different resource: a reservation is "alive" only as long as something's actively vouching for it, not until an explicit release that a crash could skip.

### 5.3 Why this lives in Health, not a new API
Restated from Setup's own deep-dive reasoning (§6 there) for completeness: this is a continuously-queried runtime concern (checked on effectively every GPU-backed session creation across multiple processes), the same *kind* of ongoing-signal responsibility Health already exists to host (Watchdog's kicks, live diagnostic classification) — not a new domain, just one more live signal alongside the ones already here.

---

## 6. Watchdog sub-API
**Full treatment in `v3-deepdive-34-watchdog.md`.** Summary below.
Liveness monitoring distinct from crash detection: each service proves it's alive via periodic kicks, auto-triggering a restart (via Supervisor) if silent past a timeout — a hung-not-crashed process is invisible to a plain process-status check, which is exactly the gap this closes. Also tracks which version/commit each currently-running service instance is on, given A/B hot-swap across channels (Update API's own deep-dive territory) — version/commit info rides the heartbeat response specifically, not every business response, keeping the hot path clean regardless of how cheap it would be to include everywhere.
```python
@dataclass(frozen=True)
class Heartbeat:
    service: str
    instance_id: str
    version_commit: str
    kicked_at: datetime
```

---

## 7. Asyncio and profiling
Status checks and the resource ledger's reservation calls are the highest-frequency operations in this API — genuinely async, network/IPC-bound, same "hot path stays minimal" discipline already applied to Auth's `ValidateSession` (its deep-dive §8). The live diagnostic's classification math itself is cheap (file 02's own table: "negligible" for the diagnostic math specifically) — the expensive part was always the workload being classified, which belongs to whichever API is doing the actual work, not to Health.

---

## 8. gRPC surface

```protobuf
service HealthService {
  rpc GetStatus(StatusRequest) returns (StatusResponse);
  rpc Heartbeat(HeartbeatRequest) returns (HeartbeatAck);          // Watchdog kicks
  rpc ReserveResource(ReserveRequest) returns (ReservationResponse);
  rpc ReleaseResource(ReleaseRequest) returns (ReleaseAck);
  rpc RefreshReservation(RefreshRequest) returns (ReleaseAck);      // the TTL heartbeat, §5.2
  rpc GetCapabilityDrift(DriftRequest) returns (DriftResponse);      // §4
}

message DriftResponse {
  repeated CapabilityDriftFinding findings = 1;
  bool any_drifted = 2;
}
```

---

## 9. Config

```
health:
  watchdog:
    kick_interval_seconds: 15
    timeout_seconds: 60
  resource_ledger:
    reservation_ttl_seconds: 120     # see §5.2
  capability_drift:
    check_on_boot: true                # see §4.2
    periodic_check_interval_hours: 6
```

---

## 10. Testing hooks
- **Abandoned-reservation cleanup test**: a reservation created without any subsequent refresh, confirming it's correctly released once its TTL lapses — direct validation of §5.2's entire failure-mode fix.
- **Watchdog restart trigger test**: a service that stops kicking, confirming Watchdog correctly triggers a Supervisor restart within the configured timeout, not later and not never.
- **Soft-degradation detection test**: a bench case where a normally-CPU-bound engine is forced into an artificially slow/network-bound-looking pattern, confirming the live diagnostic actually flags it rather than only catching hard failures.
- **Capability drift detection test**: run under a simulated 3.15+ interpreter with the PyPI `frozendict` package deliberately still importable (a stale-lockfile simulation), confirming `check_capability_drift()` correctly flags it — and, separately, confirming a genuinely clean 3.15+ environment reports `drifted: false` rather than a false positive. Both directions matter equally here, since a check that cries wolf gets ignored just as fast as one that never fires.

---

## 11. Open questions for this deep-dive (logged, not guessed at)
- **Reservation TTL default value, locked in as a reasoned starting placeholder.** Real session-lifetime data across OCR/Inference/Preprocessing's actual usage patterns can tune it later; the mechanism (TTL-based, Watchdog-heartbeat-refreshed) is what matters for shipping.
- **In-flight work when a reservation is force-released but the process turns out to still be alive, resolved: the process detects it and aborts cleanly, never assumes continued ownership.** On its next heartbeat or resource-touching operation, a process whose reservation lapsed discovers it's gone (a live check against Health's own ledger, not assumed still valid) and treats its own in-flight work the same way any other interrupted-mid-processing case is already handled — Execution Core's own checkpoint-resume mechanism (`v3-deepdive-10-execution-core-api.md` §6) picks the work back up from the last checkpoint once a fresh reservation is acquired, rather than the process continuing to act as if it still holds a resource that may have already been handed to someone else. Safety over optimism: never assume you still own something you haven't confirmed.
- **The capability drift registry's own long-term ownership, resolved: yes, the enforcement mechanism is real, not just assumed.** The Forward-Compatibility Hygiene checkbox already added to `new_dependency.md`, `new_core_api.md`, `new_sub_api.md`, and `new_provider.md`'s own PR checklists (both full and short versions, `docs/templates/`) is exactly the enforcement this question was asking whether existed — a new shimmed capability genuinely can't merge without that checkbox being addressed, closing the loop between "this should get registered" and "something actually checks that it did."
