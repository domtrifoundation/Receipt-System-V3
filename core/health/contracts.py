"""Health API data contracts (`v3-deepdive-20-health-api.md` §3–§5, §8).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in
this package that anything outside `core/health/` imports from — Watchdog's own contracts
live in `watchdog/contracts.py`, because Watchdog is a sub-API with its own boundary, not a
section of this one.

Three things here are load-bearing rather than stylistic:

* **Every dict-typed field is a `FrozenDict`** (`docs/PRINCIPLES.md` §2.1). A status snapshot
  handed to a caller that could be mutated in place afterwards is not a snapshot. Anything
  checking the type of such a field must test `collections.abc.Mapping`; the Python 3.15
  builtin `frozendict` is not a `dict` subclass and `isinstance(x, dict)` silently misses it.
* **`ReservationOutcome` carries a rejection as data, not as an absent reservation.** §5.1 is
  explicit that a rejection means the caller falls back to CPU or queues — it is a normal,
  expected answer, not a failure. A contract that expressed rejection as `None` would push
  every caller into inventing its own reason for why, which is exactly the shape of thing
  §4.1 of `docs/PRINCIPLES.md` exists to prevent.
* **`ResourceReservation.expires_at` is on the contract, not derived by the caller.** The TTL
  is what makes the deep-dive §5.2 abandoned-reservation fix real; putting the expiry on the
  record means a caller can see for itself whether what it holds is still live rather than
  assuming it (§11's "never assume you still own something you haven't confirmed").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.frozen_dict import FrozenDict

#: §9's config defaults, as real constants rather than numbers repeated across modules.
DEFAULT_RESERVATION_TTL_SECONDS: int = 120
DEFAULT_KICK_INTERVAL_SECONDS: int = 15
DEFAULT_WATCHDOG_TIMEOUT_SECONDS: int = 60
DEFAULT_DRIFT_CHECK_INTERVAL_HOURS: int = 6


class ServiceState(str, Enum):
    """What the status layer currently reports about a service (§1).

    `DEGRADED` is deliberately distinct from `DOWN`. `docs/PRINCIPLES.md` §4.4's
    degrade-gracefully posture only means anything if there is a state expressing "still
    serving, but not at full capability" — an OCR process with one engine unavailable is not
    down, and reporting it as down would make Supervisor's rollout gate (§1) refuse a
    perfectly serviceable release.

    `UNKNOWN` is what an unreachable probe resolves to. It is not `DOWN`: Health reports, it
    does not decide (§1), and "I could not tell" is a materially different fact for an
    operator than "I checked and it is dead".

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value is a
    breaking change to the `.proto` surface.
    """

    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class WorkloadClass(str, Enum):
    """The bench suite's empirical classification, reused against live traffic (§3).

    These are the classes the OCR/Preprocessing/Inference deep-dives' own testing-hooks
    sections established, named here once so the live diagnostic and the bench suite cannot
    drift into two vocabularies for one measurement.
    """

    CPU_BOUND = "CPU_BOUND"
    IO_BOUND = "IO_BOUND"
    NETWORK_BOUND = "NETWORK_BOUND"
    MEMORY_BOUND = "MEMORY_BOUND"
    NEGLIGIBLE = "NEGLIGIBLE"
    INDETERMINATE = "INDETERMINATE"


class ReservationRejectionReason(str, Enum):
    """Why a reservation was not granted (§5.1).

    Every member here is a *normal* answer the caller acts on, not an error. `UNKNOWN_DEVICE`
    is the one that looks like an error and is not: Health reads Setup's published
    `HardwareProfile` rather than probing (§1), so a device Setup has not published is a
    device this ledger has no VRAM ceiling for, and granting against an unknown ceiling is
    the unsafe answer.
    """

    INSUFFICIENT_CAPACITY = "INSUFFICIENT_CAPACITY"
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"
    INVALID_REQUEST = "INVALID_REQUEST"


@dataclass(frozen=True)
class DependencyReachability:
    """One external dependency's reachability, as of `checked_at` (§1)."""

    name: str
    reachable: bool
    checked_at: datetime
    latency_ms: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class ServiceStatus:
    """A single service instance's live status (§1, §8's `StatusResponse`).

    `version_commit` rides this and the heartbeat, never every business response — §7's
    hot-path discipline, and the reason `docs/PROCESS_TOPOLOGY.md` §7 can say Watchdog knows
    which version each instance is on without every RPC paying for it.
    """

    service: str
    instance_id: str
    state: ServiceState
    version: str
    version_commit: str
    reported_at: datetime
    queue_depth: int = 0
    dependencies: tuple[DependencyReachability, ...] = ()
    resource_utilization: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    detail: str = ""


