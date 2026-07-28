"""Notifications/Inbox API error taxonomy.

These are surfaced as `error_code`/`error_detail` on the result contracts rather than raised
across the gRPC boundary (`docs/PRINCIPLES.md` §4.1). They exist as real types because the
*internal* call path still benefits from telling them apart — a full inbox store and a denied
cross-user read are different problems with different operator responses, the same reasoning
`core/logs/errors.py` and `core/audit/errors.py` state for their own packages.

This API has no equivalent of Auth's raise-loudly carve-out. Nothing here is a session or role
failure in Auth's own sense — the closest analogue, a denied cross-user inbox read, is data a
caller can display, not a security failure whose call stack must unwind loudly.

Two postures sit side by side, mirroring `core/logs/errors.py`'s own split:

- **The identity/cross-user gate fails closed** (§4.2): an unresolvable session, an absent
  checker, or a checker that cannot be reached are all denials, never a silent bypass.
- **Everything else degrades gracefully** (§4.4): a channel that cannot send degrades that
  channel alone and is reported in `DeliveryStatus`/metrics; it never fails the in-app write
  that is this API's own durable guarantee.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

# --------------------------------------------------------------- wire codes
# Stable strings, field-only-append discipline (`docs/templates/new_grpc_endpoint.md`): a code
# is added, never renamed or reused — a caller may be matching on it.

E_INVALID_NOTIFICATION = "INVALID_NOTIFICATION"
E_CROSS_USER_ACCESS_DENIED = "CROSS_USER_ACCESS_DENIED"
E_ACCESS_CHECK_UNAVAILABLE = "ACCESS_CHECK_UNAVAILABLE"
E_SESSION_UNRESOLVABLE = "SESSION_UNRESOLVABLE"
E_NOTIFICATION_NOT_FOUND = "NOTIFICATION_NOT_FOUND"
E_STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
E_INVALID_QUERY = "INVALID_QUERY"
E_INVALID_PREFERENCE = "INVALID_PREFERENCE"

#: Operator-facing one-liners, kept next to the codes so a client that only has the code still
#: has something to show. `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — a module-level lookup
#: table nothing should ever write, read concurrently across real OS threads.
ERROR_SUMMARIES: FrozenDict = FrozenDict(
    {
        E_INVALID_NOTIFICATION: "the notification request is missing a required field",
        E_CROSS_USER_ACCESS_DENIED: (
            "this caller has no active break-glass grant for the requested user's inbox"
        ),
        E_ACCESS_CHECK_UNAVAILABLE: "the break-glass grant could not be checked",
        E_SESSION_UNRESOLVABLE: "the caller's session could not be resolved to a user",
        E_NOTIFICATION_NOT_FOUND: "no notification with that id exists for this user",
        E_STORE_UNAVAILABLE: "the per-user inbox store could not be reached",
        E_INVALID_QUERY: "the inbox query is not usable",
        E_INVALID_PREFERENCE: "the channel preference is not usable",
    }
)


# ------------------------------------------------------------- internal types


class NotificationsError(Exception):
    """Base for everything this package raises internally, never across its gRPC boundary."""


class InvalidNotification(NotificationsError):
    """A `NotifyRequest` is missing a field the in-app record cannot be trusted without."""


class CrossUserAccessDenied(NotificationsError):
    """A read of another user's inbox with no active break-glass grant (§4, and this
    package's own gate — identical in shape to `core/logs/errors.py::CrossUserAccessDenied`)."""


class AccessCheckUnavailable(NotificationsError):
    """Auth could not be reached to evaluate a cross-user read.

    Treated as denial, never as permission (`docs/PRINCIPLES.md` §4.2): an unavailable
    security check means unsafe, never a silent bypass.
    """


class SessionUnresolvable(NotificationsError):
    """The caller's session did not resolve to a user at all — the fail-closed default when
    no real `SessionResolver` is wired up yet, mirroring Audit's `deny_all_roles`."""


class NotificationNotFound(NotificationsError):
    """A `mark_read` targeting an id that does not exist for the resolved user."""


class StoreUnavailable(NotificationsError):
    """The per-user SQLite store could not be opened or written to."""


class InvalidQuery(NotificationsError):
    """A malformed read request — a negative limit, an empty subject user id."""


class InvalidPreference(NotificationsError):
    """A channel preference naming a channel this build does not recognise, or an override
    contact address that is empty when `enabled=True`."""


#: Exception type -> stable wire code. `code_for` is the one place this mapping is read;
#: `FrozenDict` because it is a module-level constant nothing should mutate (§2.1.1).
ERROR_CODES: FrozenDict = FrozenDict(
    {
        InvalidNotification: E_INVALID_NOTIFICATION,
        CrossUserAccessDenied: E_CROSS_USER_ACCESS_DENIED,
        AccessCheckUnavailable: E_ACCESS_CHECK_UNAVAILABLE,
        SessionUnresolvable: E_SESSION_UNRESOLVABLE,
        NotificationNotFound: E_NOTIFICATION_NOT_FOUND,
        StoreUnavailable: E_STORE_UNAVAILABLE,
        InvalidQuery: E_INVALID_QUERY,
        InvalidPreference: E_INVALID_PREFERENCE,
    }
)


def code_for(exc: BaseException) -> str:
    """The wire code for an internal error, or `INTERNAL` for anything unmapped.

    Unmapped is deliberately not an exception of its own: a caller receiving `INTERNAL` with a
    real detail string is strictly better off than one receiving a crash from the error path
    itself (matches `core/logs/errors.py::code_for`'s own reasoning).
    """
    return ERROR_CODES.get(type(exc), "INTERNAL")


__all__ = [
    "ERROR_CODES",
    "ERROR_SUMMARIES",
    "E_ACCESS_CHECK_UNAVAILABLE",
    "E_CROSS_USER_ACCESS_DENIED",
    "E_INVALID_NOTIFICATION",
    "E_INVALID_PREFERENCE",
    "E_INVALID_QUERY",
    "E_NOTIFICATION_NOT_FOUND",
    "E_SESSION_UNRESOLVABLE",
    "E_STORE_UNAVAILABLE",
    "AccessCheckUnavailable",
    "CrossUserAccessDenied",
    "InvalidNotification",
    "InvalidPreference",
    "InvalidQuery",
    "NotificationNotFound",
    "NotificationsError",
    "SessionUnresolvable",
    "StoreUnavailable",
    "code_for",
]
