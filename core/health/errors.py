"""Health API error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts rather than raised
across the API boundary (`docs/PRINCIPLES.md` §4.1). They exist as real types because the
*internal* call path still benefits from telling them apart — a reservation refused because
the device is full and one refused because Setup never published that device are different
operator problems with different fixes.

**A rejected reservation is not in here, and that is the point.** §5.1 of this API's deep-dive
says a rejection means the caller falls back to CPU or queues, "not that the reservation call
itself fails loudly". Rejection is `ReservationOutcome.rejection_reason`, a normal answer.
This module is only for the cases where Health could not evaluate the request at all.

Health has no equivalent of Auth's raise-loudly carve-out. Health *reports* (§1); a reporting
service whose own failure can take down the thing it is reporting on has inverted its purpose.
The graceful-degradation posture of `docs/PRINCIPLES.md` §4.4 is the default throughout, with
one deliberate exception recorded in `resource_ledger.py`: a device whose ceiling is unknown
is never granted against, because granting against an unknown ceiling is the unsafe answer
rather than the lenient one.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict


class HealthError(Exception):
    """Base for everything this API raises internally, never across its boundary."""


class UnknownService(HealthError):
    """A status or heartbeat query naming a service this process has never heard from.

    Not an error in the reporting direction — a service that has not reported yet is
    `ServiceState.UNKNOWN`, which is a real answer. This is for the query direction, where
    the caller asked about a name that does not exist at all.
    """


class HardwareProfileUnavailable(HealthError):
    """Setup API's published `HardwareProfile` could not be read (§1, §5.1).

    Health reads that profile rather than re-probing hardware, so without it there is no
    device ceiling to check a reservation against. Resolves to a `UNKNOWN_DEVICE` rejection,
    never to a grant: an unknown ceiling is exactly the case where optimism costs a real
    out-of-memory crash in another process.
    """


class ReservationNotFound(HealthError):
    """A release or refresh naming a reservation the ledger has no record of."""


class ReservationExpired(HealthError):
    """A refresh arriving after the reservation's TTL already lapsed (§5.2).

    Deliberately *not* silently re-granted. §11 resolves this case explicitly: a process
    whose reservation lapsed discovers it is gone and aborts its in-flight work cleanly
    rather than continuing to act as if it still holds a resource that may already have been
    handed to someone else. Reviving it here would remove the caller's chance to find out.
    """


class InvalidReservationRequest(HealthError):
    """A non-positive size, an empty device id, an empty owning API name."""


class InsufficientDiagnosticSamples(HealthError):
    """A classification asked for before enough samples exist to mean anything (§3).

    Resolves to a `WorkloadClass.INDETERMINATE` finding rather than a guess. A soft-degradation
    detector that cried wolf on two samples would be ignored exactly as fast as one that never
    fired (§10's own framing of the drift check applies identically here).
    """


class DriftCheckUnavailable(HealthError):
    """A capability drift probe could not be evaluated on this interpreter (§4).

    Degrades to no finding for that capability, never to a `drifted=False` claim. Reporting a
    clean bill of health for a check that did not run is worse than reporting nothing, since
    §4.1's whole reason for returning clean findings is that an operator can trust them.
    """


#: Stable wire codes for the `.proto` surface's own `error_code` fields (§8). Field-only-append
#: discipline applies here the same way it does to the `.proto`: a code is added, never
#: renamed, because a client may be matching on it.
ERROR_CODES: FrozenDict = FrozenDict(
    {
        UnknownService: "UNKNOWN_SERVICE",
        HardwareProfileUnavailable: "HARDWARE_PROFILE_UNAVAILABLE",
        ReservationNotFound: "RESERVATION_NOT_FOUND",
        ReservationExpired: "RESERVATION_EXPIRED",
        InvalidReservationRequest: "INVALID_RESERVATION_REQUEST",
        InsufficientDiagnosticSamples: "INSUFFICIENT_DIAGNOSTIC_SAMPLES",
        DriftCheckUnavailable: "DRIFT_CHECK_UNAVAILABLE",
    }
)

#: One-line operator-facing summaries, keyed by wire code. Kept beside the codes so a caller
#: rendering an error never has to invent its own wording for a condition this API named.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        "UNKNOWN_SERVICE": "No status has ever been reported for that service.",
        "HARDWARE_PROFILE_UNAVAILABLE": (
            "Setup API's hardware profile could not be read, so no device ceiling is known."
        ),
        "RESERVATION_NOT_FOUND": "No reservation exists with that id.",
        "RESERVATION_EXPIRED": (
            "The reservation's TTL lapsed and it was released; acquire a fresh one before "
            "resuming work."
        ),
        "INVALID_RESERVATION_REQUEST": "The reservation request was malformed.",
        "INSUFFICIENT_DIAGNOSTIC_SAMPLES": (
            "Not enough samples yet to classify this operation's workload."
        ),
        "DRIFT_CHECK_UNAVAILABLE": "A capability drift probe could not run on this interpreter.",
        "INTERNAL": "An unmapped internal error.",
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with
    a real detail string is strictly better off than one receiving a crash from the error
    path itself.
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


def summary_for(code: str) -> str:
    """The operator-facing summary for a wire code, or a generic line for an unknown one."""
    return ERROR_SUMMARIES.get(code, ERROR_SUMMARIES["INTERNAL"])


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "DriftCheckUnavailable",
    "HardwareProfileUnavailable",
    "HealthError",
    "InsufficientDiagnosticSamples",
    "InvalidReservationRequest",
    "ReservationExpired",
    "ReservationNotFound",
    "UnknownService",
    "code_for",
    "summary_for",
]