@dataclass(frozen=True)
class ResourceReservation:
    """A live claim on a device's VRAM (§5.1).

    Created by `resource_ledger.reserve`, kept alive by `refresh`, ended by `release` — or,
    when the owning process dies without releasing, by its TTL lapsing (§5.2). `released_at`
    and `expires_at` together are what let a holder answer "do I still own this?" from the
    record itself instead of assuming.
    """

    reservation_id: str
    owning_api: str
    device_id: str
    reserved_mb: int
    reserved_at: datetime
    expires_at: datetime
    released_at: datetime | None = None
    release_reason: str = ""

    @property
    def active(self) -> bool:
        """Released reservations are never active; TTL lapse is evaluated by the ledger.

        Deliberately not time-aware: `contracts.py` holds no logic (§1.1), and a property
        that read the wall clock would be a second, quietly divergent opinion about expiry
        alongside `resource_ledger.py`'s own.
        """
        return self.released_at is None


@dataclass(frozen=True)
class ReservationOutcome:
    """The answer to a `reserve()` call — granted or rejected, both normal (§5.1).

    A rejection is not an error and leaves `error_code` empty. `error_code` is reserved for
    the `docs/PRINCIPLES.md` §4.1 boundary case: a request Health could not evaluate at all.
    """

    granted: bool
    reservation: ResourceReservation | None = None
    rejection_reason: ReservationRejectionReason | None = None
    device_total_mb: int = 0
    device_committed_mb: int = 0
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class DeviceCommitment:
    """What the ledger currently believes is committed on one device (§5)."""

    device_id: str
    total_mb: int
    committed_mb: int
    active_reservations: int

    @property
    def available_mb(self) -> int:
        return max(0, self.total_mb - self.committed_mb)


@dataclass(frozen=True)
class LiveDiagnosticSample:
    """One observation of real traffic, in the bench suite's own terms (§3)."""

    service: str
    operation: str
    wall_time_ms: float
    cpu_time_ms: float
    rss_delta_mb: float
    observed_at: datetime


@dataclass(frozen=True)
class LiveDiagnosticFinding:
    """A classification of recent samples, and whether it drifted from the baseline (§3).

    The payoff §3 names is **soft degradation**: an engine normally `CPU_BOUND` now behaving
    `NETWORK_BOUND` is invisible to up/down checking and is exactly what this surfaces. A
    finding with `degraded=False` is still returned — a clean bill of health is a loggable
    fact, the same reasoning §4.1's drift check states outright.
    """

    service: str
    operation: str
    baseline_class: WorkloadClass
    observed_class: WorkloadClass
    sample_count: int
    degraded: bool
    detail: str = ""


@dataclass(frozen=True)
class CapabilityDriftFinding:
    """§4.1's contract, in shape.

    `drifted=False` findings are returned too, deliberately: §4.1 ends by saying a clean bill
    of health is itself a useful, loggable fact, and a check that only ever speaks up when
    something is wrong gives an operator no way to tell "nothing is wrong" from "the check
    never ran".
    """

    capability: str
    python_version: str
    expected_path: str
    actual_path: str
    drifted: bool
    detail: str = ""


@dataclass(frozen=True)
class HealthMetrics:
    """This API's own counters, snapshotted (`metrics.py`).

    Field names are the counter names — `metrics.py` derives them from this contract so the
    two cannot drift apart.
    """

    reservations_granted: int = 0
    reservations_rejected: int = 0
    reservations_released: int = 0
    reservations_expired: int = 0
    reservations_refreshed: int = 0
    refresh_on_expired_rejected: int = 0
    status_reports_received: int = 0
    status_probes_unreachable: int = 0
    diagnostic_samples_recorded: int = 0
    soft_degradations_detected: int = 0
    drift_checks_run: int = 0
    drift_findings_flagged: int = 0


__all__ = [
    "DEFAULT_DRIFT_CHECK_INTERVAL_HOURS",
    "DEFAULT_KICK_INTERVAL_SECONDS",
    "DEFAULT_RESERVATION_TTL_SECONDS",
    "DEFAULT_WATCHDOG_TIMEOUT_SECONDS",
    "CapabilityDriftFinding",
    "DependencyReachability",
    "DeviceCommitment",
    "HealthMetrics",
    "LiveDiagnosticFinding",
    "LiveDiagnosticSample",
    "ReservationOutcome",
    "ReservationRejectionReason",
    "ResourceReservation",
    "ServiceState",
    "ServiceStatus",
    "WorkloadClass",
]
