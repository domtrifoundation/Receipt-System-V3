"""Supervisor's data contracts (`v3-deepdive-38-supervisor.md` §3, §5, §6). Types only,
no logic (`docs/PRINCIPLES.md` §1.1) — the only module other packages import from.

Supervisor lives permanently outside every release clone (`docs/PRINCIPLES.md` §1.6), so
these contracts describe process-lifecycle state, never anything about what a service
*does* — that boundary is this whole package's own scope (§1: "launches processes and
watches health signals; it has no opinion about what any service actually does").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

__all__ = [
    "ActiveRelease",
    "BootReport",
    "RestartResult",
    "RestartStage",
    "RollbackResult",
    "ServiceLaunchResult",
    "ServiceSpec",
    "ServiceState",
    "ServiceVersionPin",
    "SleepPolicy",
    "SleepStatus",
    "UpdateResult",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActiveRelease:
    """§3.1's own sketch, verbatim — a small local record (not a full database), one per
    channel, since multiple channels are simultaneously active in hosted multi-tenant
    mode. Every user's request ultimately routes through this to reach the correct
    channel's own service processes."""

    channel: str
    release_dir: Path
    activated_at: datetime = field(default_factory=utcnow)


class ServiceState(str, Enum):
    """What Supervisor currently believes about one service instance — the "should this
    be running at all" question §1 draws as this package's own, distinct from Watchdog's
    "is a running service alive" question."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    SLEEPING = "sleeping"
    FAILED = "failed"


class SleepPolicy(str, Enum):
    """§6.2's own three-way split — deliberately not a uniform policy. `NEVER`: Auth,
    Gateway, Health, Persistence, Logs, Watchdog (each has its own stated reason in the
    deep-dive; the common thread is "something else's correctness depends on this one
    never having a cold-start delay"). `SCHEDULED_ONLY`: Ingestion (a webhook subscription
    plus a daily fallback-poll timer). `IDLE_TIMEOUT`: OCR, Preprocessing, Inference —
    resident only while a run is actually in progress.
    """

    NEVER = "never"
    IDLE_TIMEOUT = "idle_timeout"
    SCHEDULED_ONLY = "scheduled_only"


@dataclass(frozen=True)
class ServiceSpec:
    """One Layer-1 service Boot Sequence knows how to launch (`docs/PROCESS_TOPOLOGY.md`
    §2) — the per-service venv, the module entry point, and the dependency-order
    constraint §3.2 requires ("Persistence before Execution Core, since Execution Core
    depends on it").

    `import_path` matches `docs/VENV_AND_IMPORTS.md`'s own per-service venv naming
    (`core.ocr`, not `ocr`) — the same dotted path `services/setup/venv_provisioning.py`
    already uses to name a service's own `.venvs/<import_path>/` directory, so Boot
    Sequence resolves the exact venv Setup/Update already provisioned rather than
    guessing at a different naming scheme.
    """

    name: str
    import_path: str
    serve_module: str
    """The module Boot Sequence runs as `python -m <serve_module>` inside the clone, with
    the service's own venv on `PYTHONPATH` — e.g. `"core.persistence.grpc_servicer"`."""
    address: str
    """`host:port` this service's own `serve()` binds to — used for the real
    gRPC-reachability health-gate check (see `boot_sequence.py`'s own module docstring for
    why this is a reachability probe, not a Watchdog kick, in this build)."""
    depends_on: tuple[str, ...] = ()
    sleep_policy: SleepPolicy = SleepPolicy.NEVER


@dataclass(frozen=True)
class ServiceLaunchResult:
    """One service's own outcome from one Boot Sequence pass. Errors are data
    (`docs/PRINCIPLES.md` §4.1) — a service that never became reachable within its
    timeout is `ok=False`, never a raise that would take the whole sequence down with it."""

    name: str
    ok: bool
    pid: int | None = None
    started_at: datetime = field(default_factory=utcnow)
    became_healthy_at: datetime | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class BootReport:
    """The whole Boot Sequence's own outcome (§3.2) — every service's own result, in
    launch order, plus whether the whole sequence may hand off to Interface's TUI."""

    channel: str
    release_dir: Path
    services: tuple[ServiceLaunchResult, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every launched service came up healthy — the gate Interface's own
        loading screen checks before handing off to the running TUI (§3.2's own "only
        once every service is confirmed healthy")."""
        return bool(self.services) and all(s.ok for s in self.services)

    @property
    def failed_services(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.services if not s.ok)


@dataclass(frozen=True)
class RollbackResult:
    """§3.3's own outcome — reverting one channel's `ActiveRelease` back to the prior
    release directory and re-launching from it."""

    channel: str
    reverted_to: Path | None
    boot: BootReport | None = None
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code and self.reverted_to is not None


@dataclass(frozen=True)
class ServiceVersionPin:
    """§5.2's own sketch, verbatim — a real, more surgical alternative to a full
    `TriggerRollback`: one service, one channel, independent of the rest of that
    channel's own services. `pinned_version=None` means "follow the channel's own release
    normally," the default, unpinned state."""

    channel: str
    service_name: str
    pinned_version: str | None
    pinned_by: str
    pinned_at: datetime = field(default_factory=utcnow)


RestartStage = Literal[
    "pending", "confirming_target", "stopping_old", "launching_new", "waiting_healthy", "complete", "failed",
]


@dataclass(frozen=True)
class RestartResult:
    """§5.4's own single-instance restart outcome (TUI/Inference only — the two-service
    closed list §5.3 justifies explicitly). `stage="failed"` at `waiting_healthy` is a
    real, harder failure than Supervisor's own self-update rollback (§4): there is no old
    instance left running to fall back to, since step 2 already stopped it."""

    service_name: Literal["interface_tui", "inference"]
    target_version: str
    stage: RestartStage
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.stage == "complete"


@dataclass(frozen=True)
class SleepStatus:
    """`GetSleepStatus`'s own answer for one service — whether it is genuinely asleep
    right now, and under which policy."""

    service_name: str
    policy: SleepPolicy
    state: ServiceState
    last_activity_at: datetime | None = None
    next_scheduled_wake_at: datetime | None = None


@dataclass(frozen=True)
class UpdateResult:
    """§4.2's own two-phase self-update outcome. `smoke_test_passed=False` means the old
    Supervisor kept running untouched — the single most important guarantee in this whole
    package, per the deep-dive's own §10 testing-hook priority."""

    ok: bool
    smoke_test_passed: bool = False
    handed_off: bool = False
    error_detail: str = ""
