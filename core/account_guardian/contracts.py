"""Account Guardian data contracts (`v3-deepdive-06-account-guardian-api.md` §3, §6, §7).

This is the only module in this package other APIs import from (`docs/PRINCIPLES.md` §1.1).
It holds types and no logic beyond trivially-derived predicates on a value's own fields.

**This package deliberately reuses Auth & Tenancy's own vocabulary rather than defining a
second copy of it.** `Role` and `AuthMethod` are imported from `core.auth.contracts` and
re-exported here, not redeclared — the deep-dive is explicit that this API "consumes Auth's
`SessionStore` and `User` primitives" rather than duplicating them (§1), and a second
`Role` enum living here would be exactly the kind of drifting parallel taxonomy
`docs/PRINCIPLES.md` §3.4 exists to prevent, even though Role/AuthMethod are not themselves
Architect-owned schema data.

Every type below is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(`docs/PRINCIPLES.md` §2.1) — these are result contracts that cross a gRPC boundary, or are
read back out of `store.py` into one, and a frozen dataclass holding a plain `dict` is only
shallowly immutable.

**Errors are data here, with one carve-out that is not this package's own.** Every result
type below carries `error`/`error_detail`, per `docs/PRINCIPLES.md` §4.1's ordinary
convention. The one exception belongs to Auth, not to Account Guardian: when this API asks
Auth to resolve a session and Auth cannot, that failure is raised using Auth's own
`core.auth.errors` exception types, imported and re-raised as-is rather than reinvented as a
third convention (see `gateways.py`). Nothing in *this* module represents that raised case,
because a raised exception is not a value — there is no `SessionResult` type here for the
same reason `core/auth/contracts.py` has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict
from core.auth.contracts import AuthMethod, Role
from core.persistence.contracts import BlobRef

__all__ = [
    "AccountGuardianMetrics",
    "AuthMethod",
    "BlobRef",
    "CANCELLABLE_DELETION_STAGES",
    "CallerSession",
    "ConsentCheckResult",
    "ConsentDocumentType",
    "ConsentRecord",
    "DataExportRequest",
    "DeletionRequest",
    "DeletionResult",
    "DeletionStage",
    "DeviceListResult",
    "DeviceSession",
    "EraseOutcome",
    "ExportOutcome",
    "ExportRequestResult",
    "ExportStatus",
    "KNOWN_SSO_PROVIDERS",
    "PolicyVersion",
    "RecoveryRequest",
    "RecoveryResult",
    "RecoveryStage",
    "RecoveryVerificationChecklist",
    "Role",
    "RevokeResult",
    "SsoLinkRequest",
    "SsoLinkResult",
    "SsoLinkStage",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------- sessions/devices


@dataclass(frozen=True)
class CallerSession:
    """The subset of Auth's own `Session` that actually crosses `ValidateSession`'s wire
    response.

    Deliberately not `core.auth.contracts.Session` itself: that type requires
    `created_at`/`last_seen_at`, and `ValidateSession`'s response never carries them — the
    Auth deep-dive (§9) keeps that response minimal on purpose, since it is the
    highest-volume call in the entire system. Fabricating placeholder timestamps to satisfy
    `Session`'s constructor would be worse than a narrower type that only claims what the
    wire actually gives us.
    """

    session_id: str
    user_id: str
    role: Role


@dataclass(frozen=True)
class DeviceSession:
    """One row of a user's own device/session list (deep-dive §3, §4).

    `user_agent_summary` is parsed and human-readable ("Chrome on Windows") — never the raw
    User-Agent string, which can leak more granular fingerprinting detail than a user needs
    to recognise "is this my phone or something I don't recognise" (deep-dive §4).
    """

    session_id: str
    created_at: datetime
    last_seen_at: datetime
    user_agent_summary: str
    is_current: bool


@dataclass(frozen=True)
class DeviceListResult:
    """Errors are data (`docs/PRINCIPLES.md` §4.1). `error` is populated, never raised,
    when the underlying capability degrades — including the real gap `gateways.py`
    documents: Auth's `AuthService` has no session-listing RPC yet."""

    devices: tuple[DeviceSession, ...] = ()
    error: str | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class RevokeResult:
    """Revocation is a privileged action (deep-dive: device management is a real security
    surface) — `audit_recorded`/`audit_error` carry whether Audit actually accepted the
    entry, distinct from `error`/`error_detail`, which describe the revocation itself. A
    revoke can succeed while its audit write degrades, and the two must stay tellable apart
    the same way `core.audit.contracts.RecordResult.degraded_sinks` keeps a degraded mirror
    distinct from a failed primary write (`docs/PRINCIPLES.md` §4.2, §4.4)."""

    revoked: bool = False
    sessions_revoked: int = 0
    error: str | None = None
    error_detail: str = ""
    audit_recorded: bool = True
    audit_error: str = ""


