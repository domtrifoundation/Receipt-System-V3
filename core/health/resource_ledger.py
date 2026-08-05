"""The live VRAM/resource commitment ledger (`v3-deepdive-20-health-api.md` §5).

OCR (§5.6 there), Inference (§8.6) and Preprocessing (§6.7) all check in here before claiming
GPU resources. This module is the thing those three documents were promised.

Three decisions in here are load-bearing rather than stylistic:

* **A rejection is a normal answer, not an error.** §5.1 says so outright: "a rejection means
  the caller falls back to CPU or queues, not that the reservation call itself fails loudly."
  So `reserve()` returns a `ReservationOutcome` either way, and nothing on the rejection path
  raises.
* **Reservations expire on a TTL rather than being held on trust** (§5.2). This is the fix for
  the failure mode Inference's own deep-dive flagged and could not resolve: a process that
  crashes without calling `release()` would otherwise block real capacity forever. A live
  session refreshes; a dead one stops refreshing and its claim lapses. Auth's session-expiry
  pattern applied to a different resource.
* **A lapsed reservation is never quietly revived by a late refresh** (§11). The owning
  process is supposed to *discover* that it lost its claim and abort its in-flight work
  cleanly, because the VRAM may already have been handed to someone else. Silently extending
  an expired reservation would take that discovery away and hand two processes the same
  memory. `refresh()` on an expired id fails, deliberately.

**Setup API owns hardware detection; this module owns the live ledger** (§1). Device ceilings
come from Setup's published `HardwareProfile` through the `HardwareProfileReader` adapter
below — never from probing hardware here (`docs/PRINCIPLES.md` §1.3, and §1.5's own division
of who owns what). Setup does not exist yet, so the default reader publishes nothing and every
reservation against an unknown device is **rejected**: granting against an unknown ceiling is
the unsafe answer, and this is one place where the fail-closed posture of §4.2 outranks §4.4's
degrade-gracefully default.

**Concurrency**: the ledger is touched from the reservation hot path (§7) across every
GPU-backed session creation in the cluster, so its internal state is guarded by a real lock
rather than relying on the GIL — this project targets free-threaded 3.14t, where `dict`
mutation is not implicitly serialized (`docs/PRINCIPLES.md` §3.3.1).
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from common.execution_provider import GpuLike

from .contracts import (
    DEFAULT_RESERVATION_TTL_SECONDS,
    DeviceCommitment,
    ReservationOutcome,
    ReservationRejectionReason,
    ResourceReservation,
)
from .errors import (
    InvalidReservationRequest,
    ReservationExpired,
    ReservationNotFound,
    code_for,
)
from .metrics import HealthMetricsCollector


def _utc_now() -> datetime:
    """Timezone-aware UTC, injected everywhere below rather than called inline.

    A TTL mechanism whose tests cannot control the clock is a TTL mechanism whose expiry path
    is untested in practice — §10's abandoned-reservation cleanup test is only meaningful if
    time can be advanced deterministically.
    """
    return datetime.now(timezone.utc)


@runtime_checkable
class HardwareProfileReader(Protocol):
    """The one adapter between this ledger and Setup API's published `HardwareProfile`.

    `docs/PRINCIPLES.md` §1.3: the external thing sits behind one small internal interface,
    not scattered call sites. When Setup API lands, wiring it in means passing a real reader
    here — not editing this module.
    """

    def total_mb(self, device_id: str) -> int | None:
        """That device's total VRAM in MB, or `None` if the profile does not name it."""


@runtime_checkable
class _HardwareProfileLike(Protocol):
    """Structural, not an import of `services.setup.contracts.HardwareProfile` —
    `PublishedHardwareProfile` only ever reads `.gpus`, and this repo's own established
    convention (`core/inference/contracts.py`'s `BlobRef`, re-declared rather than
    imported from `core.persistence`) is exactly this: a package beneath every service
    (`common/`, and this ledger by extension) never imports a specific service's own
    concrete type."""

    gpus: Sequence[GpuLike]


