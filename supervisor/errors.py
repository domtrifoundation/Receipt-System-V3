"""Supervisor's error taxonomy.

Surfaced as data on the result contracts (`contracts.py`) rather than raised across this
package's own boundary (`docs/PRINCIPLES.md` §4.1) — a service that fails to boot, a
rollback with nothing to revert to, an unavailable target clone are all ordinary,
expected outcomes for something whose whole job is watching things fail and deciding
what to do about it.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class SupervisorInternalError(Exception):
    """Base for everything this package raises internally, never across its boundary."""


class UnknownChannel(SupervisorInternalError):
    """A channel with no `ActiveRelease` on record at all."""


class NoPriorRelease(SupervisorInternalError):
    """§3.3's rollback has nothing to revert to — no prior release directory is on
    record for this channel. Update API's own garbage collection always keeps current
    plus at least one prior, so this should not happen against a correctly-run install;
    reported as data rather than assumed impossible."""


class ServiceLaunchFailed(SupervisorInternalError):
    """A service's own subprocess could not even be started — a missing venv, a missing
    entry-point module, or the interpreter itself failing to launch."""


class ServiceNeverBecameHealthy(SupervisorInternalError):
    """A launched service never became reachable within its own timeout — Boot
    Sequence's own §3.2 "a service that fails to come up within a timeout surfaces
    clearly, never silently hangs" case."""


class TargetCloneUnavailable(SupervisorInternalError):
    """§5.4 step 1's own gate — the target version's release clone does not exist, or is
    not health-check-capable. Checked *before* the currently-running instance is ever
    stopped, since that is the one step in this whole restart whose failure is
    recoverable."""


class SmokeTestFailed(SupervisorInternalError):
    """§4.2's own two-phase self-update gate — the new Supervisor build could not prove
    it can read config, locate active releases, and report healthy without touching live
    service state. The old Supervisor keeps running untouched."""


ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownChannel: "UNKNOWN_CHANNEL",
        NoPriorRelease: "NO_PRIOR_RELEASE",
        ServiceLaunchFailed: "SERVICE_LAUNCH_FAILED",
        ServiceNeverBecameHealthy: "SERVICE_NEVER_BECAME_HEALTHY",
        TargetCloneUnavailable: "TARGET_CLONE_UNAVAILABLE",
        SmokeTestFailed: "SMOKE_TEST_FAILED",
    }
)

ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_CHANNEL": "No active release is on record for that channel.",
        "NO_PRIOR_RELEASE": "There is no prior release directory to roll back to.",
        "SERVICE_LAUNCH_FAILED": "The service's own subprocess could not be started.",
        "SERVICE_NEVER_BECAME_HEALTHY": "The service never became reachable within its own timeout.",
        "TARGET_CLONE_UNAVAILABLE": "The target version's release clone does not exist or is not health-check-capable.",
        "SMOKE_TEST_FAILED": "The new Supervisor build failed its own smoke test; the old instance keeps running.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "NoPriorRelease",
    "ServiceLaunchFailed",
    "ServiceNeverBecameHealthy",
    "SmokeTestFailed",
    "SupervisorInternalError",
    "TargetCloneUnavailable",
    "UnknownChannel",
    "code_for",
    "summary_for",
]
