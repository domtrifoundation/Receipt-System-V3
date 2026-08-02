"""Audit/Event Log error taxonomy.

These are surfaced as the `error`/`error_detail` pair on the result types in `contracts.py`,
and as `error_code`/`error_detail` on the wire — never raised across the gRPC boundary
(`docs/PRINCIPLES.md` §4.1). Audit has no equivalent of Auth's deliberate raise-loudly
carve-out: a caller here is reporting that a privileged action already happened, and
blowing up its call stack after the fact does not un-happen it.

The exception classes below are for the *internal* call path only — the writer distinguishing
"the primary sink is unreachable" from "this event is malformed" is genuinely useful inside
the package. Every one of them is caught before it reaches a boundary.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

# --------------------------------------------------------------- wire codes
# Stable strings. Like `ActionType` values and `.proto` field numbers, a code is added or
# deprecated, never renamed or reused — a caller may be branching on it.

E_INVALID_EVENT = "INVALID_EVENT"
E_REASON_REQUIRED = "REASON_REQUIRED"
E_UNKNOWN_ACTION = "UNKNOWN_ACTION"
E_SINK_UNAVAILABLE = "SINK_UNAVAILABLE"
E_WRITE_FAILED = "WRITE_FAILED"
E_ROLE_FORBIDDEN = "ROLE_FORBIDDEN"
E_READ_FAILED = "READ_FAILED"
E_RETENTION_BELOW_BASELINE = "RETENTION_BELOW_BASELINE"
E_RETENTION_INVALID = "RETENTION_INVALID"
E_PURGE_DISABLED = "PURGE_DISABLED"
E_PURGE_FAILED = "PURGE_FAILED"
E_APPEND_ONLY_VIOLATION = "APPEND_ONLY_VIOLATION"

#: Operator-facing one-liners, kept next to the codes so a client that only has the code
#: still has something to show. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — a
#: module-level lookup table nothing should ever write.
ERROR_SUMMARIES: FrozenDict = FrozenDict({
    E_INVALID_EVENT: "the submitted audit event is missing a required field",
    E_REASON_REQUIRED: "this action type requires a stated reason",
    E_UNKNOWN_ACTION: "no such privileged action is registered",
    E_SINK_UNAVAILABLE: "the primary audit sink could not be reached",
    E_WRITE_FAILED: "the audit record was not written",
    E_ROLE_FORBIDDEN: "audit history is visible to staff and owner roles only",
    E_READ_FAILED: "the audit query could not be completed",
    E_RETENTION_BELOW_BASELINE: (
        "retention below the 10-year BIR RR No. 17-2013 / RR 5-2014 baseline requires an "
        "explicit override"
    ),
    E_RETENTION_INVALID: "the retention configuration is not usable",
    E_PURGE_DISABLED: "retention mode is 'indefinite'; nothing is ever purged",
    E_PURGE_FAILED: "the retention purge did not complete",
    E_APPEND_ONLY_VIOLATION: (
        "an UPDATE or DELETE was attempted against the audit table and denied at the "
        "connection level"
    ),
})


# ------------------------------------------------------------- internal types


class AuditError(Exception):
    """Base for everything this package raises internally. Never crosses a boundary."""

    code: str = E_WRITE_FAILED


class InvalidEvent(AuditError):
    """A submitted event is missing a field the record cannot be trusted without."""

    code = E_INVALID_EVENT


class ReasonRequired(InvalidEvent):
    """`AuditEvent.reason` is mandatory for this action type."""

    code = E_REASON_REQUIRED


class UnknownPrivilegedAction(AuditError):
    """A caller named an operation absent from `contracts.PRIVILEGED_ACTIONS`.

    Deliberately an error rather than a silently-accepted free-form string: the coverage
    guarantee in the deep-dive's §7 only means something if the set of privileged actions is
    closed and checkable.
    """

    code = E_UNKNOWN_ACTION


class SinkUnavailable(AuditError):
    """A sink could not be written to. Fatal for the primary, degrading for a mirror."""

    code = E_SINK_UNAVAILABLE


class RoleForbidden(AuditError):
    """A non-staff, non-owner caller asked to read the audit log.

    Fails closed: an unrecognised or absent role is denied, never defaulted to permitted
    (`docs/PRINCIPLES.md` §4.2).
    """

    code = E_ROLE_FORBIDDEN


class RetentionBelowBaseline(AuditError):
    """A retention period shorter than the BIR baseline, with no explicit override."""

    code = E_RETENTION_BELOW_BASELINE


class AppendOnlyViolation(AuditError):
    """The SQLite authorizer denied an UPDATE or DELETE against the audit table.

    Reaching this means code inside this package tried to mutate the log. That is a bug in
    this package, and the connection-level authorizer catching it is the point (§3.2).
    """

    code = E_APPEND_ONLY_VIOLATION


__all__ = [
    "AppendOnlyViolation",
    "AuditError",
    "ERROR_SUMMARIES",
    "E_APPEND_ONLY_VIOLATION",
    "E_INVALID_EVENT",
    "E_PURGE_DISABLED",
    "E_PURGE_FAILED",
    "E_READ_FAILED",
    "E_REASON_REQUIRED",
    "E_RETENTION_BELOW_BASELINE",
    "E_RETENTION_INVALID",
    "E_ROLE_FORBIDDEN",
    "E_SINK_UNAVAILABLE",
    "E_UNKNOWN_ACTION",
    "E_WRITE_FAILED",
    "InvalidEvent",
    "ReasonRequired",
    "RetentionBelowBaseline",
    "RoleForbidden",
    "SinkUnavailable",
    "UnknownPrivilegedAction",
]