class NoHardwareProfile:
    """The default reader: nothing is published, so nothing is grantable.

    Deliberately not a permissive stub. Setup API does not exist yet, and a placeholder that
    granted freely would be a silent bypass of the one capacity check that stands between two
    processes and the same VRAM (`docs/PRINCIPLES.md` §4.2). Every request resolves to
    `UNKNOWN_DEVICE`, which is a rejection the caller handles — falling back to CPU — not a
    crash.
    """

    def total_mb(self, device_id: str) -> int | None:
        return None


class StaticHardwareProfile:
    """A reader over a fixed device→MB map.

    Real, not a test double: a self-hosted install pinning its own device ceilings in config
    is a genuine deployment shape, and it is also what makes §10's capacity tests exercise the
    same code path production does rather than a mock of it.
    """

    def __init__(self, devices: dict[str, int]) -> None:
        self._devices = dict(devices)

    def total_mb(self, device_id: str) -> int | None:
        return self._devices.get(device_id)


class PublishedHardwareProfile:
    """The real reader over Setup API's now-actually-published `HardwareProfile`
    (`services/setup/hardware/persistence.py` — real, live-found gap closed there: nothing
    ever wrote a detected profile anywhere before that module existed). Setup owns
    detection, this ledger owns the live commitment count on top of it (§1's own division,
    this file's module docstring) — this class is the one adapter between them, matching
    `HardwareProfileReader`'s own stated purpose exactly.

    **Two real, independent `device_id` conventions coexist in this codebase today, not
    unified into one** (confirmed live: `core/inference/model_registry.py`'s
    `device_by_preset` uses compute-API-style strings — `"cuda"`, `"directml"` — while
    `core/ocr/engines/rapidocr_engine.py`/`paddleocr_engine.py` default their own
    `device_id` config to `"gpu0"`-style index strings). Neither is wrong; forcing either
    caller to rename would be a breaking change to code this pass has no reason to touch.
    `total_mb()` resolves `device_id` three ways, first match wins:
    1. **Exact `compute_api` match** — `"cuda"`/`"sycl"`/`"rocm"` picks the best (most
       VRAM) GPU reporting that compute API.
    2. **`"gpuN"` index match** — the Nth GPU in detection order, OCR's own convention.
    3. **`"computeapi:N"` match** — the Nth GPU among those sharing that compute API, for
       a real multi-GPU-of-the-same-vendor machine neither convention above disambiguates
       on its own.
    `None` (never a fabricated ceiling) when nothing matches — `ResourceLedger.reserve()`
    reads that as `UNKNOWN_DEVICE`, the same fail-closed rejection `NoHardwareProfile`
    already produces for everything, per this file's own §4.2 posture.
    """

    _GPU_INDEX_RE = re.compile(r"^gpu(\d+)$")
    _COMPUTE_API_INDEX_RE = re.compile(r"^([a-z]+):(\d+)$")

    def __init__(self, profile: _HardwareProfileLike | None) -> None:
        self._profile = profile

    def total_mb(self, device_id: str) -> int | None:
        if self._profile is None:
            return None
        gpus = self._profile.gpus

        by_index = self._GPU_INDEX_RE.match(device_id)
        if by_index:
            index = int(by_index.group(1))
            if 0 <= index < len(gpus):
                return _vram_to_mb(gpus[index].vram_gb)
            return None

        by_api_index = self._COMPUTE_API_INDEX_RE.match(device_id)
        if by_api_index:
            api, index = by_api_index.group(1), int(by_api_index.group(2))
            matching = [g for g in gpus if g.compute_api == api]
            if 0 <= index < len(matching):
                return _vram_to_mb(matching[index].vram_gb)
            return None

        matching = [g for g in gpus if g.compute_api == device_id]
        if not matching:
            return None
        best = max(matching, key=lambda g: g.vram_gb or 0)
        return _vram_to_mb(best.vram_gb)


def _vram_to_mb(vram_gb: float | None) -> int | None:
    return round(vram_gb * 1024) if vram_gb is not None else None