# --------------------------------------------------------------------- account recovery


class RecoveryStage(str, Enum):
    """A staff-mediated case queue, not a self-service flow (deep-dive §5). There is
    deliberately no automated `APPROVED` transition anywhere in this package — every
    approval is a staff decision recorded with `reviewed_by` set."""

    REQUESTED = "requested"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RecoveryVerificationChecklist:
    """The three-check structure the deep-dive's own open questions section resolves with
    (§12), not a single pass/fail test. Every field is independently optional because not
    every check is available for every case — a solo consumer account has no colleague to
    vouch for it, and not every user set an optional recovery contact.

    **No single field is sufficient alone** (deep-dive §12: "staff judgment combines what's
    actually available"). `account_recovery.py`'s `approve()` enforces the one automatable
    floor this package can responsibly assert: at least one check must be affirmatively
    satisfied before a request can move to `APPROVED`. Which combination is *enough* for a
    given case stays a human judgment call, deliberately not encoded as an algorithm here.
    """

    knowledge_check_passed: bool = False
    knowledge_check_note: str = ""
    #: `None` means "no recovery contact was ever on file for this account", distinct from
    #: `False` ("one was on file and did not verify").
    recovery_contact_verified: bool | None = None
    #: A second already-verified staff/owner user_id at the same multi-tenant install,
    #: vouching for this case — real signal a solo consumer account cannot produce.
    vouched_by_user_id: str | None = None

    @property
    def any_check_satisfied(self) -> bool:
        return bool(
            self.knowledge_check_passed
            or self.recovery_contact_verified
            or self.vouched_by_user_id
        )


@dataclass(frozen=True)
class RecoveryRequest:
    request_id: str
    user_id: str
    requested_at: datetime
    stage: RecoveryStage
    #: Which of Auth's four methods the user reports having lost. `None` when the request
    #: does not name one (a user who lost every method they had configured at once).
    lost_method: AuthMethod | None = None
    checklist: RecoveryVerificationChecklist = field(
        default_factory=RecoveryVerificationChecklist
    )
    reviewed_by: str | None = None
    resolved_at: datetime | None = None
    notes: str = ""


@dataclass(frozen=True)
class RecoveryResult:
    request: RecoveryRequest | None = None
    error: str | None = None
    error_detail: str = ""
    #: See `RevokeResult`'s own docstring — the same "the action and its audit write are
    #: two separately-tellable outcomes" reasoning applies to every privileged action here.
    audit_recorded: bool = True
    audit_error: str = ""


# --------------------------------------------------------------------- SSO provider change


class SsoLinkStage(str, Enum):
    """`sso_linking.py`'s own sketch in the deep-dive is marked "future" (§2) — this is the
    request-intake half of that future feature, real today; the actual identity mutation on
    Auth's own `users` row is gated on an Auth RPC that does not exist yet (`gateways.py`).
    """

    REQUESTED = "requested"
    STEP_UP_PENDING = "step_up_pending"
    PENDING_AUTH_MUTATION = "pending_auth_mutation"
    COMPLETED = "completed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SsoLinkRequest:
    request_id: str
    user_id: str
    provider: str
    requested_at: datetime
    stage: SsoLinkStage
    completed_at: datetime | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class SsoLinkResult:
    request: SsoLinkRequest | None = None
    error: str | None = None
    error_detail: str = ""
    audit_recorded: bool = True
    audit_error: str = ""


# --------------------------------------------------------------------- data export


class ExportStatus(str, Enum):
    """Values match the deep-dive's own `Literal` exactly (§3) — kept as an `Enum` for the
    same reason every other closed vocabulary in this codebase is one rather than a bare
    string: a typo in a status string is a `ValueError` at construction, not a silent typo
    that compares unequal forever."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class DataExportRequest:
    request_id: str
    user_id: str
    requested_at: datetime
    status: ExportStatus
    export_blob_ref: BlobRef | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class ExportRequestResult:
    request: DataExportRequest | None = None
    error: str | None = None
    error_detail: str = ""
    audit_recorded: bool = True
    audit_error: str = ""


@dataclass(frozen=True)
class ExportOutcome:
    """What `gateways.PersistenceGateway.generate_export` hands back — the Persistence-side
    half of a `DataExportRequest`, before it is folded into this package's own record."""

    ok: bool
    export_blob_ref: BlobRef | None = None
    export_id: str = ""
    generated_at: datetime | None = None
    error: str | None = None
    error_detail: str = ""


# --------------------------------------------------------------------- deletion


class DeletionStage(str, Enum):
    """Verbatim from the deep-dive (§3, §6.3). `BILLING_HOLD` is the resolved answer to
    file 01's own flagged "can't delete mid-subscription" question — the grace period *is*
    the window that resolution happens in, never a silent skip of Billing's own state."""

    REQUESTED = "requested"
    GRACE_PERIOD = "grace_period"
    BILLING_HOLD = "billing_hold"
    PROCESSING = "processing"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


