"""The live resource ledger (`v3-deepdive-20-health-api.md` §5).

§10's first named testing hook is the abandoned-reservation cleanup test — "a reservation
created without any subsequent refresh, confirming it's correctly released once its TTL
lapses — direct validation of §5.2's entire failure-mode fix." That is
`test_abandoned_reservation_is_reclaimed_when_ttl_lapses` below, and the capacity it frees is
asserted, not just its released flag: a reservation marked released that still counts against
the device would leave the bug §5.2 exists to fix fully intact.
"""

from __future__ import annotations

import pytest

from core.health.contracts import ReservationRejectionReason
from core.health.errors import ReservationExpired, ReservationNotFound
from core.health.metrics import HealthMetricsCollector
from core.health.resource_ledger import (
    NoHardwareProfile,
    ResourceLedger,
    StaticHardwareProfile,
    total_committed,
)


def test_reserve_grants_within_device_capacity(ledger):
    outcome = ledger.reserve("inference", "gpu:0", 2048)

    assert outcome.granted
    assert outcome.reservation is not None
    assert outcome.reservation.owning_api == "inference"
    assert outcome.device_total_mb == 8188
    assert outcome.device_committed_mb == 2048


def test_reserve_beyond_capacity_is_a_rejection_not_an_error(ledger):
    """§5.1: a rejection means the caller falls back to CPU or queues.

    The assertion that `error_code` stays empty is the load-bearing one. A caller that treats
    a rejection as a failure would surface an error to a user for what is a routine capacity
    decision, which is exactly the confusion the outcome contract exists to prevent.
    """
    ledger.reserve("inference", "gpu:1", 4000)
    outcome = ledger.reserve("ocr", "gpu:1", 512)

    assert not outcome.granted
    assert outcome.rejection_reason is ReservationRejectionReason.INSUFFICIENT_CAPACITY
    assert outcome.error_code == ""
    assert outcome.device_committed_mb == 4000


def test_unknown_device_is_rejected_never_granted():
    """Fail closed where the ceiling is unknown (`docs/PRINCIPLES.md` §4.2).

    Setup API does not exist yet, so `NoHardwareProfile` is what a real process gets today. A
    permissive default here would hand two processes the same VRAM the first time anything
    ran before Setup landed.
    """
    ledger = ResourceLedger(profile=NoHardwareProfile())

    outcome = ledger.reserve("ocr", "gpu:0", 1)

    assert not outcome.granted
    assert outcome.rejection_reason is ReservationRejectionReason.UNKNOWN_DEVICE


@pytest.mark.parametrize(
    ("owning_api", "device", "mb"),
    [("", "gpu:0", 512), ("ocr", "", 512), ("ocr", "gpu:0", 0), ("ocr", "gpu:0", -1)],
)
def test_malformed_requests_are_rejected(ledger, owning_api, device, mb):
    outcome = ledger.reserve(owning_api, device, mb)

    assert not outcome.granted
    assert outcome.rejection_reason is ReservationRejectionReason.INVALID_REQUEST
    assert outcome.error_code == "INVALID_RESERVATION_REQUEST"


def test_release_frees_capacity_for_the_next_caller(ledger):
    first = ledger.reserve("inference", "gpu:1", 4000)
    ledger.release(first.reservation.reservation_id)

    second = ledger.reserve("ocr", "gpu:1", 4000)

    assert second.granted
    assert ledger.commitment("gpu:1").committed_mb == 4000


def test_releasing_twice_is_a_no_op_not_an_error(ledger):
    """A retry after a dropped response must never fail a cleanup path."""
    granted = ledger.reserve("ocr", "gpu:0", 128).reservation

    first = ledger.release(granted.reservation_id)
    second = ledger.release(granted.reservation_id)

    assert second.released_at == first.released_at


def test_release_of_unknown_id_raises_internally(ledger):
    with pytest.raises(ReservationNotFound):
        ledger.release("nope")


