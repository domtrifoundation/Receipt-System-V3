"""Review/Flagging API data contracts (`v3-deepdive-25-review-flagging-api.md` §4, §6).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in
this package that anything outside `core/review_flagging/` imports from.

**`Flag.flag_type` is a plain `str`, never a local enum.** The taxonomy of what a flag
*is* — `vat_math_mismatch`, `tin_format_malformed`, the rest of the real inventory — is
Architect API's registry (`core/architect/contracts.py`'s `DefinitionKind.FLAG_TYPE`,
re-exported below as `ARCHITECT_FLAG_TYPE_KIND` so a caller wiring a real validator names
the right kind rather than guessing at a string). Declaring a second, local enum here would
be exactly the shadow taxonomy `docs/PRINCIPLES.md` §3.4 exists to prevent — this package
manages a flag's *lifecycle*, it does not define what flags exist. This mirrors
`core/notifications/contracts.py`'s own `Notification.category` verbatim: kept an
unvalidated string, with `FlagTypeValidator` below as the adapter seam a real Architect
registry client plugs into, never a shortcut that invents a parallel vocabulary.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(`docs/PRINCIPLES.md` §2.1) — a frozen dataclass holding a plain `dict` is only shallowly
immutable, and `Flag.payload` is handed across a process boundary and read concurrently by
the staff queue and the audit screen at once. Any `isinstance` check against it must test
`collections.abc.Mapping`, never `dict`: the Python 3.15 builtin `frozendict` is not a
`dict` subclass.

Errors are data here, never raised across the boundary (§4.1): every result type below
carries `error_code`/`error_detail` and an `ok` property.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from common.frozen_dict import FrozenDict
from core.architect.contracts import DefinitionKind

#: The kind a real Architect-registry-backed `FlagTypeValidator` should query against.
#: Re-exported here rather than left for a caller to look up so this package's own seam
#: names the correct kind directly instead of a hand-typed string that could drift from
#: Architect's own enum member.
ARCHITECT_FLAG_TYPE_KIND: DefinitionKind = DefinitionKind.FLAG_TYPE


def utcnow() -> datetime:
    """Timezone-aware UTC now, matching every other API's own `utcnow` (`core/audit`,
    `core/logs`, `core/notifications`) — a naive value compared against an aware one raises
    out of a boundary that returns errors as data, never exceptions (`docs/PRINCIPLES.md`
    §4.1)."""
    return datetime.now(timezone.utc)


class FlagStatus(str, Enum):
    """The flag lifecycle's own states (§4).

    `DISMISSED` is deliberately distinct from `RESOLVED` — a false positive versus an actual
    fix applied — and the deep-dive's own §7 testing hook exists specifically because that
    distinction is easy to blur in a staff-facing queue or metrics view that only asks
    "is this flag still open." `metrics.py` keeps two separate counters for exactly this
    reason; collapsing them anywhere downstream is the bug this contract exists to prevent.

    Values are stable wire strings. Adding a member is fine; renaming or reusing one is a
    breaking change to `review_flagging.proto`, the same discipline every other API's own
    status enum in this repo follows.
    """

    OPEN = "open"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


#: The flag lifecycle's own state machine (§4). A module-level constant lookup table, so
#: `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — this is read from every transition check in
#: `lifecycle.py`, concurrently, and nothing should ever write to it.
#:
#: `OPEN` reaches `RESOLVED`/`DISMISSED` directly as well as through `ASSIGNED`: the open
#: question this deep-dive resolves (§8, "a shared open queue, self-assign — the same shape
#: as Support Ticketing's own identical question") means a staff member working an
#: unassigned flag straight through to resolution self-assigns it to themselves as part of
#: that same call rather than requiring a separate `AssignFlag` round trip first — see
#: `lifecycle.py`'s own docstring on `resolve`/`dismiss` for exactly how that is recorded.
#: `RESOLVED` and `DISMISSED` are terminal: neither has an outgoing edge, so any further
#: transition attempt against either is rejected explicitly rather than silently no-op'd,
#: the same discipline `core/account_guardian/privacy/deletion_request.py`'s own
#: `_TERMINAL_STAGES` follows for its own lifecycle.
VALID_TRANSITIONS: FrozenDict = FrozenDict(
    {
        FlagStatus.OPEN: frozenset({FlagStatus.ASSIGNED, FlagStatus.RESOLVED, FlagStatus.DISMISSED}),
        FlagStatus.ASSIGNED: frozenset({FlagStatus.RESOLVED, FlagStatus.DISMISSED}),
        FlagStatus.RESOLVED: frozenset(),
        FlagStatus.DISMISSED: frozenset(),
    }
)

#: Read access to the staff queue, and the right to assign/resolve/dismiss, is staff/owner
#: only — never client role (`docs/PRINCIPLES.md` §4.2). A client learning the internal
#: review state of their own flagged receipt is a different, narrower concern this API does
#: not serve; the staff queue itself is privileged infrastructure the same way Audit's own
#: read access is (`core/audit/contracts.py::READER_ROLES`).
FlagRole = Literal["client", "staff", "owner"]
RESOLVER_ROLES: frozenset[str] = frozenset({"staff", "owner"})

#: §8's own resolved severity split for the flag-to-notification mapping: malicious/unsafe
#: content and ATP-validity/BIR-compliance flags get an immediate Notifications alert; every
#: other flag type appears in the staff queue on its own normal cadence. A plain `frozenset`
#: rather than `FrozenDict`, matching `core/audit/contracts.py::REASON_REQUIRED_ACTIONS` —
#: a `frozenset` is already immutable by construction, so the `FrozenDict` shim buys nothing
#: for a membership-only table.
HIGH_STAKES_FLAG_TYPES: frozenset[str] = frozenset(
    {"content_security_unsafe", "atp_validity", "bir_completeness"}
)


@dataclass(frozen=True)
class Flag:
    """One flag instance, from creation through terminal resolution (§4).

    `flag_type` is never validated against a local vocabulary (see this module's own
    docstring) — only against Architect's registry, through the `FlagTypeValidator` seam,
    and even that check degrades permissive rather than rejecting (`docs/PRINCIPLES.md`
    §4.4): an unrecognised flag type is a labeling gap, not a reason to lose a real signal a
    producer API raised in good faith.

    `payload` carries whatever context the raising API attached (a computed VAT delta, the
    two conflicting values Reimport's three-way diff found) — opaque to this package, which
    only manages the flag's lifecycle, never its domain meaning.
    """

    flag_id: str
    flag_type: str
    user_id: str
    receipt_id: str
    status: FlagStatus
    created_by: str
    created_at: datetime
    assigned_to: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str = ""
    payload: FrozenDict = field(default_factory=lambda: FrozenDict({}))

    @property
    def is_dismissal(self) -> bool:
        """True only for a confirmed false positive — never true for an actual fix (§4)."""
        return self.status is FlagStatus.DISMISSED

    @property
    def is_resolution(self) -> bool:
        """True only when an actual fix was applied — never true for a dismissal (§4)."""
        return self.status is FlagStatus.RESOLVED

    @property
    def is_terminal(self) -> bool:
        return self.status in (FlagStatus.RESOLVED, FlagStatus.DISMISSED)

    @property
    def is_high_stakes(self) -> bool:
        """§8's resolved severity split — whether this flag type earns an immediate
        Notifications alert rather than appearing in the queue on its own cadence."""
        return self.flag_type in HIGH_STAKES_FLAG_TYPES


# --------------------------------------------------------------------- requests


@dataclass(frozen=True)
class CreateFlagRequest:
    """What a producer API asks for (Reconciliation, Content Security, Reimport — §1's own
    list of callers). System-to-system, never session-gated: the caller names its own
    `created_by`, the same posture `core/notifications/contracts.py::NotifyRequest` takes
    for its own system-to-system `Notify` call."""

    flag_type: str
    user_id: str
    receipt_id: str
    created_by: str
    payload: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class AssignFlagRequest:
    """Self-assign (`assignee_user_id` equal to the resolved caller) or an owner's
    reassignment (§8's own resolved routing policy) — `lifecycle.py` is what tells the two
    apart and gates the latter to the `owner` role specifically."""

    flag_id: str
    assignee_user_id: str


@dataclass(frozen=True)
class ResolveFlagRequest:
    """`edit_field`/`edit_new_value` are how a resolution "involves a data change" (§4):
    when set, `lifecycle.resolve` routes the write through `edit_entry_point.apply_edit`
    before the flag is marked `RESOLVED`, and a write that fails leaves the flag exactly
    where it was — never a special-cased bypass. Left unset, resolution is recorded as a
    pure status transition, for a fix already applied through some other path."""

    flag_id: str
    resolution_note: str = ""
    edit_field: str | None = None
    edit_new_value: str | None = None


@dataclass(frozen=True)
class DismissFlagRequest:
    """A pure status transition (§4) — dismissal never carries an edit, because a false
    positive is, by definition, nothing to fix."""

    flag_id: str
    reason: str = ""


@dataclass(frozen=True)
class ListFlagsQuery:
    """The staff queue's own read filter. An empty `statuses` reads every status; a caller
    wanting "the open queue" passes `(FlagStatus.OPEN, FlagStatus.ASSIGNED)` explicitly
    rather than this module guessing at a default that could silently exclude a state."""

    statuses: tuple[FlagStatus, ...] = ()
    flag_type: str | None = None
    receipt_id: str | None = None
    assigned_to: str | None = None
    limit: int = 100
    offset: int = 0


# --------------------------------------------------------------------- results
# Errors are data at this API's boundary, never exceptions raised across it
# (`docs/PRINCIPLES.md` §4.1). Every result below carries `error_code`/`error_detail` and an
# `ok` property so a caller checks one field rather than wrapping the call in try/except.


@dataclass(frozen=True)
class FlagResult:
    flag: Flag | None = None
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class ListFlagsResult:
    flags: tuple[Flag, ...] = ()
    total_matching: int = 0
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class AuditTraceEntry:
    """One row of Logs' own operational trace, projected for the per-receipt audit screen
    (§3) — how a receipt was scanned, what each OCR engine read, what Inference concluded
    and why it flagged something. This package never stores this itself; it is a read-time
    projection of Logs' own data, never a second copy of it."""

    timestamp: datetime
    service: str
    level: str
    message: str
    detail: str = ""


@dataclass(frozen=True)
class AuditView:
    """§3's per-receipt audit screen: Logs' own trace, plus every flag this package has
    ever raised for the receipt, in one readable view. `trace_available=False` means the
    Logs seam degraded (§4.4, not a security check) — the flags half of the view is still
    real and still shown; a client renders that distinction rather than being handed an
    empty screen with no explanation."""

    receipt_id: str
    trace: tuple[AuditTraceEntry, ...] = ()
    flags: tuple[Flag, ...] = ()
    trace_available: bool = True
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class EditLink:
    """§3's deep-link target: which field on which receipt a flag or a Notifications
    quick-action button should open an edit form against. `field=None` means this flag type
    has no single obvious field to deep-link to — a client falls back to opening the receipt
    generally rather than guessing at one."""

    flag_id: str
    receipt_id: str
    field: str | None
    suggested_value: str | None = None
    label: str = ""


@dataclass(frozen=True)
class EditWriteResult:
    """What actually applying an edit through Persistence's normal write path produced.
    `historian_event_id` is the proof the write went through the real path (Historian-
    logged) rather than a shortcut that bypassed it — the deep-dive's own §7 testing hook."""

    ok: bool
    historian_event_id: str = ""
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class FlagMetrics:
    """This API's own counters, snapshotted (`metrics.py`). Field names are the counter
    names — `metrics.py` derives them from this contract so the two cannot drift apart."""

    flags_created: int = 0
    flags_create_rejected: int = 0
    flags_assigned: int = 0
    flags_reassigned: int = 0
    flags_resolved: int = 0
    flags_dismissed: int = 0
    invalid_transitions_rejected: int = 0
    resolutions_denied_role: int = 0
    resolutions_denied_ownership: int = 0
    audit_records_written: int = 0
    audit_records_degraded: int = 0
    notifications_sent: int = 0
    notifications_skipped_routine: int = 0
    notifications_failed: int = 0
    edit_writes_applied: int = 0
    edit_writes_unavailable: int = 0
    audit_views_built: int = 0
    audit_trace_unavailable: int = 0
    flag_type_unrecognized: int = 0


# ------------------------------------------------------------------- providers
# Protocol seams for every pluggable/cross-API capability (`docs/PRINCIPLES.md` §1.2, §1.3).
# Concrete defaults and adapters live in the modules that consume them (`lifecycle.py`,
# `audit_screen.py`, `edit_entry_point.py`, `gateways.py`) — the same split
# `core/notifications/contracts.py` uses for its own `CategoryValidator`/`SessionResolver`.


@runtime_checkable
class FlagTypeValidator(Protocol):
    """The Architect-registry seam for `Flag.flag_type` (see this module's own docstring on
    why `flag_type` is a plain string rather than a local enum). Returns whether this build
    recognises the code — never raises, since this is not a security check and a validator
    that cannot answer degrades to permissive (§4.4)."""

    def is_known(self, flag_type: str) -> bool: ...


@dataclass(frozen=True)
class AuditRecordOutcome:
    """What recording a privileged action with Audit actually produced — deliberately
    separate from the flag-resolution outcome itself (`gateways.AuditRecorder`), the same
    split `core/account_guardian/gateways.py::AuditOutcome` keeps for its own privileged
    actions: a resolution can succeed while its audit write degrades, and the two must stay
    tellable apart."""

    recorded: bool
    event_id: str = ""
    error_code: str = ""
    error_detail: str = ""


@runtime_checkable
class AuditRecorder(Protocol):
    """The seam onto Audit/Event Log API. Every staff resolution of a flag — including a
    refused attempt — is a privileged action and must produce an entry here."""

    async def record(
        self,
        operation: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> AuditRecordOutcome: ...


@runtime_checkable
class FlagNotifier(Protocol):
    """The seam onto Notifications/Inbox API for new-flag creation (§5, §8) — a real,
    bidirectional connection `notifications.proto` itself names as a caller of `Notify`.
    Returns whether the in-app notification was actually recorded; never raises, since a
    failed notification must never fail the flag creation it describes (§4.4)."""

    async def notify_new_flag(self, flag: Flag) -> bool: ...


@runtime_checkable
class PersistenceWriteGateway(Protocol):
    """The seam onto Persistence's normal write path (§3, §4) — the one mechanism every
    edit in this system converges on, regardless of which screen initiated it. Never raises;
    a write that cannot be performed is `EditWriteResult(ok=False, ...)`, so a resolution
    that depended on it can decline to proceed rather than guessing at success."""

    async def apply_edit(
        self, user_id: str, receipt_id: str, field: str, new_value: str, actor_user_id: str
    ) -> EditWriteResult: ...


@runtime_checkable
class AuditTraceSource(Protocol):
    """The seam onto Logs API for §3's per-receipt audit screen. Never raises; an
    unreachable Logs process degrades to an empty trace with `trace_available=False`
    (§4.4) rather than failing the whole screen — the flags half of `AuditView` is this
    package's own data and stays real regardless."""

    async def fetch(self, receipt_id: str) -> tuple[AuditTraceEntry, ...]: ...


@runtime_checkable
class SessionRoleResolver(Protocol):
    """The seam onto Auth & Tenancy for resolving *who is actually calling* and *what role
    they hold* from a session id — never from a value the caller asserts about itself
    (`docs/PRINCIPLES.md` §4.2). Returns `None` for any session this cannot vouch for,
    treated as denial everywhere it is called, never as permission."""

    async def resolve(self, session_id: str) -> tuple[str, str] | None: ...


__all__ = [
    "ARCHITECT_FLAG_TYPE_KIND",
    "HIGH_STAKES_FLAG_TYPES",
    "RESOLVER_ROLES",
    "VALID_TRANSITIONS",
    "AssignFlagRequest",
    "AuditRecordOutcome",
    "AuditRecorder",
    "AuditTraceEntry",
    "AuditTraceSource",
    "AuditView",
    "CreateFlagRequest",
    "DismissFlagRequest",
    "EditLink",
    "EditWriteResult",
    "Flag",
    "FlagMetrics",
    "FlagNotifier",
    "FlagResult",
    "FlagRole",
    "FlagStatus",
    "FlagTypeValidator",
    "ListFlagsQuery",
    "ListFlagsResult",
    "PersistenceWriteGateway",
    "ResolveFlagRequest",
    "SessionRoleResolver",
    "utcnow",
]
