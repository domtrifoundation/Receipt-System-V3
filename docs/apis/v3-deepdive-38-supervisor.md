# V3 Deep Dive: Supervisor

**Parent context:** Referenced throughout `v3-deepdive-24-update-deployment-api.md` §5 and `v3-deepdive-11-setup-api.md`, but never given its own dedicated design until now — a real gap, surfaced during the Setup Sequence walkthrough. This is the thing that arbitrates the entire multi-clone system: launches every service, health-gates cutover, drives rollback, and (new in this session) manages sleep/wake for genuinely idle services.

**Status:** New dedicated deep-dive. No prior full treatment — previously a paragraph inside Update API's own document, disproportionate to how critical this component actually is.

---

## 1. Scope & boundary

Supervisor is the **one thing that lives outside every release clone, permanently** — not inside any versioned `<version>_<commit-hash>` directory, a genuine top-level citizen alongside config and shared data (`docs/PRINCIPLES.md` §1.6). It owns: determining which release is active per channel, launching every service from the correct clone's own venv in dependency order, health-gating rollout cutover, driving rollback, and — new — sleeping/waking genuinely idle services. It does not:
- **decide business logic** — Supervisor launches processes and watches health signals; it has no opinion about what any service actually does.
- **update itself the way it updates everything else** — this is the entire reason this document exists; see §4.
- **replace Watchdog** — Watchdog (Health API's sub-API) proves a *running* service is alive via kicks; Supervisor decides whether a service should be *running at all* in the first place. Different questions, deliberately different owners.

**Why "Supervisor" is the right name to remember**: it's the literal, already-established name throughout this project's own corpus (file 01, Update API's deep-dive) — not a new concept, just one that never got its own real design pass until this session.

---

## 2. Package layout — deliberately outside the normal structure

```
supervisor/                    # top-level, sibling to every release clone — NEVER inside one
  __init__.py
  contracts.py                    # ActiveRelease, ServiceState, SleepPolicy
  arbitration.py                    # which clone is active per channel — see §3
  boot_sequence.py                    # dependency-ordered launch, health-gated — see §3.2
  rollback.py
  self_update/                          # Supervisor's own, separate update mechanism — see §4
    __init__.py
    reexec.py
  sleep_wake/                             # new — see §5
    __init__.py
    socket_activation_linux.py
    activation_proxy_windows.py
    classification.py                       # which services are sleep-candidates
  errors.py
```
Deliberately minimal. This isn't an accident of scope — see §4.1 for why keeping Supervisor small is itself a load-bearing design goal, not just tidiness.

---

## 3. Multi-clone arbitration — the actual mechanism

### 3.1 Which clone is active, per channel
```python
@dataclass(frozen=True)
class ActiveRelease:
    channel: str            # ltsc | stable | beta | alpha | latest_commit
    release_dir: Path         # the specific <version>_<commit-hash> directory currently active for this channel
    activated_at: datetime
```
A small local record (not a full database — this is genuinely simple state) tracked per channel, since — per `docs/PROCESS_TOPOLOGY.md` §1's own established fact — multiple channels can be active simultaneously in hosted multi-tenant mode, each with its own currently-active release directory. Supervisor is what every user's request ultimately routes through to reach the correct channel's own service processes.

### 3.2 Boot Sequence — consolidated from where it was scattered before
Already described piecemeal across Update API's and Setup API's own deep-dives; the authoritative version lives here, since Supervisor is the thing actually doing it: on launch, Supervisor determines the active release per channel, then launches every Layer-1 service (`docs/PROCESS_TOPOLOGY.md` §2) **in dependency order** — Persistence before Execution Core, since Execution Core depends on it — waiting for Watchdog to confirm each service's first successful health check before starting the next. Only once every service is confirmed healthy does Interface API's loading screen (codename splash) hand off to the running TUI. A service that fails to come up within a timeout surfaces via Review/Flagging or Telemetrees, never silently hangs.

### 3.3 Rollback
If a newly-cutover release fails its own post-cutover health checks, Supervisor reverts `ActiveRelease` for that channel back to the prior release directory (still on disk — garbage collection always keeps at least one prior, Update deep-dive §3) and re-launches services from it. This is a genuine advantage of "clone into a new directory, never mutate in place" — the old release is never gone, just no longer pointed at.

---

## 4. Supervisor's own update mechanism — the reason this needed its own document

### 4.1 Why Supervisor can't update itself the way it updates everything else
Every other service gets updated by Supervisor cloning a new release and cutting over to it — but Supervisor *is* the thing performing that operation. It cannot cleanly clone-and-cutover itself using its own mechanism without a chicken-and-egg problem: if the new Supervisor has a bug, there's no old, still-running Supervisor left to catch the failure and roll back, because updating Supervisor means replacing the very process that would normally do that catching. **This is the actual reason Supervisor is kept deliberately minimal (§2)** — the smaller and simpler it is, the less often it needs to change at all, and the safer each of those rare changes is.

### 4.2 The mechanism: verified two-phase re-exec, never silent
```python
# self_update/reexec.py — sketch
async def update_supervisor(new_binary_path: Path) -> UpdateResult:
    """1. Download/stage the new Supervisor build to a location the
    CURRENT Supervisor process doesn't touch while running.
       2. Launch the new build as a genuinely separate process, pointed
    at a --smoke-test flag: it must prove it can read config, locate
    the active releases, and report healthy — WITHOUT touching any
    live service's state yet.
       3. Only if that smoke test passes does the current Supervisor
    hand off: it tells the new process to take over live arbitration,
    and only THEN does the old process exit. If the smoke test fails,
    the old Supervisor keeps running, untouched, and reports the
    failed update attempt — never a blind swap."""
```
**Never silent or fully automatic — this is a deliberate, stated asymmetry from every other API's update flow.** A regular Core API can update silently within its channel once Proving Grounds and Health-gated cutover both pass. Supervisor updates always surface to the owner for explicit confirmation before the two-phase handoff even begins, given the failure mode here is categorically worse than any other service's — a broken Supervisor with no working prior instance left to arbitrate means the whole instance needs manual recovery, not just one degraded API. **Supervisor candidates also sit behind a meaningfully higher Proving Grounds bar** (its own deep-dive §36) than ordinary dependency or code bumps — a longer soak period on Alpha/Beta before ever being offered to Stable, given how much rarer and higher-stakes a Supervisor change actually is.

---

## 5. Version control for other services — two genuinely different shapes, not one mechanism forced to cover both

Everything in §4 is about Supervisor updating *itself*. This section is Supervisor's other, much more common job: changing which version of some *other* service is running — and that job has two genuinely different shapes depending on whether the target service can run multiple versions at once.

### 5.1 The two shapes, stated precisely
- **Multi-version-capable services** (24 of the 28 Core APIs — everything except Interface's TUI and Inference, §5.3 below) can genuinely run several versions simultaneously, one per active channel, exactly as `docs/PROCESS_TOPOLOGY.md` §1 already establishes. For these, "updating a version" normally just means a new channel-wide cutover (§3 above) — but a real, more granular owner capability is worth having on top of that, §5.2.
- **Single-instance services — the TUI and Inference, and only these two** — can only ever have one version running at a time, full stop, regardless of channel. Both are this project's heaviest processes; multiplying either per-channel the way the rest of the fleet does would mean running several copies of the most resource-intensive services simultaneously for no real benefit, since the TUI is fundamentally a local console one operator is looking at (not a remote-served-per-user surface the way the webapp is), and Inference already had this exact exception stated for itself (`docs/MAINTENANCE.md` §2 — "every user's inference requests route to one shared instance pinned to the system's primary/Stable channel"). Updating either of these means an actual process restart, designed in §5.4-§5.6.

### 5.2 Per-API, per-channel version pinning — a real, more granular owner capability than a full channel rollback
`TriggerRollback` (§7's gRPC surface) rolls back an entire channel — every service on it, all at once. A real, distinct, more surgical capability is worth having alongside it: an owner pinning *one specific* multi-version-capable service to a specific version within one channel, independent of the rest of that channel's own services — useful for exactly the case a full rollback is too blunt for ("I want to test the new OCR release on Beta while everything else on Beta stays where it is," or "roll back just Reconciliation after a bad release, without touching the twenty-three other services that were fine").
```python
@dataclass(frozen=True)
class ServiceVersionPin:
    channel: str
    service_name: str
    pinned_version: str | None    # None means "follow the channel's own release normally" — the default, unpinned state
    pinned_by: str                  # owner/staff user_id
    pinned_at: datetime
```
A pin is scoped to exactly one service on exactly one channel — every other service on that channel keeps following normal channel-wide cutover. Surfaced in Interface's own Fleet screen (`v3-deepdive-14-interface-api.md` §3.2), never a raw config edit.

### 5.3 Why exactly two services get the single-instance treatment, not more
Worth being explicit this is a closed, justified list, the same discipline `docs/PRINCIPLES.md` §1.4 already requires for the TUI's own custom-screen exceptions: **Interface's TUI** and **Inference**, and no others. Both share the same two properties that actually justify the exception — genuinely the heaviest processes in the fleet, and each has its own independent reason multi-version doesn't make sense for it (TUI: a local console, not a per-remote-user surface; Inference: already-established single-shared-instance reasoning, `docs/MAINTENANCE.md` §2). A future service being merely "kind of heavy" isn't sufficient justification on its own to add a third exception to this list without the same explicit reasoning.

### 5.4 The restart mechanism itself — reusing the two-phase pattern from §4, not inventing a second one
```python
async def restart_service_on_version(service_name: Literal["interface_tui", "inference"], target_version: str) -> RestartResult:
    """The same verified two-phase handoff §4.2 already uses for
    Supervisor's own self-update, applied here to a different target.
    1. Confirm target_version's own release clone exists and is
       health-check-capable (doesn't have to BE currently active on
       any channel — TUI/Inference version selection is independent
       of channel-based multi-version serving entirely, since neither
       participates in that model at all).
    2. Stop the currently-running instance of service_name.
    3. Launch the new instance from target_version's own clone.
    4. Wait for its own first successful health check (Watchdog,
       same as Boot Sequence's own dependency-ordered launch, §3.2)
       before considering the restart complete.
    If step 4 never succeeds, this is a real, harder failure mode
    than Supervisor's own self-update rollback (§4) — there's no
    'old instance still running' to fall back to, since the old one
    was already stopped in step 2. Mitigated by confirming step 1
    thoroughly before ever stopping the running instance, not by
    a rollback after the fact."""
```

### 5.5 TUI-specific: the restart is visible, because the thing restarting is what the operator is looking at
Unlike Inference (§5.6), stopping and relaunching the TUI process necessarily means the operator's own terminal goes away and comes back — this can't be hidden, so the design makes it a deliberate, legible experience rather than an unexplained blank terminal. **Reuses Boot Sequence's existing loading screen** (`v3-deepdive-14-interface-api.md`'s own enumerated custom-screen exception) rather than building a second "big loading screen" for the same underlying purpose — the outgoing TUI instance renders it with an "Updating to v{target_version}…" message before handing off, and the newly-launched instance renders the same screen (its own normal boot sequence) before taking over the terminal fully. **A "skip animation" early-exit control** — genuinely useful for development/testing iteration where waiting through a full boot animation repeatedly is pure friction, not gated behind `dev_mode` specifically (a normal owner mid-update might reasonably want to skip it too), but visually presented as a secondary, clearly-optional action, never the primary button.

### 5.6 Inference-specific: non-fullscreen, since the TUI itself never stops running
The TUI process itself isn't the thing being restarted here — it stays fully interactive throughout, showing Inference's own restart as a small, non-blocking status panel (Health API's own live-diagnostic layer, `v3-deepdive-20-health-api.md` §3, is what actually reports the transition from "old version healthy" → "restarting" → "new version healthy," this panel just renders that feed). No animation, no full-screen takeover, no operator input blocked — an owner can keep doing anything else in the TUI while this proceeds.

---

## 6. Sleep/wake for genuinely idle services — new, and a natural extension of what Supervisor already owns

### 6.1 Why this belongs here, not as a separate mechanism
Supervisor already owns the full lifecycle of every service's process — launching it, watching its health, deciding whether it should be running. "Should this service be *asleep* right now, and wake it when X happens" is the same *kind* of responsibility, not a new domain requiring a new owner.

### 6.2 Which services are actual sleep candidates — not a uniform policy
```python
class SleepPolicy(str, Enum):
    NEVER = "never"              # must always be immediately responsive
    IDLE_TIMEOUT = "idle_timeout"  # sleep after N minutes with no activity, wake on next request
    SCHEDULED_ONLY = "scheduled_only"  # normally asleep, woken only for a known trigger (a webhook callback, a scheduled job)
```
**Not every service is a sleep candidate, and pretending otherwise would be a real correctness risk, not just a missed optimization.** `NEVER`: Auth (session validation is the hottest path in the entire system — sleeping this would mean every request pays a cold-start penalty), Gateway (the fixed, always-reachable edge), Health (has to keep monitoring everything *else*, can't itself be the thing asleep when something needs catching), Persistence (near-universal dependency, every other API's own requests would stall waiting for it to wake), Logs (things need to log continuously, including the wake events of everything else), Watchdog (can't supervise liveness while asleep). `SCHEDULED_ONLY` — your own example is exactly right: **Ingestion** spends the overwhelming majority of its time doing nothing but holding a webhook subscription open and waiting for a daily fallback-poll timer (Webhook Subscription Manager's own deep-dive §4) — genuinely a strong sleep candidate. `IDLE_TIMEOUT` — OCR, Preprocessing, Inference: only needed while a run is actually in progress; with no active run, there's no reason for these to be resident at all.

### 6.3 Waking on an incoming request — Linux gets this free, Windows doesn't, and that asymmetry is worth stating plainly rather than glossed over
**Linux: systemd socket activation** (confirmed current, standard, actively used — Docker itself runs this way) is the real, off-the-shelf mechanism: a lightweight `.socket` unit listens on a sleeping service's gRPC port; systemd itself holds the socket while the actual service process isn't running at all; the first incoming connection triggers systemd to start the service and hand it the socket. Genuinely free — no custom code needed for the activation mechanism itself, only for making sure this project's own gRPC services can accept a passed-in socket cleanly (`SD_LISTEN_FDS_START`-style handling, or the simpler `systemd-socket-proxyd` fallback pattern for services that don't natively support socket-passing, which decouples the socket lifecycle from the service without needing the service to know anything special about it at all).

**Windows has no equivalent OS-service-level primitive.** This needs to be built: a small, minimal-footprint **activation proxy** — its own tiny always-resident process (deliberately much lighter than the real service, the same "keep the always-on piece minimal" discipline §4.1 already established for Supervisor itself) that listens on the target port, and on first connection, launches the real service and either hands off or relays the connection until the real service is ready to take over directly. This is real, buildable work, not a free platform feature — worth stating honestly rather than implying Windows gets the same thing "somehow."

### 6.4 Waking on a schedule
For `SCHEDULED_ONLY` services like Ingestion, the wake trigger isn't always an incoming connection — the daily fallback poll (§6.2) is a *timer*, not a request. This needs a persistent-but-tiny timer component that doesn't itself require the full sleeping service to be resident to know "it's time" — Supervisor's own `sleep_wake/` module owns a lightweight schedule table (service name → next wake time), checked on its own short interval, waking the target service the same way an incoming connection would. **This exact mechanism is now also the correct default trigger for Background Workers' own user-configured scheduling** (`v3-deepdive-12-background-workers-api.md` §5.3, its own `SupervisorWakeTrigger` provider) — a user-scheduled task dispatched by a service that could itself be asleep has the identical problem Ingestion's own daily poll already solved here, reused rather than re-solved.

### 6.5 A convenience worth offering, given both are already daily-cadence operations: aligning Logs' rotation with Ingestion's fallback poll
Since Logs' own day-rotation (its deep-dive §3.1) and Ingestion's fallback poll (its deep-dive §4.1.3) are both already daily-cadence, independently-timed operations, and Ingestion's own wake-from-sleep now genuinely depends on precise timing (§6.4) — worth exposing one shared, optional `daily_maintenance_time` config value both can reference instead of each drifting on its own independently-chosen schedule. Off by default (each keeps its own natural cadence), a real convenience once enabled: a predictable, single daily window rather than two independently-timed events a user has no reason to expect are related.

---

## 7. Asyncio, free-threading, and profiling — a genuine gap, caught during a later hygiene audit, not present when this document was first written

`docs/PRINCIPLES.md` §5 states this as a design requirement for every API's own deep-dive: state which concurrency bucket(s) it falls into, up front. This document never did — a real gap, not just a missing formality, caught when a direct challenge asked whether the project's own forward-compatibility and hygiene standards had actually been re-applied to the documents written after the big audit pass that established them. They hadn't, for this one.

**Supervisor's own work is fundamentally process-lifecycle orchestration, not computation** — four genuinely distinct concurrency shapes, worth being precise about rather than lumping into one bucket:
- **Boot Sequence and rollback** (§3.2, §3.3): launching child processes (`subprocess`/`multiprocessing` primitives, not a network call) and waiting on Watchdog's own health-check confirmations — a mix of process-spawning and async I/O, never itself compute-bound.
- **The two-phase self-update mechanism** (§4.2): the same shape — spawning a genuinely separate new process, waiting on its own smoke-test result over IPC — async coordination around a real process boundary, the entire point of the design being that this coordination happens *between* processes, never inside a shared one.
- **Single-instance restart and version pinning** (§5.4): the identical process-spawning-plus-health-check-polling shape as Boot Sequence above, applied to one already-running service instead of the whole fleet at once — not a new concurrency category, worth stating explicitly rather than leaving it to be inferred, since it was added to this document after the original three-bullet version of this section was written.
- **The Windows activation proxy** (§6.3): a small, genuinely separate always-resident process of its own, needs to be async internally to accept incoming connections while waiting to spawn the real service — the one piece of this document that's a persistent async event loop in the same sense OCR's or Inference's own service processes are, just far lighter.

**No compute-bound pure-Python work exists anywhere in this document's own scope** — nothing here does the kind of CPU-bound work free-threading would meaningfully help with, consistent with every other thin-orchestration API in this batch (Tool Call, Account Guardian, Notifications) reaching the same conclusion for the same underlying reason. **No new native/C-extension dependency is introduced by this document either** — process spawning uses Python's own standard library (`subprocess`, `multiprocessing`), nothing requiring its own Telemetrees tracking entry beyond what the interpreter itself already needs (`docs/MAINTENANCE.md` §3's own tracked-dependency inventory, unchanged by anything in this document).

---

## 8. gRPC surface — minimal, local-only

```protobuf
service SupervisorService {
  rpc GetActiveRelease(ChannelRequest) returns (ActiveReleaseResponse);
  rpc TriggerRollback(RollbackRequest) returns (RollbackResponse);
  rpc GetSleepStatus(ServiceStatusRequest) returns (SleepStatusResponse);
  rpc ForceWake(ForceWakeRequest) returns (WakeResponse);          // owner/staff manual override — "wake this now, I need it"
  rpc PinServiceVersion(PinRequest) returns (ServiceVersionPinResponse);      // §5.2 — per-API, per-channel override
  rpc ListServiceVersionPins(ChannelRequest) returns (PinListResponse);
  rpc RestartServiceOnVersion(RestartRequest) returns (stream RestartProgress);   // §5.4 — TUI/Inference only, streamed so the Fleet screen (fullscreen for TUI, a status panel for Inference) can render live progress
}
```
Deliberately not exposed the same way every other Core API's gRPC surface is — this is a local-only control interface (Interface API's own fleet screen is the primary consumer), not something reachable from the general request path, consistent with keeping Supervisor's own attack/failure surface as small as its codebase.

---

## 9. Config

```
supervisor:
  self_update:
    require_owner_confirmation: true      # never configurable to false — see §4.2
    proving_grounds_soak_days: 14           # longer than ordinary code/dependency bumps
  sleep_wake:
    enabled: true
    idle_timeout_minutes: 30                 # for IDLE_TIMEOUT-class services
  daily_maintenance_time: null                # see §6.5 — null means independent scheduling, unset by default
  single_instance_restart:
    tui_boot_animation_skippable: true          # §5.5 — the "skip animation" control, never gated behind dev_mode specifically
    single_instance_health_check_timeout_seconds: 30   # §5.4 step 4 — how long to wait for the new instance's first successful health check before declaring the restart failed
```

---

## 10. Testing hooks
- **Two-phase update failure-injection**: a deliberately broken new-Supervisor build that fails its own smoke test, confirming the old Supervisor keeps running untouched and reports the failure — the single most important test in this entire document, given what a false pass here would cost.
- **Sleep/wake correctness test**: an `IDLE_TIMEOUT`-class service (OCR, say) genuinely stops consuming resources after its timeout, and a subsequent gRPC request correctly triggers a wake and completes successfully — not just fast asleep, but *correctly* wakes.
- **Windows activation-proxy load test**: confirms the proxy itself stays genuinely lightweight (memory/CPU) even under many concurrent wake-triggering connections, since a heavy "lightweight" proxy would defeat its own purpose.
- **Boot Sequence dependency-order test**: already implied elsewhere, worth an explicit regression here specifically, given this document is now the authoritative owner of that sequence.
- **Single-instance restart failure test**: `restart_service_on_version()` (§5.4) targeting a deliberately broken clone — confirms the health-check-capable check in step 1 actually catches it *before* the currently-running instance is stopped, since step 1 failing is recoverable and step 4 failing after step 2 has already happened is not. The concrete validation that this design's own stated asymmetry (§5.4) is real, not just described.
- **Version-pin scope test**: confirms `PinServiceVersion` on one service within a channel doesn't affect any other service on that same channel — direct validation of §5.2's "surgical, not a full rollback" claim.
- **TUI restart handoff test**: confirms the outgoing TUI instance's own Boot-Sequence-reused screen actually hands off terminal control cleanly to the newly-launched instance, with no dropped input or corrupted terminal state in between — the concrete UX risk this whole mechanism has to get right.

---

## 11. Open questions for this deep-dive (logged, not guessed at)
- **`daily_maintenance_time`'s actual scheduling semantics, resolved: a single instant both operations run from, staggered rather than simultaneous.** Logs' own rotation fires at that instant; Ingestion's fallback poll fires a few minutes after, not at the exact same moment — simpler and more predictable than a shared window, and avoids both operations genuinely competing for I/O at the identical instant for no real benefit.
- **`IDLE_TIMEOUT` default value, locked in at 30 minutes as the reasoned default.** Real usage-pattern data can tune it later; the mechanism is what matters for shipping.
- **Whether `ForceWake` needs its own Audit entry, resolved: yes.** A manual override of sleep state is a real administrative action with real operational consequences — consistent with every other privileged, non-routine action in this project getting Audit-logged.
- **Cross-platform parity commitment, resolved: Linux-first, not simultaneous.** Linux gets systemd socket activation genuinely free; Windows requires real, custom-built activation-proxy work. Shipping Linux support first rather than blocking on both simultaneously is the pragmatic sequencing — Windows support ships when that real work is actually done, not held to an artificial simultaneous-launch requirement that would just delay Linux users for no benefit to them.
- **Cross-channel rollback semantics, resolved: mostly independent per channel, with Inference API as a documented, unavoidable exception.** Inference is pinned to the system's Stable channel regardless of a caller's own channel selection (file 01's own stated reasoning, to avoid loading multiple model copies) — a Beta-channel rollback genuinely can't independently roll back Inference's own behavior, since Beta never had its own separate Inference instance to roll back in the first place. Every other service rolls back per-channel cleanly; this one specific, already-documented exception is the one real shared-resource interaction, not a gap in the rollback design itself.
- **`PinServiceVersion` audit trail, resolved: yes, the same reasoning as `ForceWake`.** A version pin is a real, consequential administrative override — Audit-logged for the same reason.
- **Simultaneous TUI restart requests from multiple staff sessions, resolved: the TUI is inherently single-operator per install.** A physical/local console, not a remote multi-session surface — stated explicitly here rather than left as an unstated assumption, closing the question rather than leaving it ambiguous.
