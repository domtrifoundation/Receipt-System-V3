# V3 Deep Dive: Watchdog (Health sub-API)

**Parent API:** `v3-deepdive-20-health-api.md` §5. **Companion files:** `v3-deepdive-24-update-deployment-api.md` §5 (Supervisor, the actual restart-executor Watchdog triggers).

**Status:** Sub-API deep-dive, full treatment. Real V2 lineage (`health.py`'s actual `Watchdog`/`Heartbeat` classes).

---

## 1. Scope & boundary

Watchdog owns **liveness monitoring** — proving a service is alive via periodic kicks, distinct from crash detection (a hung-not-crashed process passes a plain process-status check but is exactly the failure mode this exists to catch). It does not:
- **execute the restart itself** — that's Supervisor's own, more conservative code path (Update deep-dive §5); Watchdog detects and triggers, Supervisor acts.
- **duplicate Health's own status/diagnostic layer** — status (up/down, queue depth) and live diagnostic (soft-degradation classification) are the parent API's own concern; Watchdog is specifically about the binary "has this service gone silent" question.

---

## 2. Package layout

```
core/health/watchdog/
  __init__.py
  contracts.py            # Heartbeat, WatchdogState, error types
  kicks.py                    # receiving/tracking heartbeats
  timeout_detector.py            # the silent-past-timeout check
  version_tracking.py             # per-instance version/commit, rides the heartbeat
  errors.py
```

---

## 3. The kick mechanism
```python
@dataclass(frozen=True)
class Heartbeat:
    service: str
    instance_id: str
    version_commit: str
    kicked_at: datetime

async def kick(service: str, instance_id: str, version_commit: str) -> None:
    """Called periodically by every long-running service's own internal
    loop — a service proves its own liveness by calling this, Watchdog
    never has to reach into a service to check on it. This is the
    inversion that makes a hung-not-crashed process detectable at all:
    a process that's stuck won't be calling this anymore, even though
    its OS-level process status still reads 'running.'"""
```

---

## 4. Timeout detection and restart triggering
```python
async def check_for_silence() -> tuple[str, ...]:
    """Runs on its own interval, comparing each tracked service's last
    kick against the configured timeout. A service silent past its
    timeout gets reported here — Watchdog's own job stops at reporting;
    Supervisor (its own deep-dive §5) is what actually executes a
    restart, kept deliberately separate so the thing deciding 'should I
    restart this' is never the same code path that might itself be
    hung."""
```

---

## 5. Version/commit tracking — piggybacked on the heartbeat, not every response
Given A/B hot-swap across channels (Update API's own multi-channel model), knowing which version/commit each currently-running service instance is on matters for diagnosing a channel-specific issue — but this rides the heartbeat response specifically, not every business response, keeping the actual hot path (every real API call) clean of version-tagging overhead that's cheap regardless but has no reason to be paid there.

---

## 6. Asyncio
Kicks and the silence-check are both lightweight, high-frequency async operations — the same "hot path stays minimal" discipline Health's own `ValidateSession`-adjacent reasoning already established (its deep-dive §6).

---

## 7. gRPC surface

```protobuf
service WatchdogService {
  rpc Kick(HeartbeatRequest) returns (KickAck);
  rpc GetSilentServices(SilenceCheckRequest) returns (SilentServicesResponse);
}
```

---

## 8. Config

```
watchdog:
  kick_interval_seconds: 15
  timeout_seconds: 60
```

---

## 9. Testing hooks
- **Hung-not-crashed simulation test**: a service process that stops kicking but doesn't actually exit (simulating a genuine hang, not a crash) is correctly detected within the configured timeout — the concrete validation of Watchdog's entire reason for existing over a plain process-status check.
- **Restart-trigger handoff test**: confirms Watchdog correctly reports to Supervisor rather than attempting any restart action itself.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Per-service timeout overrides, resolved: a global default with real per-service override capability.** A single global timeout doesn't fit every service equally — Inference's own model-loading time is a genuinely different cycle length than a lightweight API like Auth's own heartbeat — so the config carries a sensible global default plus an explicit per-service override map for the services that actually need one (Inference being the clearest real case), rather than either forcing one-size-fits-all or requiring every service to configure its own value individually when most are fine with the default.