#: Stages from which a user may still cancel (deep-dive §6.3: "only valid while stage is
#: REQUESTED, GRACE_PERIOD, or BILLING_HOLD"). A module-level lookup table nothing should
#: ever write is exactly what `docs/PRINCIPLES.md` §2.1.1 asks to be immutable, even though
#: it holds no values worth looking up by key — a `frozenset` carries the same immutability
#: property here without pretending this is a mapping.
CANCELLABLE_DELETION_STAGES: frozenset[DeletionStage] = frozenset(
    {DeletionStage.REQUESTED, DeletionStage.GRACE_PERIOD, DeletionStage.BILLING_HOLD}
)


@dataclass(frozen=True)
class DeletionRequest:
    request_id: str
    user_id: str
    requested_at: datetime
    stage: DeletionStage
    grace_period_ends_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def cancellable(self) -> bool:
        return self.stage in CANCELLABLE_DELETION_STAGES


@dataclass(frozen=True)
class DeletionResult:
    request: DeletionRequest | None = None
    error: str | None = None
    error_detail: str = ""
    audit_recorded: bool = True
    audit_error: str = ""


@dataclass(frozen=True)
class EraseOutcome:
    """What `gateways.PersistenceGateway.erase_account` hands back once `PROCESSING`
    actually starts (deep-dive §6.3: "routes through Persistence's normal write path... a
    real Historian-logged event")."""

    ok: bool
    erased_at: datetime | None = None
    error: str | None = None
    error_detail: str = ""


# --------------------------------------------------------------------- consent (§7)


class ConsentDocumentType(str, Enum):
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"


@dataclass(frozen=True)
class ConsentRecord:
    """A user's acceptance of one *specific* document version (deep-dive §7.2) — publishing
    a new version never retroactively counts as every existing user having accepted it."""

    user_id: str
    document_type: ConsentDocumentType
    document_version: str
    accepted_at: datetime
    #: Evidentiary value for the hosted service specifically; `None` for self-hosted
    #: single-tenant installs where it adds no real value (deep-dive §7.2).
    ip_address: str | None = None


@dataclass(frozen=True)
class PolicyVersion:
    """One published revision of a Terms-of-Service or Privacy-Policy document.

    `text_ref` is a pointer into the owner-configurable top-level config directory
    (`docs/PRINCIPLES.md` §1.6), never the document text itself — a self-hosted operator's
    own legal text is genuinely different content from DOMTRI's own hosted default, and this
    package draws no opinion about what either one says (deep-dive §7.1).
    """

    document_type: ConsentDocumentType
    version: str
    published_at: datetime
    text_ref: str
    #: An owner judgment call, not an algorithm (deep-dive §7.3): whether this revision is
    #: substantive enough that every existing user must explicitly re-accept it.
    requires_reconsent: bool = False


@dataclass(frozen=True)
class ConsentCheckResult:
    """§7.4's enforcement query: does this user have a valid `ConsentRecord` for whichever
    version of `document_type` is current right now."""

    has_valid_consent: bool
    current_version: PolicyVersion | None = None
    error: str | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class AccountGuardianMetrics:
    """What Health and Telemetrees can ask this API about itself (`metrics.py`).

    Every field is a genuinely mutable counter behind `metrics.AccountGuardianMetricsCollector`
    — this frozen type is only the immutable snapshot handed out, the same split
    `core/health/metrics.py` and `core/audit/metrics.py` both use: a caller can never be
    holding a view that mutates under it mid-read.
    """

    devices_listed: int = 0
    devices_revoked: int = 0
    all_devices_revoked_calls: int = 0
    recovery_requests_created: int = 0
    recovery_approved: int = 0
    recovery_rejected: int = 0
    recovery_completed: int = 0
    recovery_cancelled: int = 0
    sso_link_requests: int = 0
    export_requests: int = 0
    deletion_requests: int = 0
    deletion_cancelled: int = 0
    deletion_completed: int = 0
    consent_recorded: int = 0
    audit_write_failures: int = 0


#: The SSO providers this package knows how to validate a link request against — a small,
#: explicit Provider Registry (`docs/PRINCIPLES.md` §1.2, §1.3) rather than a hardcoded
#: `if provider == "google"` scattered through `sso_linking.py`. Mirrors Auth's own
#: `auth.oidc.providers_enabled` config list (deep-dive-05 §10); the two are not the same
#: list by accident — this one must be extended in the same change that adds a provider to
#: Auth's, since linking a provider Auth cannot itself authenticate against is meaningless.
#: `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1 — a module-level constant nothing should
#: ever mutate.
KNOWN_SSO_PROVIDERS: FrozenDict = FrozenDict({"google": "Google"})
