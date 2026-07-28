"""Watchdog liveness monitoring (`v3-deepdive-34-watchdog.md` §3, §4, §5, §10).

§9's first named testing hook is the hung-not-crashed simulation: "a service process that
stops kicking but doesn't actually exit (simulating a genuine hang, not a crash) is correctly
detected within the configured timeout — the concrete validation of Watchdog's entire reason
for existing over a plain process-status check." That is
`test_hung_not_crashed_service_is_detected_within_its_timeout`.

§9's second is the restart-trigger handoff test, "confirms Watchdog correctly reports to
Supervisor rather than attempting any restart action itself". That one is asserted structurally
in `test_watchdog_exposes_no_restart_capability`: the guarantee is the *absence* of a restart
path, and an absence is only really tested by looking for it and not finding it.
"""

from __future__ import annotations

import pytest

from common.frozen_dict import FrozenDict
from core.health.watchdog.contracts import Liveness, WatchdogConfig
from core.health.watchdog.errors import InvalidHeartbeat
from core.health.watchdog.kicks import KickRegistry
from core.health.watchdog.timeout_detector import TimeoutDetector, resolve_timeout
from core.health.watchdog.version_tracking import VersionTracker


@pytest.fixture
def registry(clock) -> KickRegistry:
    return KickRegistry(now=clock)


def test_a_kicking_service_is_alive(registry, clock):
    registry.kick("ocr", "ocr-1", "abc1234")
    detector = TimeoutDetector(registry, now=clock)

    clock.advance(30)

    assert detector.state("ocr", "ocr-1").liveness is Liveness.ALIVE


def test_hung_not_crashed_service_is_detected_within_its_timeout(registry, clock):
    """§9's hung-not-crashed simulation — the reason this sub-API exists at all.

    The simulated process never exits. Its OS-level status would still read "running" and a
    plain process-status check would call it healthy. It simply stops kicking, and that is the
    only signal there is.
    """
    registry.kick("ocr", "ocr-1", "abc1234")
    detector = TimeoutDetector(registry, now=clock)

    clock.advance(61)
    report = detector.check_for_silence()

    assert report.silent_services == ("ocr",)
    state = report.states[0]
    assert state.liveness is Liveness.SILENT
    assert state.silent_for_seconds == pytest.approx(61.0)


def test_service_is_not_reported_silent_one_second_before_its_timeout(registry, clock):
    """Detected within the configured timeout — "not later and not never" (§10 of the parent).

    The boundary is asserted from both sides because an off-by-one here either restarts
    healthy services or never restarts hung ones.
    """
    registry.kick("ocr", "ocr-1")
    detector = TimeoutDetector(registry, now=clock)

    clock.advance(60)

    assert detector.state("ocr", "ocr-1").liveness is Liveness.ALIVE


def test_never_seen_instance_is_unseen_not_silent(registry, clock):
    """Restarting something that never started would be Supervisor acting on a fiction.

    A service still coming up during the boot sequence (`docs/PROCESS_TOPOLOGY.md` §6) is
    exactly the case that would hit.
    """
    detector = TimeoutDetector(registry, now=clock)

    assert detector.state("inference", "inference-1").liveness is Liveness.UNSEEN


def test_kicking_again_clears_silence(registry, clock):
    detector = TimeoutDetector(registry, now=clock)
    registry.kick("ocr", "ocr-1")
    clock.advance(61)
    assert detector.state("ocr", "ocr-1").liveness is Liveness.SILENT

    registry.kick("ocr", "ocr-1")

    assert detector.state("ocr", "ocr-1").liveness is Liveness.ALIVE


def test_per_service_timeout_override_applies():
    """§10's resolved open question: a global default plus real per-service overrides.

    Inference's model-loading cycle is genuinely a different length from a lightweight API's
    heartbeat, so a single global value would either restart Inference mid-load or wait far
    too long on everything else.
    """
    config = WatchdogConfig(
        timeout_seconds=60, per_service_timeouts=FrozenDict({"inference": 600})
    )

    assert resolve_timeout("inference", config) == 600
    assert resolve_timeout("auth", config) == 60