def test_abandoned_reservation_is_reclaimed_when_ttl_lapses(ledger, clock):
    """§10's abandoned-reservation cleanup test — §5.2's failure mode, directly.

    A process crashing without calling `release()` is simulated by simply never refreshing.
    The reclaimed capacity is what is asserted: the whole bug was stale reservations blocking
    real capacity forever.
    """
    granted = ledger.reserve("inference", "gpu:1", 4096).reservation
    assert ledger.commitment("gpu:1").committed_mb == 4096

    clock.advance(121)
    reclaimed = ledger.sweep_expired()

    assert [r.reservation_id for r in reclaimed] == [granted.reservation_id]
    assert reclaimed[0].release_reason == "ttl_lapsed"
    assert ledger.commitment("gpu:1").committed_mb == 0
    assert ledger.reserve("ocr", "gpu:1", 4096).granted


def test_stale_reservation_cannot_refuse_a_live_one(ledger, clock):
    """The sweep runs before the capacity decision, not after.

    Without that ordering a crashed process's stale claim is what refuses a live caller —
    which is the same outage §5.2 set out to end, just moved one call later.
    """
    ledger.reserve("inference", "gpu:1", 4096)
    clock.advance(200)

    outcome = ledger.reserve("ocr", "gpu:1", 4096)

    assert outcome.granted


def test_refresh_keeps_a_live_reservation_alive(ledger, clock):
    granted = ledger.reserve("inference", "gpu:0", 1024).reservation

    clock.advance(100)
    refreshed = ledger.refresh(granted.reservation_id)
    clock.advance(100)

    assert refreshed.expires_at > granted.expires_at
    assert ledger.commitment("gpu:0").committed_mb == 1024
    assert not ledger.sweep_expired()


def test_refresh_after_expiry_is_refused_never_silently_revived(ledger, clock):
    """§11: the owning process must *discover* it lost its claim.

    Reviving an expired reservation here would hand two processes the same VRAM — the second
    acquired it legitimately while the first was silent, and a late refresh that succeeded
    would leave both believing they own it.
    """
    granted = ledger.reserve("inference", "gpu:0", 1024).reservation
    clock.advance(121)

    with pytest.raises(ReservationExpired):
        ledger.refresh(granted.reservation_id)


def test_expired_reservation_reports_itself_as_released_to_its_holder(ledger, clock):
    """§11's "never assume you still own something you haven't confirmed", from the read side."""
    granted = ledger.reserve("ocr", "gpu:0", 256).reservation
    clock.advance(121)

    seen = ledger.get(granted.reservation_id)

    assert seen is not None
    assert not seen.active
    assert seen.release_reason == "ttl_lapsed"


def test_reservations_on_one_device_do_not_consume_another(ledger):
    ledger.reserve("inference", "gpu:0", 8000)

    assert ledger.commitment("gpu:1").committed_mb == 0
    assert ledger.reserve("ocr", "gpu:1", 4096).granted


def test_metrics_count_each_outcome(ledger, clock):
    metrics = HealthMetricsCollector()
    counted = ResourceLedger(
        profile=StaticHardwareProfile({"gpu:0": 1024}),
        ttl_seconds=60,
        metrics=metrics,
        now=clock,
    )

    granted = counted.reserve("ocr", "gpu:0", 512).reservation
    counted.reserve("ocr", "gpu:0", 4096)
    counted.refresh(granted.reservation_id)
    counted.release(granted.reservation_id)
    second = counted.reserve("ocr", "gpu:0", 512).reservation
    clock.advance(61)
    counted.sweep_expired()

    snapshot = metrics.snapshot()
    assert snapshot.reservations_granted == 2
    assert snapshot.reservations_rejected == 1
    assert snapshot.reservations_refreshed == 1
    assert snapshot.reservations_released == 1
    assert snapshot.reservations_expired == 1
    assert second is not None


def test_total_committed_ignores_released_reservations(ledger):
    first = ledger.reserve("ocr", "gpu:0", 512).reservation
    ledger.reserve("inference", "gpu:0", 256)
    ledger.release(first.reservation_id)

    assert total_committed(ledger.active_reservations(), "gpu:0") == 256
