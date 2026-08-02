"""Audit/Event Log data contracts (`v3-deepdive-08-audit-event-log-api.md` §4, §5).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in
this package that anything outside `core/audit/` imports from.

Two things here are load-bearing rather than stylistic:

* **`AuditEvent.details` is a `FrozenDict`, never a plain `dict`.** A frozen dataclass with
  a plain dict field is only shallowly immutable, and an append-only audit record whose
  payload could be mutated in place after the fact would be a real — and, for this API
  specifically, ironic — hole (`docs/PRINCIPLES.md` §2.1, deep-dive §4). Anything checking
  the type of such a field must test `collections.abc.Mapping`; the Python 3.15 builtin
  `frozendict` is not a `dict` subclass and `isinstance(x, dict)` silently misses it.
* **There is no mutating result type here.** No `UpdateEventRequest`, no `DeleteEventResult`.
  The absence is the guarantee (deep-dive §3.2): a correction to a prior entry is a *new*
  event carrying `corrects_event_id`, never an edit to the original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from common.frozen_dict import FrozenDict


class ActionType(str, Enum):
    """The privileged actions this project records.

    The first eight are the deep-dive's own §4 list verbatim. The remainder close a real
    gap between §4 and §7: §7's privileged-action coverage test names `ForceWake`,
    `PinServiceVersion`, agent-token issuance and `is_group_manager` toggles as actions
    that must produce an audit entry, but §4's enum had no member capable of representing
    any of them. `RETENTION_PURGE_EXECUTED` is the same kind of addition for §5 — a
    retention purge that left no trace of itself would be the one deletion this log could
    not account for. See this package's CLAUDE.md; these additions are flagged, not quiet.

    Values are stable wire strings. Adding a member is fine; renaming or reusing a value is
    not, for the same reason a `.proto` field number is never reused — historical rows carry
    the old string forever.
    """

    BREAK_GLASS_GRANTED = "break_glass_granted"
    BREAK_GLASS_REVOKED = "break_glass_revoked"
    VENDOR_CONTRIBUTION_APPROVED = "vendor_contribution_approved"
    VENDOR_CONTRIBUTION_REJECTED = "vendor_contribution_rejected"
    CONFIG_CHANGED = "config_changed"
    ROLE_CHANGED = "role_changed"
    CONTENT_CONFIRMED_MALICIOUS = "content_confirmed_malicious"
    ACCOUNT_RECOVERY_APPROVED = "account_recovery_approved"

    # --- additions covering §7's own coverage list, see the docstring above --------
    AGENT_TOKEN_ISSUED = "agent_token_issued"
    AGENT_TOKEN_REVOKED = "agent_token_revoked"
    SERVICE_FORCE_WOKEN = "service_force_woken"
    SERVICE_VERSION_PINNED = "service_version_pinned"
    GROUP_MANAGER_TOGGLED = "group_manager_toggled"
    RETENTION_PURGE_EXECUTED = "retention_purge_executed"


#: The structural half of §7's privileged-action coverage test: the canonical operation
#: name every other API uses when it reports a privileged action, mapped to the `ActionType`
#: that operation must produce. The test walks this table rather than trusting each caller
#: to have remembered — "a structural check against the list, not per-action trust."
#:
#: `FrozenDict`, not `dict`, because a module-level lookup table nothing should ever write
#: is exactly what §2.1.1 covers, and this one is read concurrently from real OS threads.
PRIVILEGED_ACTIONS: FrozenDict = FrozenDict({
    "break_glass_grant": ActionType.BREAK_GLASS_GRANTED,
    "break_glass_revoke": ActionType.BREAK_GLASS_REVOKED,
    "vendor_contribution_approve": ActionType.VENDOR_CONTRIBUTION_APPROVED,
    "vendor_contribution_reject": ActionType.VENDOR_CONTRIBUTION_REJECTED,
    "config_change": ActionType.CONFIG_CHANGED,
    "role_change": ActionType.ROLE_CHANGED,
    "content_confirm_malicious": ActionType.CONTENT_CONFIRMED_MALICIOUS,
    "account_recovery_approve": ActionType.ACCOUNT_RECOVERY_APPROVED,
    "agent_token_issue": ActionType.AGENT_TOKEN_ISSUED,
    "agent_token_revoke": ActionType.AGENT_TOKEN_REVOKED,
    "force_wake": ActionType.SERVICE_FORCE_WOKEN,
    "pin_service_version": ActionType.SERVICE_VERSION_PINNED,
    "is_group_manager_toggle": ActionType.GROUP_MANAGER_TOGGLED,
    "retention_purge": ActionType.RETENTION_PURGE_EXECUTED,
})

#: Actions for which `AuditEvent.reason` is mandatory rather than optional. Break-glass is
#: Auth's own stated requirement; the rest are here because an irreversible or user-visible
#: staff decision recorded with no stated reason is not usable evidence later.
REASON_REQUIRED_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.BREAK_GLASS_GRANTED,
    ActionType.CONTENT_CONFIRMED_MALICIOUS,
    ActionType.ACCOUNT_RECOVERY_APPROVED,
})

#: Read access is staff/owner only, never client role (deep-dive §4). A client learning that
#: a staff member accessed their folder is Notifications' job, already served directly by
#: Auth's break-glass design — this API does not serve it a second way.
AuditorRole = Literal["client", "staff", "owner"]

READER_ROLES: frozenset[str] = frozenset({"staff", "owner"})


class RetentionMode(str, Enum):
    """`fixed` auto-deletes past the horizon; `indefinite` never purges at all (§5)."""

    FIXED = "fixed"
    INDEFINITE = "indefinite"


#: 10 years, matching BIR Revenue Regulations No. 17-2013 as amended by RR 5-2014, which
#: requires books of accounts and accounting records to be preserved for ten (10) years
#: reckoned from the day following the deadline for filing the return for the taxable year.
#: Researched, not guessed — `v3-deepdive-06-account-guardian-api.md` §7 arrives at the same
#: regulation independently. Never lowered without an explicit override; see
#: `RetentionPolicy` and `retention.py`.
DEFAULT_RETENTION_DAYS = 3650

#: The regulation citation carried into the TUI settings surface itself, so an owner
#: changing the value is making an informed choice against the real legal context rather
#: than adjusting an unexplained number (§5). These are the `MenuItemSpec` fields Interface
#: API's own menu data provides for exactly this purpose — declared here as plain data so
#: this package does not import Interface's own types (assumption noted in CLAUDE.md).
RETENTION_SETTING_SPEC: FrozenDict = FrozenDict({
    "key": "audit.retention_days",
    "label": "Audit log retention (days)",
    "default": DEFAULT_RETENTION_DAYS,
    "tooltip": (
        "How long privileged-action audit records are kept. The 3650-day (10 year) default "
        "matches BIR Revenue Regulations No. 17-2013, as amended by RR 5-2014, which "
        "requires accounting records to be preserved for ten years. Raising this, or "
        "setting retention mode to 'indefinite', is always safe. Lowering it below the "
        "default requires a deliberate override and may put this installation out of "
        "compliance with Philippine record-retention law."
    ),
    "docs_ref": "docs/apis/v3-deepdive-08-audit-event-log-api.md#5-retention",
})


@dataclass(frozen=True)
class RetentionPolicy:
    """Resolved retention configuration (§5).

    `shorten_override` exists so that going below the researched legal baseline is a
    deliberate, recorded act rather than a quiet edit to a number — `docs/PRINCIPLES.md`
    §4.3's "never silently override" applied to a config value instead of a data conflict.
    """

    retention_days: int = DEFAULT_RETENTION_DAYS
    mode: RetentionMode = RetentionMode.FIXED
    shorten_override: bool = False
    shorten_override_reason: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    """One privileged, security-relevant action. Written once, never altered (§3.2).

    `corrects_event_id` is how a correction is expressed: a new event pointing at the one it
    corrects. There is deliberately no path anywhere that edits the original.
    """

    event_id: str
    action_type: ActionType
    actor_user_id: str
    occurred_at: datetime
    target_user_id: str | None = None
    reason: str | None = None
    details: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    corrects_event_id: str | None = None


@dataclass(frozen=True)
class AuditQueryFilter:
    """Read-side filter (§4). Every field optional; an empty filter reads the whole log."""

    action_types: tuple[ActionType, ...] = ()
    actor_user_id: str | None = None
    target_user_id: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 100
    offset: int = 0


# --------------------------------------------------------------------- results
# Errors are data at this API's boundary, never exceptions raised across it
# (`docs/PRINCIPLES.md` §4.1). Every result below carries `error`/`error_detail`, and every
# caller checks `error` rather than wrapping the call in try/except. The error code strings
# themselves live in `errors.py`.


@dataclass(frozen=True)
class RecordResult:
    """`degraded_sinks` holds the `AuditSink.name` of each mirror that failed while the
    primary write succeeded — bare names, so a caller can match one against a registered
    sink. The reason a mirror failed belongs in the operational trace (Logs API), not in a
    string a caller has to parse a name back out of.

    The split is deliberate (`docs/PRINCIPLES.md` §4.2/§4.4): a failed *primary* write is an
    error, because a caller that believes it recorded an audit entry when it did not is the
    exact failure this API cannot have. A failed *mirror* degrades and is reported, because
    losing a redundant copy is not a reason to fail the privileged action itself.
    """

    recorded: bool
    event_id: str | None = None
    degraded_sinks: tuple[str, ...] = ()
    error: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class AuditQueryResult:
    events: tuple[AuditEvent, ...] = ()
    total_matching: int = 0
    error: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class PurgeResult:
    purged: int = 0
    horizon: datetime | None = None
    error: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class RetentionResolution:
    policy: RetentionPolicy | None = None
    error: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class AuditMetrics:
    """What Health and Telemetrees can ask this API about itself (`metrics.py`)."""

    total_events: int = 0
    events_by_action: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    oldest_occurred_at: datetime | None = None
    newest_occurred_at: datetime | None = None
    events_past_horizon: int = 0
    database_bytes: int = 0
    error: str | None = None
    error_detail: str | None = None


# ------------------------------------------------------------------- providers


@runtime_checkable
class AuditSink(Protocol):
    """A destination an audit event is written to (`docs/PRINCIPLES.md` §1.2).

    More than one sink runs at once by design, not one selected from config: the SQLite
    sink is the mandatory primary, and an installation that needs a second, independently
    controlled copy of its privileged-action trail (a WORM volume, an off-box appliance)
    registers a mirror alongside it rather than replacing it. That is the shape where
    running several simultaneously adds real value, which is §1.2's own test for it.

    Note what this Protocol does *not* declare: no update, no delete. A sink that cannot be
    asked to remove a record by any method on its own interface is a structural guarantee
    rather than a policy (deep-dive §3.2).
    """

    @property
    def name(self) -> str:
        """Stable identifier, used in `RecordResult.degraded_sinks`."""

    @property
    def is_primary(self) -> bool:
        """True for the one sink whose failure is an error rather than a degradation."""

    def append(self, event: AuditEvent) -> None:
        """Append one event. Raises on failure; the registry turns that into result data."""

    def close(self) -> None: ...


__all__ = [
    "ActionType",
    "AuditEvent",
    "AuditMetrics",
    "AuditQueryFilter",
    "AuditQueryResult",
    "AuditSink",
    "AuditorRole",
    "DEFAULT_RETENTION_DAYS",
    "PRIVILEGED_ACTIONS",
    "PurgeResult",
    "READER_ROLES",
    "REASON_REQUIRED_ACTIONS",
    "RETENTION_SETTING_SPEC",
    "RecordResult",
    "RetentionMode",
    "RetentionPolicy",
    "RetentionResolution",
]
