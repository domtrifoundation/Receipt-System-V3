"""`update_supervisor()` — §4.2's own two-phase verified re-exec. §10's own named
priority: "the single most important test in this entire document" is the failing-smoke-
test case confirming the old Supervisor keeps running untouched."""

from __future__ import annotations

import sys

from supervisor.self_update.reexec import update_supervisor

from ..conftest import run


def test_refuses_without_owner_confirmation():
    result = run(update_supervisor([sys.executable, "-c", "print(1)"], owner_confirmed=False))

    assert result.ok is False
    assert "owner confirmation" in result.error_detail


def test_a_passing_smoke_test_hands_off():
    handed_off = []

    async def handoff():
        handed_off.append(True)

    result = run(update_supervisor(
        [sys.executable, "-c", "import sys; sys.exit(0)"], owner_confirmed=True, handoff=handoff,
    ))

    assert result.ok is True
    assert result.smoke_test_passed is True
    assert result.handed_off is True
    assert handed_off == [True]


def test_a_passing_smoke_test_with_no_handoff_callback_does_not_hand_off():
    result = run(update_supervisor([sys.executable, "-c", "import sys; sys.exit(0)"], owner_confirmed=True))

    assert result.ok is True
    assert result.handed_off is False


def test_a_failing_smoke_test_never_hands_off_and_the_old_instance_is_untouched():
    """The single most important test per §10 — a deliberately broken new build must
    never trigger handoff."""
    handed_off = []

    async def handoff():
        handed_off.append(True)

    result = run(update_supervisor(
        [sys.executable, "-c", "print('boom: config unreadable'); import sys; sys.exit(1)"],
        owner_confirmed=True, handoff=handoff,
    ))

    assert result.ok is False
    assert result.smoke_test_passed is False
    assert "boom" in result.error_detail
    assert handed_off == []


def test_a_hanging_smoke_test_times_out_and_never_hands_off():
    handed_off = []

    async def handoff():
        handed_off.append(True)

    result = run(update_supervisor(
        [sys.executable, "-c", "import time; time.sleep(30)"], owner_confirmed=True, handoff=handoff, timeout_seconds=1.0,
    ))

    assert result.ok is False
    assert "timed out" in result.error_detail
    assert handed_off == []


def test_smoke_test_flag_is_appended_when_not_already_present():
    from supervisor.self_update.reexec import SMOKE_TEST_FLAG

    result = run(update_supervisor(
        [sys.executable, "-c", f"import sys; sys.exit(0 if {SMOKE_TEST_FLAG!r} in sys.argv else 1)"],
        owner_confirmed=True,
    ))

    assert result.ok is True
