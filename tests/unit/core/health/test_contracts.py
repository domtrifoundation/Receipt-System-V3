"""Health's frozen contracts and their `FrozenDict` fields (`docs/PRINCIPLES.md` §2.1).

The `forward_compat`-marked test here is the one this package genuinely needs across
interpreters: `ServiceStatus.resource_utilization` and `WatchdogConfig.per_service_timeouts`
are `FrozenDict`-typed, and on 3.15 the builtin `frozendict` is **not** a `dict` subclass. Any
code that reached for `isinstance(x, dict)` would silently take the wrong branch — for
`per_service_timeouts` that means every service quietly falling back to the global watchdog
timeout while the config appears to have been honoured.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

import pytest

from common.frozen_dict import FrozenDict
from core.health.contracts import (
    CapabilityDriftFinding,
    DeviceCommitment,
    ReservationOutcome,
    ResourceReservation,
    ServiceState,
    ServiceStatus,
)
from core.health.watchdog.contracts import Heartbeat, Liveness, WatchdogConfig, WatchdogState

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.forward_compat
def test_frozen_dict_fields_are_mappings_not_dict_subclasses():
    """The check every `FrozenDict` consumer must make is `Mapping`, never `dict`.

    On 3.14 the PyPI `frozendict` happens to satisfy both; on 3.15 the builtin satisfies only
    `Mapping`. A test asserting `Mapping` passes on both and is the one that stays true when
    the interpreter moves — which is the whole point of the marker.
    """
    status = ServiceStatus(
        service="ocr",
        instance_id="ocr-1",
        state=ServiceState.UP,
        version="x00.00.09",
        version_commit="abc1234",
        reported_at=NOW,
        resource_utilization=FrozenDict({"vram_mb": "2048"}),
    )
    config = WatchdogConfig(per_service_timeouts=FrozenDict({"inference": 600}))

    assert isinstance(status.resource_utilization, Mapping)
    assert isinstance(config.per_service_timeouts, Mapping)
    assert status.resource_utilization["vram_mb"] == "2048"
    assert config.per_service_timeouts["inference"] == 600


@pytest.mark.forward_compat
def test_frozen_dict_fields_reject_mutation():
    """Shallow immutability is not enough — a frozen dataclass with a plain `dict` is mutable."""
    status = ServiceStatus(
        service="ocr",
        instance_id="ocr-1",
        state=ServiceState.UP,
        version="x00.00.09",
        version_commit="abc1234",
        reported_at=NOW,
        resource_utilization=FrozenDict({"vram_mb": "2048"}),
    )

    with pytest.raises(Exception):
        status.resource_utilization["vram_mb"] = "4096"  # type: ignore[index]


def test_error_summaries_table_is_a_frozen_dict():
    """§2.1.1: a module-level constant lookup table is a `FrozenDict` too."""
    from core.health.errors import ERROR_CODES, ERROR_SUMMARIES

    assert isinstance(ERROR_SUMMARIES, Mapping)
    assert isinstance(ERROR_CODES, Mapping)
    with pytest.raises(Exception):
        ERROR_SUMMARIES["INTERNAL"] = "something else"  # type: ignore[index]


def test_reservation_active_reflects_release_not_the_clock():
    """`contracts.py` holds no logic (§1.1).

    `active` deliberately does not read the wall clock: a time-aware property here would be a
    second, quietly divergent opinion about expiry alongside the ledger's own, and the two
    would disagree exactly at the boundary that matters.
    """
    live = ResourceReservation(
        reservation_id="r1",
        owning_api="ocr",
        device_id="gpu:0",
        reserved_mb=512,
        reserved_at=NOW,
        expires_at=NOW,
    )

    assert live.active


def test_device_commitment_available_never_goes_negative():
    commitment = DeviceCommitment(
        device_id="gpu:0", total_mb=1024, committed_mb=2048, active_reservations=2
    )

    assert commitment.available_mb == 0


def test_rejection_outcome_carries_a_reason_rather_than_an_absent_reservation():
    """§5.1: a rejection is a normal answer the caller acts on, not a missing result."""
    outcome = ReservationOutcome(granted=False)

    assert outcome.reservation is None
    assert outcome.error_code == ""


def test_drift_finding_is_frozen():
    finding = CapabilityDriftFinding(
        capability="frozendict",
        python_version="3.15.0",
        expected_path="builtin (PEP 814)",
        actual_path="builtin",
        drifted=False,
    )

    with pytest.raises(Exception):
        finding.drifted = True  # type: ignore[misc]


def test_silence_report_derives_silent_services_rather_than_storing_them():
    from core.health.watchdog.contracts import SilenceReport

    report = SilenceReport(
        states=(
            WatchdogState(
                service="ocr",
                instance_id="ocr-1",
                liveness=Liveness.SILENT,
                last_kick_at=NOW,
            ),
            WatchdogState(
                service="auth",
                instance_id="auth-1",
                liveness=Liveness.ALIVE,
                last_kick_at=NOW,
            ),
        ),
        checked_at=NOW,
    )

    assert report.silent_services == ("ocr",)


def test_heartbeat_is_frozen():
    beat = Heartbeat(
        service="ocr", instance_id="ocr-1", version_commit="abc1234", kicked_at=NOW
    )

    with pytest.raises(Exception):
        beat.version_commit = "bbbbbbb"  # type: ignore[misc]
