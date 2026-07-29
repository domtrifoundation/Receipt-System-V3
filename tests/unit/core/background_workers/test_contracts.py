"""Background Workers' frozen contracts (`docs/PRINCIPLES.md` §2.1, §2.1.1).

The `forward_compat`-marked tests cover `DEFAULT_CADENCE_SECONDS` and the error tables, all
module-level constant lookup tables §2.1.1 reaches. On 3.15 the builtin `frozendict` is not a
`dict` subclass, so an `isinstance(x, dict)` check against one silently takes the wrong branch
— here that would mean a job's shipping cadence reading as unset and the job never being
scheduled at all, which on unattended work is invisible until someone asks why the sweep never
ran.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest

from core.background_workers.contracts import (
    DEFAULT_CADENCE_SECONDS,
    GLOBAL_SCOPE,
    MAX_CONSECUTIVE_FAILURES,
    IdleWindow,
    JobClass,
    JobHealth,
    JobOutcome,
    JobRegistration,
    JobRunResult,
)
from core.background_workers.errors import ERROR_CODES, ERROR_SUMMARIES
from core.background_workers.registry import KNOWN_JOBS

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)


@pytest.mark.forward_compat
def test_module_level_lookup_tables_are_mappings_not_dict_subclasses():
    for table in (DEFAULT_CADENCE_SECONDS, KNOWN_JOBS, ERROR_CODES, ERROR_SUMMARIES):
        assert isinstance(table, Mapping)


@pytest.mark.forward_compat
def test_the_cadence_table_cannot_be_rewritten_at_runtime():
    """A cadence mutable at runtime makes "how often does this run" depend on what ran before."""
    with pytest.raises(Exception):
        DEFAULT_CADENCE_SECONDS["expired_session_cleanup"] = 1  # type: ignore[index]


@pytest.mark.forward_compat
def test_the_job_inventory_cannot_be_rewritten_at_runtime():
    """`KNOWN_JOBS` is the answer to "what does this program do unattended".

    An inventory something could append to at runtime would make that answer depend on import
    order, which is the opposite of the discoverability §6.5 wants from it.
    """
    with pytest.raises(Exception):
        KNOWN_JOBS["something_new"] = "somewhere"  # type: ignore[index]


def test_event_triggered_is_derived_from_the_absence_of_an_interval():
    """§6.2 uses `interval_seconds=None` for exactly this, and a derived property cannot be
    set inconsistently with the field it reads."""
    timed = JobRegistration(
        job_id="a", owning_api="logs", job_class=JobClass.ASYNC_IO, interval_seconds=60
    )
    evented = JobRegistration(job_id="b", owning_api="telemetrees", job_class=JobClass.ASYNC_IO)

    assert not timed.event_triggered
    assert evented.event_triggered


def test_a_job_defaults_to_system_wide_scope():
    """The safe default: a job whose author did not think about scope touches no user's data.

    Defaulting to a per-user scope would require a user id nobody supplied, and defaulting to
    "check every user" would make one busy user block every other user's maintenance.
    """
    job = JobRegistration(job_id="a", owning_api="logs", job_class=JobClass.ASYNC_IO)

    assert job.scope == GLOBAL_SCOPE
    assert not job.idle_only


def test_disabled_is_derived_from_the_timestamp_not_stored_twice():
    assert not JobHealth(job_id="a").disabled
    assert JobHealth(job_id="a", disabled_at=NOW).disabled


def test_run_duration_is_derived_from_the_two_timestamps():
    result = JobRunResult(
        job_id="a",
        outcome=JobOutcome.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2.5),
    )

    assert result.duration_seconds == pytest.approx(2.5)


def test_an_idle_window_always_carries_a_reason():
    """A scheduler skipping a job must be able to say why in one line.

    A bare False leaves an operator reading source to find out what the check even consulted.
    """
    window = IdleWindow(scope="user-1", idle=False, reason="2 active run(s)")

    assert window.reason


@pytest.mark.parametrize(
    "cls", [JobRegistration, JobHealth, JobRunResult, IdleWindow]
)
def test_every_contract_is_frozen(cls):
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_the_failure_guard_threshold_is_the_documented_five():
    """§10 resolves this as five, and a silently different number would make the guard's
    documented behaviour a lie rather than a tunable."""
    assert MAX_CONSECUTIVE_FAILURES == 5


def test_every_error_code_has_an_operator_summary():
    for code in ERROR_CODES.values():
        assert ERROR_SUMMARIES.get(code)