def test_override_map_reads_work_without_isinstance_dict(registry, clock):
    """`docs/PRINCIPLES.md` §2.1: the 3.15 builtin `frozendict` is not a `dict` subclass.

    `resolve_timeout` reads through `.get` for exactly this reason. A branch that had gone
    through `isinstance(x, dict)` would silently miss the builtin and hand every service the
    global default while appearing to honour the override.
    """
    config = WatchdogConfig(
        timeout_seconds=60, per_service_timeouts=FrozenDict({"inference": 600})
    )
    detector = TimeoutDetector(registry, config=config, now=clock)
    registry.kick("inference", "inference-1")

    clock.advance(300)

    assert detector.state("inference", "inference-1").liveness is Liveness.ALIVE


def test_two_instances_of_one_service_are_tracked_separately(registry, clock):
    """Under A/B hot-swap two instances genuinely run at once (§5).

    Collapsing them by service name would let a healthy new instance's kick vouch for a hung
    old one still holding real work.
    """
    registry.kick("ocr", "ocr-old", "aaaaaaa")
    clock.advance(61)
    registry.kick("ocr", "ocr-new", "bbbbbbb")
    detector = TimeoutDetector(registry, now=clock)

    states = {s.instance_id: s.liveness for s in detector.check_for_silence().states}

    assert states["ocr-old"] is Liveness.SILENT
    assert states["ocr-new"] is Liveness.ALIVE


@pytest.mark.parametrize(("service", "instance"), [("", "ocr-1"), ("ocr", "")])
def test_unattributable_heartbeat_is_rejected(registry, service, instance):
    """A kick that names no instance proves nothing about any instance's liveness."""
    with pytest.raises(InvalidHeartbeat):
        registry.kick(service, instance)


def test_forgetting_a_retired_instance_stops_it_being_reported(registry, clock):
    """An alert that never clears is an alert that stops being read."""
    registry.kick("ocr", "ocr-1")
    clock.advance(61)
    detector = TimeoutDetector(registry, now=clock)
    assert detector.check_for_silence().silent_services == ("ocr",)

    registry.forget("ocr", "ocr-1")

    assert detector.check_for_silence().silent_services == ()


def test_version_commit_rides_the_heartbeat(registry, clock):
    """§5: version/commit rides the heartbeat, never every business response."""
    registry.kick("ocr", "ocr-1", "abc1234")
    tracker = VersionTracker(registry)

    assert tracker.version_for("ocr", "ocr-1") == "abc1234"
    assert tracker.version_for("ocr", "never-kicked") == ""


def test_fleet_versions_show_a_service_running_two_commits(registry, clock):
    """Mid-hot-swap this is normal, expected state — information, never a conflict to resolve.

    Health reports; it does not decide (parent §1), so two commits for one service is a fact
    for the fleet screen rather than something this package tries to reconcile.
    """
    registry.kick("ocr", "ocr-old", "aaaaaaa")
    registry.kick("ocr", "ocr-new", "bbbbbbb")
    tracker = VersionTracker(registry)

    assert tracker.fleet_versions()["ocr"] == ("aaaaaaa", "bbbbbbb")
    assert tracker.instances_by_version("ocr")["aaaaaaa"] == ("ocr-old",)


def test_watchdog_exposes_no_restart_capability():
    """§9's restart-trigger handoff test: Watchdog reports, Supervisor acts.

    The guarantee is an absence, so this looks for one. Nothing in the sub-API's modules may
    grow a restart entry point — the moment one exists, the separation §1 relies on (the code
    deciding "should I restart this" is never the code that might itself be hung) is gone.
    """
    from core.health.watchdog import contracts, kicks, timeout_detector, version_tracking

    for module in (contracts, kicks, timeout_detector, version_tracking):
        names = [n.lower() for n in dir(module)]
        assert not [n for n in names if "restart" in n or "kill" in n]