class ResourceLedger:
    """Tracks which process currently holds how much VRAM on which device (§5).

    One instance per Health process. Every public method is safe to call concurrently.
    """

    def __init__(
        self,
        *,
        profile: HardwareProfileReader | None = None,
        ttl_seconds: int = DEFAULT_RESERVATION_TTL_SECONDS,
        metrics: HealthMetricsCollector | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._profile: HardwareProfileReader = profile or NoHardwareProfile()
        self._ttl = timedelta(seconds=ttl_seconds)
        self._metrics = metrics or HealthMetricsCollector()
        self._now = now
        self._lock = threading.Lock()
        self._reservations: dict[str, ResourceReservation] = {}

    # ------------------------------------------------------------------ reserve

    def reserve(self, owning_api: str, device_id: str, mb: int) -> ReservationOutcome:
        """Grant or reject a claim on `device_id` (§5.1).

        Called before a `PresetWorker` (Inference) or an OCR engine session allocates on a GPU
        device. Expired reservations are swept first so a crashed process's stale claim can
        never be what refuses a live one — that sweep-before-decide ordering is the whole
        practical payoff of §5.2's TTL.
        """
        if not owning_api or not device_id or mb <= 0:
            self._metrics.increment("reservations_rejected")
            return ReservationOutcome(
                granted=False,
                rejection_reason=ReservationRejectionReason.INVALID_REQUEST,
                error_code=code_for(InvalidReservationRequest()),
                error_detail="owning_api and device_id must be non-empty and mb must be positive",
            )

        total = self._profile.total_mb(device_id)
        if total is None:
            self._metrics.increment("reservations_rejected")
            return ReservationOutcome(
                granted=False,
                rejection_reason=ReservationRejectionReason.UNKNOWN_DEVICE,
            )

        now = self._now()
        with self._lock:
            self._sweep_locked(now)
            committed = self._committed_locked(device_id)
            if committed + mb > total:
                self._metrics.increment("reservations_rejected")
                return ReservationOutcome(
                    granted=False,
                    rejection_reason=ReservationRejectionReason.INSUFFICIENT_CAPACITY,
                    device_total_mb=total,
                    device_committed_mb=committed,
                )

            reservation = ResourceReservation(
                reservation_id=uuid.uuid4().hex,
                owning_api=owning_api,
                device_id=device_id,
                reserved_mb=mb,
                reserved_at=now,
                expires_at=now + self._ttl,
            )
            self._reservations[reservation.reservation_id] = reservation
            committed_after = committed + mb

        self._metrics.increment("reservations_granted")
        return ReservationOutcome(
            granted=True,
            reservation=reservation,
            device_total_mb=total,
            device_committed_mb=committed_after,
        )

    # ------------------------------------------------------------------ release

    def release(self, reservation_id: str, reason: str = "released") -> ResourceReservation:
        """End a reservation the owner is done with (§5.1).

        Releasing an already-released reservation is a no-op returning the existing record,
        not an error: a retry after a dropped response must not be able to fail a cleanup path.
        """
        now = self._now()
        with self._lock:
            existing = self._reservations.get(reservation_id)
            if existing is None:
                raise ReservationNotFound(reservation_id)
            if existing.released_at is not None:
                return existing
            released = ResourceReservation(
                reservation_id=existing.reservation_id,
                owning_api=existing.owning_api,
                device_id=existing.device_id,
                reserved_mb=existing.reserved_mb,
                reserved_at=existing.reserved_at,
                expires_at=existing.expires_at,
                released_at=now,
                release_reason=reason,
            )
            self._reservations[reservation_id] = released
        self._metrics.increment("reservations_released")
        return released

    # ------------------------------------------------------------------ refresh

    def refresh(self, reservation_id: str) -> ResourceReservation:
        """Extend a live reservation's TTL — the §5.2 heartbeat.

        Piggybacks on Watchdog's own kick mechanism rather than inventing a second heartbeat
        channel (§5.2), so a service already proving its liveness is not asked to prove it
        twice on two schedules.

        Raises `ReservationExpired` for a lapsed id rather than reviving it. §11 resolves that
        case explicitly: the process discovers its claim is gone and aborts its in-flight work
        through Execution Core's checkpoint-resume, instead of continuing to act as if it
        still owns memory that may already belong to someone else.
        """
        now = self._now()
        with self._lock:
            existing = self._reservations.get(reservation_id)
            if existing is None:
                raise ReservationNotFound(reservation_id)
            if existing.released_at is not None or existing.expires_at <= now:
                self._sweep_locked(now)
                self._metrics.increment("refresh_on_expired_rejected")
                raise ReservationExpired(reservation_id)
            refreshed = ResourceReservation(
                reservation_id=existing.reservation_id,
                owning_api=existing.owning_api,
                device_id=existing.device_id,
                reserved_mb=existing.reserved_mb,
                reserved_at=existing.reserved_at,
                expires_at=now + self._ttl,
            )
            self._reservations[reservation_id] = refreshed
        self._metrics.increment("reservations_refreshed")
        return refreshed

    # ------------------------------------------------------------------- reads

    def get(self, reservation_id: str) -> ResourceReservation | None:
        """The record as the ledger holds it, so a holder can check rather than assume (§11)."""
        with self._lock:
            self._sweep_locked(self._now())
            return self._reservations.get(reservation_id)

    def commitment(self, device_id: str) -> DeviceCommitment:
        """What is currently committed on one device, after sweeping lapsed claims."""
        total = self._profile.total_mb(device_id) or 0
        with self._lock:
            self._sweep_locked(self._now())
            committed = self._committed_locked(device_id)
            active = sum(
                1
                for r in self._reservations.values()
                if r.device_id == device_id and r.released_at is None
            )
        return DeviceCommitment(
            device_id=device_id,
            total_mb=total,
            committed_mb=committed,
            active_reservations=active,
        )

    def active_reservations(self) -> tuple[ResourceReservation, ...]:
        with self._lock:
            self._sweep_locked(self._now())
            return tuple(r for r in self._reservations.values() if r.released_at is None)

    def sweep_expired(self) -> tuple[ResourceReservation, ...]:
        """Release every reservation whose TTL lapsed, returning what was reclaimed (§5.2).

        Runs on its own from every ledger operation, and is also callable directly so a
        Background Workers idle-time job can reclaim capacity on a quiet cluster where no
        reservation call would otherwise trigger the sweep.
        """
        now = self._now()
        with self._lock:
            reclaimed = self._sweep_locked(now)
        return reclaimed

    # ------------------------------------------------------------------ internals

    def _committed_locked(self, device_id: str) -> int:
        return sum(
            r.reserved_mb
            for r in self._reservations.values()
            if r.device_id == device_id and r.released_at is None
        )

    def _sweep_locked(self, now: datetime) -> tuple[ResourceReservation, ...]:
        """Caller must hold `self._lock`."""
        reclaimed: list[ResourceReservation] = []
        for key, existing in list(self._reservations.items()):
            if existing.released_at is not None or existing.expires_at > now:
                continue
            lapsed = ResourceReservation(
                reservation_id=existing.reservation_id,
                owning_api=existing.owning_api,
                device_id=existing.device_id,
                reserved_mb=existing.reserved_mb,
                reserved_at=existing.reserved_at,
                expires_at=existing.expires_at,
                released_at=existing.expires_at,
                release_reason="ttl_lapsed",
            )
            self._reservations[key] = lapsed
            reclaimed.append(lapsed)
        if reclaimed:
            self._metrics.increment("reservations_expired", len(reclaimed))
        return tuple(reclaimed)


def total_committed(reservations: Iterable[ResourceReservation], device_id: str) -> int:
    """Committed MB across an arbitrary reservation set — the read used by tests and reports.

    Exists so a caller reasoning about a snapshot it already holds does not have to re-derive
    the same sum with its own subtly different notion of what counts as active.
    """
    return sum(
        r.reserved_mb for r in reservations if r.device_id == device_id and r.released_at is None
    )


__all__ = [
    "HardwareProfileReader",
    "NoHardwareProfile",
    "PublishedHardwareProfile",
    "ResourceLedger",
    "StaticHardwareProfile",
    "total_committed",
]
