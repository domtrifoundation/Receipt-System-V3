"""Notifications/Inbox API data contracts (`v3-deepdive-09-notifications-inbox-api.md` §3–§5).

Types only, no logic beyond trivially-derived predicates (`docs/PRINCIPLES.md` §1.1). This is
the single module other packages import from — nothing outside `core/notifications/` should
ever need `inbox.py`, `dispatch.py`, `db.py`, or `channels/`.

Every type here is `@dataclass(frozen=True)`, and any dict-typed field would be a `FrozenDict`
(§2.1) rather than a plain `dict` — a frozen dataclass holding a plain dict is only shallowly
immutable. None of the contracts below happen to carry a dict-typed field today (the closest
candidate, `Notification.reference`, is a plain opaque string — see its own docstring) but the
rule still governs anything added here later, and `isinstance` against a `FrozenDict` must
test `collections.abc.Mapping`, never `dict`: the Python 3.15 builtin is not a `dict` subclass.

**On `Notification.category` being a plain `str`, not a local `Enum`**: `docs/PRINCIPLES.md`
§3.4 requires any new typed/taxonomy data to be registered through Architect API, never
invented locally — and a notification category ("break_glass", "run_complete", ...) is exactly
that kind of taxonomy. `core/architect/contracts.py`'s `DefinitionKind` enum has no
`NOTIFICATION_CATEGORY` member yet, and adding one is Architect's own move
(`docs/templates/new_taxonomy_type.md`), not something this package can do by editing a file
outside its own boundary. Declaring a local `CategoryHint` enum here instead — even one that
mirrors Architect's shape — would be exactly the "ad hoc taxonomy living outside
`core/architect/`" shape `check_no_shadow_taxonomy.yml` exists to catch. So: `category` stays
an unconstrained string, and `CategoryValidator` below is the adapter seam a real Architect
registry client plugs into later, exactly as `AccessChecker` in `core/logs/query.py` is the
seam onto Auth. See `inbox.py`'s `PermissiveCategoryValidator` for the default (accept
anything non-empty) — this is deliberately *not* a security check, so it degrades permissive
rather than failing closed (`docs/PRINCIPLES.md` §4.4), unlike the session/cross-user gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable


def utcnow() -> datetime:
    """Timezone-aware UTC now. Every timestamp in this API is aware, never naive — the same
    reasoning `core/logs/contracts.py::utcnow` and `core/auth/contracts.py::utcnow` state:
    a naive value compared against an aware one raises out of a boundary that returns errors
    as data, never exceptions (`docs/PRINCIPLES.md` §4.1)."""
    return datetime.now(timezone.utc)


#: The two channel names this deep-dive's §4 designs today. A plain tuple, not a `FrozenDict`
#: or an `Enum`: it is already immutable by virtue of being a tuple, and it is a short,
#: internal set of wire-format literals (like `core/auth/contracts.py`'s `AuthMethod` values)
#: rather than a taxonomy a consuming API would register instances against — the distinction
#: `check_no_shadow_taxonomy.yml` cares about is an *extensible* typed thing, and this list is
#: closed by this API's own design, not something another API contributes entries to.
KNOWN_CHANNELS: tuple[str, ...] = ("email", "sms")


class DeliveryOutcome(str, Enum):
    """What happened to one outbound-channel delivery attempt (§4, §7's bounded-retry test).

    `SKIPPED_DISABLED` and `SKIPPED_UNCONFIGURED` are deliberately distinct from `FAILED`:
    a user who opted out, or a channel this install never configured, is not a delivery
    *failure* worth retrying or escalating — it is the channel correctly declining to run at
    all (`docs/PRINCIPLES.md` §4.4). Only `FAILED` drives the bounded-retry-then-escalate path
    in `dispatch.py`.
    """

    SENT = "sent"
    FAILED = "failed"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_UNCONFIGURED = "skipped_unconfigured"


@dataclass(frozen=True)
class Notification:
    """One in-app notification — the one channel that is fully durable (§3).

    `reference` is a *reference* to the event that caused this, never a copy of it (deep-dive
    §1's own "does NOT own" list, and this package's `CLAUDE.md`): a break-glass grant id, a
    run id. Auth's `BreakGlassGrant` and Execution Core's run record stay the source of truth.
    """

    notification_id: str
    user_id: str
    category: str
    title: str
    body: str
    reference: str | None = None
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


@dataclass(frozen=True)
class DeliveryStatus:
    """One outbound-channel attempt's outcome. `attempt` is 1-based and bounded at 3 (§7)."""

    channel: str
    outcome: DeliveryOutcome
    attempt: int = 1
    error_detail: str = ""
    delivered_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == DeliveryOutcome.SENT


@dataclass(frozen=True)
class ChannelPreference:
    """Per-user channel opt-in (§5). **Opt-in, not opt-out**: `enabled` defaults to `False`,
    matching the deep-dive's own "a user who never enabled email/SMS delivery only ever sees
    in-app notifications" — never sending unsolicited external messages to someone who never
    asked for them.

    `contact_override` is an alternate address for *this channel specifically* (e.g. a
    different notification email than the account's SSO email) — resolving the default
    address when no override is set is `dispatch.py`'s `RecipientResolver` seam onto Auth's
    own `User` record, not this contract's concern.
    """

    user_id: str
    channel: str
    enabled: bool = False
    contact_override: str | None = None


@dataclass(frozen=True)
class NotifyRequest:
    """What a consumer API (Auth's break-glass, Execution Core, Content Security, Account
    Guardian, Review/Flagging — deep-dive §1's own list) asks for: deliver a signal to one
    user. This API decides *how* it reaches them; the caller has already decided *that* and
    *when* (deep-dive §1) — this request carries no scheduling or channel-selection fields."""

    user_id: str
    category: str
    title: str
    body: str
    reference: str | None = None


# --------------------------------------------------------------------- results
# Errors are data at this API's boundary, never exceptions raised across it
# (`docs/PRINCIPLES.md` §4.1). Every result below carries `error_code`/`error_detail`.


@dataclass(frozen=True)
class NotifyResult:
    """The in-app half is `ok=True` unless the write itself failed — an outbound channel
    failing never fails this result (deep-dive §8's resolved delivery-failure handling), it is
    only visible in `channel_statuses`."""

    ok: bool
    notification: Notification | None = None
    channel_statuses: tuple[DeliveryStatus, ...] = ()
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class InboxQuery:
    """A read request. Carries who is asking, not just what is asked for — the same split
    `core/logs/contracts.py::LogQuery` uses for the identical reason.

    `requesting_user_id` is the *authenticated caller*, resolved server-side in `service.py`
    from the caller's own session and never taken from a wire field the caller could set
    itself (see this package's `CLAUDE.md` for why that is a stronger posture than Logs' own
    `requesting_user_id`, which does arrive as a wire field). When it differs from `user_id`,
    the read is a cross-user read and needs an active break-glass grant, checked through Auth.
    """

    user_id: str
    requesting_user_id: str | None = None
    unread_only: bool = False
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class InboxQueryResult:
    notifications: tuple[Notification, ...] = ()
    total_matching: int = 0
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class MarkReadResult:
    ok: bool
    notification_id: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class PreferencesResult:
    preferences: tuple[ChannelPreference, ...] = ()
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class SetPreferenceResult:
    ok: bool
    preference: ChannelPreference | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class NotificationsMetrics:
    """An immutable snapshot of the counters `metrics.py` keeps."""

    notifications_created: int = 0
    notifications_creation_failed: int = 0
    inbox_reads_served: int = 0
    inbox_reads_denied: int = 0
    inbox_marked_read: int = 0
    channel_sends_attempted: int = 0
    channel_sends_succeeded: int = 0
    channel_sends_failed: int = 0
    channel_sends_skipped_disabled: int = 0
    channel_sends_skipped_unconfigured: int = 0
    channel_send_retries: int = 0
    channel_failures_escalated: int = 0


# ------------------------------------------------------------------- providers
# Protocol seams for pluggable capabilities (`docs/PRINCIPLES.md` §1.2, §1.3). Concrete
# defaults and adapters live in the modules that consume them (`inbox.py`, `dispatch.py`),
# the same split `core/logs/query.py` uses for `AccessChecker` — keeping a Protocol here
# without a body is a type, not logic, so it stays inside §1.1's "contracts.py has no logic".


@runtime_checkable
class CategoryValidator(Protocol):
    """The Architect-registry seam for `Notification.category` (see this module's own
    docstring on why `category` is a plain string rather than a local enum). Returns whether
    this build should accept the category — never raises, since this is not a security
    check and a validator that cannot answer degrades to permissive (§4.4)."""

    def is_known(self, category: str) -> bool: ...


@runtime_checkable
class SessionResolver(Protocol):
    """The seam onto Auth & Tenancy for resolving *who is actually calling* from a session,
    never from a value the caller asserts about itself. `service.py` is the only place this
    is invoked; `inbox.py` and `dispatch.py` only ever see the already-resolved
    `requesting_user_id`."""

    def resolve(self, session_id: str) -> str | None:
        """The authenticated user id for this session, or `None` if it cannot be resolved —
        treated as denial, never as permission (`docs/PRINCIPLES.md` §4.2)."""


@runtime_checkable
class CrossUserAccessChecker(Protocol):
    """The seam onto Auth's break-glass grants for a staff/owner read of another user's
    inbox — identical in shape to `core/logs/query.py::AccessChecker`, and deliberately not a
    second permission mechanism invented here."""

    def allow_cross_user(self, requesting_user_id: str | None, subject_user_id: str) -> bool:
        """True only with an active break-glass grant. Raises if it genuinely cannot tell;
        the caller treats that the same as `False` but logs it distinctly."""


__all__ = [
    "KNOWN_CHANNELS",
    "CategoryValidator",
    "ChannelPreference",
    "CrossUserAccessChecker",
    "DeliveryOutcome",
    "DeliveryStatus",
    "InboxQuery",
    "InboxQueryResult",
    "MarkReadResult",
    "Notification",
    "NotificationsMetrics",
    "NotifyRequest",
    "NotifyResult",
    "PreferencesResult",
    "SessionResolver",
    "SetPreferenceResult",
    "utcnow",
]
