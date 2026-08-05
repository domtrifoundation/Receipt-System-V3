"""Setup API's data contracts — types only, no logic (`docs/PRINCIPLES.md` §1.1).

Four surfaces live here, added as the packages that needed them were built:

1. **Per-service venv provisioning** (`docs/VENV_AND_IMPORTS.md`) — the mechanism behind the
   "dependency installation" this API's own §1 has always claimed to own but never described.
2. **Hardware detection** (deep-dive §3, §5) — `HardwareProfile`/`GpuInfo`, the static profile
   OCR/Preprocessing/Inference all consume rather than re-probing hardware themselves (§6).
3. **The first-run wizard** (deep-dive §7, word-for-word copy in `docs/SETUP_WIZARD_SCRIPT.md`)
   — `WizardState` plus the step machine's own types.
4. **Errors as data everywhere** (`docs/PRINCIPLES.md` §4.1). A clone with one unprovisionable
   service, one undetectable GPU, or one declined wizard step has to report *which* and *why*
   and keep going — an operator or a caller needs the whole picture, not the first failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from common.frozen_dict import FrozenDict

from .errors import StripError

__all__ = [
    "DEFAULT_STEP_SEQUENCE",
    "STEP_DEFINITIONS",
    "AccountEnrollment",
    "AccountEnrollmentGateway",
    "AddressCheckingChoice",
    "AddressCheckingGateway",
    "BillingProrationChoice",
    "BillingSetupGateway",
    "BillingSetupResult",
    "BootstrapReport",
    "DevFixturesReport",
    "GpuInfo",
    "GroupsChoice",
    "GroupsSetupGateway",
    "HardwareDetector",
    "HardwareProfile",
    "HardwareReportImporter",
    "HardwareScorer",
    "IngestionChannelGateway",
    "IngestionChannelsResult",
    "LoginMethod",
    "ProvisionError",
    "ProvisionErrorCode",
    "ProvisionOutcome",
    "ProvisionReport",
    "ReceiptIngestionChoice",
    "RecommendedTier",
    "ServiceVenvSpec",
    "SetupMetrics",
    "SmsProviderChoice",
    "SmsSetupGateway",
    "SmsSetupResult",
    "StartupRegistrar",
    "StripReport",
    "TenancyChoice",
    "TermsAcceptance",
    "TierProfile",
    "TunnelSetupGateway",
    "TunnelSetupResult",
    "UseCase",
    "WebappBuilder",
    "WizardAnswer",
    "WizardState",
    "WizardStepDefinition",
    "WizardStepId",
    "WizardStepPrompt",
]


class ProvisionErrorCode(str, Enum):
    """Why one service's venv could not be provisioned.

    Distinct codes rather than one generic failure, because the operator action differs
    completely: a missing/unusable interpreter is an environment problem, a dependency
    resolution failure is usually platform wheel availability, and a missing source directory
    means the clone itself is malformed and should not be cut over to at all.
    """

    VENV_CREATION_FAILED = "venv_creation_failed"
    DEPENDENCY_INSTALL_FAILED = "dependency_install_failed"
    SOURCE_DIR_MISSING = "source_dir_missing"
    INTERPRETER_UNUSABLE = "interpreter_unusable"


@dataclass(frozen=True)
class ProvisionError:
    code: ProvisionErrorCode

    detail: str
    """The real failure text — pip's or venv's own stderr, not a summarised paraphrase.

    `v3-plan-04-v2-audit-findings.md` records V2 discarding tracebacks in favour of `str(e)` as
    a concrete cause of hard debugging; the same lesson applies to a subprocess's stderr. A
    bare "install failed" tells an operator nothing they can act on.
    """


@dataclass(frozen=True)
class ServiceVenvSpec:
    """One service's venv, fully resolved against one specific clone.

    Produced by discovery rather than a hardcoded service list, so a newly added Core API is
    picked up the day it lands. The corpus's single most-repeated structural mistake is a new
    API never being wired into the cross-cutting machinery that enumerates all of them
    (`v3-plan-03-decisions.md`'s own root-cause note on that pattern) — a hardcoded list here
    would be one more place to forget.
    """

    import_path: str
    """Dotted path, e.g. `core.ocr` — and also the venv directory's own name.

    Deliberately not the bare leaf name: `core/` and `services/` are separate trees that can
    hold the same leaf (`execution_core` is in both today), so a bare name is genuinely
    ambiguous (`docs/VENV_AND_IMPORTS.md` §2).
    """

    source_dir: Path
    venv_dir: Path

    requirement_files: tuple[Path, ...]
    """Ordered: the shared base first, then this service's own if it has one.

    Ordered and a tuple rather than a set because this is an install *sequence* — pip resolves
    later requirements against what earlier ones already pinned.
    """


@dataclass(frozen=True)
class ProvisionOutcome:
    import_path: str
    venv_dir: Path

    created: bool
    """False when the venv already existed and was left alone.

    Provisioning is idempotent and safely re-runnable — the same property Setup's own bootstrap
    has, and for the same reason (`v3-deepdive-11-setup-api.md` §4): re-running after a partial
    failure must be a normal, safe operation, not a reason to start over.
    """

    error: ProvisionError | None = None


@dataclass(frozen=True)
class ProvisionReport:
    outcomes: tuple[ProvisionOutcome, ...]

    @property
    def failed(self) -> tuple[ProvisionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.error is not None)

    @property
    def fully_provisioned(self) -> bool:
        """Whether this clone is eligible for cutover at all.

        A clone with any service unprovisioned must never be cut over to: a service whose venv
        is half-built is not a degraded service, it is an import error at launch. Supervisor
        keeps serving the prior release instead, which is its existing rollback path rather than
        a new mechanism (`docs/VENV_AND_IMPORTS.md` §5).
        """
        return not self.failed


@dataclass(frozen=True)
class StripReport:
    """`dev_mode_strip.strip_development_content()`'s own outcome. Defined here rather than in
    that module, matching `ProvisionReport`'s own placement — `docs/PRINCIPLES.md` §1.1's rule
    that `contracts.py` is the one file everything else imports from applies to a report shape
    as much as to a request/response shape."""

    removed: tuple[str, ...]
    """Entries actually removed, relative to the clone root, in a stable sorted order."""

    skipped_absent: tuple[str, ...]
    """Classified dev-only but not present in this clone.

    Not an error, and reported separately rather than silently folded into `removed`: a clone
    legitimately may not contain every dev-only entry (a shallow export, or a re-run after a
    previous strip). Conflating "removed it" with "it was never there" would make the report
    unable to answer whether a strip actually did anything.
    """

    errors: tuple[StripError, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


# =============================================================================================
# Hardware detection — the static profile (deep-dive §3, §5). Consumed by OCR/Preprocessing/
# Inference at their own startup rather than each re-probing hardware independently (§6).
# =============================================================================================


@dataclass(frozen=True)
class GpuInfo:
    name: str
    vendor: str
    """`"intel" | "nvidia" | "amd" | "unknown"`.

    A plain `str` rather than an `Enum`: this is real-world vendor-string classification, not a
    closed taxonomy this API defines — a genuinely new vendor string appearing is "unknown",
    never an unhandled-enum-member crash at detection time (`docs/PRINCIPLES.md` §4.2's
    fail-closed posture is for security checks; this is the ordinary-degradation counterpart —
    `unknown` is meaningful, actionable data, not a crash).
    """

    discrete: bool
    vram_gb: float | None
    """`None` when even the fallback chain (§5.2: registry → `AdapterRAM` → `None`) found
    nothing — never a guessed number."""

    compute_api: str
    """`"cuda" | "sycl" | "directml" | "rocm" | "unknown"` — see §5.2's classification note.
    Feeds every downstream hardware-acceleration decision across OCR/Preprocessing/Inference's
    own EP-selection lists."""

    shader_core_count: int | None = None
    """Beyond §3's own minimal sketch, added because §5.3 needs somewhere real to put what it
    merges: "parses out real hardware-read core counts to override the static per-SKU
    lookup/vendor-guess table for any matching adapter." WMI's own GPU core-count reporting is
    unreliable in a way VRAM's registry fallback does not fully compensate for (§5.3), so this
    stays `None` from the OS probe alone and is filled in only when a CPU-Z/HWiNFO report
    contributes one — `HardwareProfile.source` records whether that happened."""


@dataclass(frozen=True)
class HardwareProfile:
    cpu_name: str
    cores: int
    threads: int
    ram_gb: int | None
    gpus: tuple[GpuInfo, ...]
    npus: tuple[str, ...]
    detected_at: datetime
    source: str
    """`"os_probe" | "os_probe+external_report"` (§5.3) — whether a CPU-Z/HWiNFO report
    contributed, for transparency about how a profile was actually derived rather than silently
    blended in."""


@runtime_checkable
class HardwareDetector(Protocol):
    """Platform-dispatch probing (§5.1) — one implementation per OS, selected at registry-init
    time the same way every other Provider Registry entry in this project is
    (`docs/PRINCIPLES.md` §1.2), not branched inline wherever hardware is needed."""

    async def detect(self) -> HardwareProfile: ...


@runtime_checkable
class HardwareReportImporter(Protocol):
    """CPU-Z/HWiNFO external report fallback (§5.3) — a genuine accuracy improvement over the
    OS probe's own GPU shader/core-count reporting, not a redundant feature."""

    async def find_and_merge(
        self, profile: HardwareProfile, search_paths: tuple[Path, ...]
    ) -> HardwareProfile: ...


class TierProfile(str, Enum):
    """The three plain labels Step 9 of the wizard actually shows an owner
    (`docs/SETUP_WIZARD_SCRIPT.md` — "Lightweight" / "Balanced" / "Maximum accuracy"), not raw
    hardware-tier jargon."""

    LIGHTWEIGHT = "lightweight"
    BALANCED = "balanced"
    MAXIMUM_ACCURACY = "maximum_accuracy"


@dataclass(frozen=True)
class RecommendedTier:
    tier: TierProfile

    reasoned: bool
    """Whether `tier` came from real bench-calibrated coefficients or from the interim
    heuristic.

    **Deliberately not hidden.** Deep-dive §5.4 is explicit that `scoring.py`'s real
    coefficients should come from the bench suite's own measurements, "not invented here" —
    exactly the discipline this project applies to Tesseract's PSM default (OCR deep-dive §9:
    ship a defensible, stated default now; let real measurement override it once it exists).
    A caller that needs to know which situation it is in (the wizard copy, a future bench
    report) can, instead of the heuristic silently masquerading as calibrated.
    """


@runtime_checkable
class HardwareScorer(Protocol):
    """`recommended_settings()` (§5.4) as a seam, not a bare function — so the interim heuristic
    is swappable for real bench-calibrated coefficients without a call-site change anywhere
    that consumes it."""

    def recommend(self, profile: HardwareProfile) -> RecommendedTier: ...


# =============================================================================================
# The first-run wizard (§7). Word-for-word user-facing copy lives in
# `docs/SETUP_WIZARD_SCRIPT.md`; this module carries only the structured step data a client
# (TUI/webapp) renders that copy against — "TUI-driven via the same menu-data pattern as the
# rest of Interface API" (§7's own words), so no prose belongs in this package at all.
# =============================================================================================


class UseCase(str, Enum):
    """Step 0's three branches — the one choice that decides every step after it."""

    PERSONAL = "personal"
    TEAM = "team"
    PUBLIC = "public"


class LoginMethod(str, Enum):
    """Step 1's four choices. Deliberately the same four values as `core.auth`'s own
    `AuthMethod` enum, kept as an independent definition rather than an import — Setup must stay
    importable and testable without Auth installed (`docs/PRINCIPLES.md` §1.3), the same reason
    every collaborator below is a `Protocol`, never a concrete import."""

    SSO = "sso"
    PASSKEY = "passkey"
    EMAIL = "email"
    SMS = "sms"


class WizardStepId(str, Enum):
    """§7's step sequence, in the order `docs/SETUP_WIZARD_SCRIPT.md` presents them."""

    WELCOME = "welcome"
    ACCOUNT = "account"
    RUN_ON_STARTUP = "run_on_startup"
    TUNNEL_EXPOSURE = "tunnel_exposure"
    GROUPS = "groups"
    BILLING = "billing"
    SMS_NOTIFICATIONS = "sms_notifications"
    RECEIPT_INGESTION = "receipt_ingestion"
    ADDRESS_CHECKING = "address_checking"
    HARDWARE_TIER = "hardware_tier"
    TERMS_OF_SERVICE = "terms_of_service"
    FINALIZE = "finalize"


#: The wizard's own step order, as data — mirrors `services/execution_core/contracts.py`'s
#: `STAGE_SEQUENCE` precedent: the order is the contract, so it is written down exactly once,
#: as a tuple, rather than left implicit in whichever function happens to iterate it first.
DEFAULT_STEP_SEQUENCE: tuple[WizardStepId, ...] = (
    WizardStepId.WELCOME,
    WizardStepId.ACCOUNT,
    WizardStepId.RUN_ON_STARTUP,
    WizardStepId.TUNNEL_EXPOSURE,
    WizardStepId.GROUPS,
    WizardStepId.BILLING,
    WizardStepId.SMS_NOTIFICATIONS,
    WizardStepId.RECEIPT_INGESTION,
    WizardStepId.ADDRESS_CHECKING,
    WizardStepId.HARDWARE_TIER,
    WizardStepId.TERMS_OF_SERVICE,
    WizardStepId.FINALIZE,
)


@dataclass(frozen=True)
class WizardStepDefinition:
    """One step's identity plus its applicability rule, decoupled from any answer.

    `applies_to` is a plain `frozenset` rather than a callable predicate: every step's real
    applicability in `docs/SETUP_WIZARD_SCRIPT.md` is expressible as "these `UseCase`s see this
    step," with exactly one exception (Step 10's ToS *appears* for all three branches but its
    legal-review paragraph is `PUBLIC`-only) — handled as presentation detail in the prompt, not
    as a second applicability axis here, since the step itself still genuinely runs for all
    three.
    """

    step_id: WizardStepId
    applies_to: frozenset[UseCase]
    skippable: bool


@dataclass(frozen=True)
class WizardStepPrompt:
    """What a step hands the client to render — data, never copy. The actual words live in
    `docs/SETUP_WIZARD_SCRIPT.md`; a client renders that script keyed by `step_id`."""

    step_id: WizardStepId
    context: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    """Whatever the step needs the client to display alongside the script's own copy — e.g.
    `HARDWARE_TIER`'s `RecommendedTier`, serialized. `FrozenDict`, not `dict`
    (`docs/PRINCIPLES.md` §2.1)."""


#: Every step's applicability, as data, per `docs/SETUP_WIZARD_SCRIPT.md`'s own "Applies to"
#: line — a module-level lookup table, so `FrozenDict` per `docs/PRINCIPLES.md` §2.1.1, not a
#: plain `dict` a caller could mutate out from under every other caller.
#:
#: `skippable=False` on WELCOME/ACCOUNT/TERMS_OF_SERVICE is not "these are mandatory paperwork"
#: — it is that each is structurally load-bearing to the rest of the flow: there is no tenancy
#: to branch on before WELCOME answers it, no owner to attach every later choice to before
#: ACCOUNT creates one, and no install without accepting whatever ToS applies to the software
#: itself. FINALIZE stays genuinely `skippable=True` — it is a completion signal with nothing to
#: decide, so there is no meaningful concept of "declining" it and no reason to force a specific
#: `skipped` value on the answer that closes the flow out.
STEP_DEFINITIONS: FrozenDict = FrozenDict(
    {
        WizardStepId.WELCOME: WizardStepDefinition(
            WizardStepId.WELCOME, frozenset(UseCase), skippable=False
        ),
        WizardStepId.ACCOUNT: WizardStepDefinition(
            WizardStepId.ACCOUNT, frozenset(UseCase), skippable=False
        ),
        WizardStepId.RUN_ON_STARTUP: WizardStepDefinition(
            WizardStepId.RUN_ON_STARTUP, frozenset(UseCase), skippable=True
        ),
        WizardStepId.TUNNEL_EXPOSURE: WizardStepDefinition(
            WizardStepId.TUNNEL_EXPOSURE, frozenset({UseCase.TEAM, UseCase.PUBLIC}), skippable=True
        ),
        WizardStepId.GROUPS: WizardStepDefinition(
            WizardStepId.GROUPS, frozenset({UseCase.TEAM}), skippable=True
        ),
        WizardStepId.BILLING: WizardStepDefinition(
            WizardStepId.BILLING, frozenset({UseCase.TEAM, UseCase.PUBLIC}), skippable=True
        ),
        WizardStepId.SMS_NOTIFICATIONS: WizardStepDefinition(
            WizardStepId.SMS_NOTIFICATIONS, frozenset({UseCase.TEAM, UseCase.PUBLIC}), skippable=True
        ),
        WizardStepId.RECEIPT_INGESTION: WizardStepDefinition(
            WizardStepId.RECEIPT_INGESTION, frozenset(UseCase), skippable=True
        ),
        WizardStepId.ADDRESS_CHECKING: WizardStepDefinition(
            WizardStepId.ADDRESS_CHECKING, frozenset(UseCase), skippable=True
        ),
        WizardStepId.HARDWARE_TIER: WizardStepDefinition(
            WizardStepId.HARDWARE_TIER, frozenset(UseCase), skippable=True
        ),
        WizardStepId.TERMS_OF_SERVICE: WizardStepDefinition(
            WizardStepId.TERMS_OF_SERVICE, frozenset(UseCase), skippable=False
        ),
        WizardStepId.FINALIZE: WizardStepDefinition(
            WizardStepId.FINALIZE, frozenset(UseCase), skippable=True
        ),
    }
)


@dataclass(frozen=True)
class WizardAnswer:
    """The client's response to one `WizardStepPrompt`.

    `skipped=True` with `data` empty is a first-class, expected outcome for most steps in this
    wizard — `docs/SETUP_WIZARD_SCRIPT.md`'s own writing rule is "every optional step is
    visibly, unambiguously skippable, no dark patterns" applied at the data layer: skipping is
    never inferred from an empty payload, it is a real field a client sets deliberately.
    """

    step_id: WizardStepId
    skipped: bool
    data: FrozenDict = field(default_factory=lambda: FrozenDict({}))


class TenancyChoice(str, Enum):
    SINGLE = "single"
    MULTI = "multi"


class GroupsChoice(str, Enum):
    SHARED_SPACE = "shared_space"
    PRIVATE = "private"
    DECIDE_LATER = "decide_later"


class BillingProrationChoice(str, Enum):
    """Step 5's two independent proration axes (deep-dive §7.3,
    `v3-deepdive-22-billing-subscription-api.md` §3.3) — upgrade and downgrade are set
    separately, never coupled to one shared choice."""

    UPGRADE_IMMEDIATE_PRORATED = "upgrade_immediate_prorated"
    UPGRADE_NEXT_PERIOD = "upgrade_next_period"
    UPGRADE_FREE_UNTIL_PERIOD_AFTER_NEXT = "upgrade_free_until_period_after_next"
    DOWNGRADE_REFUND_IMMEDIATE = "downgrade_refund_immediate"
    DOWNGRADE_CREDIT_NEXT_BILL = "downgrade_credit_next_bill"
    DOWNGRADE_NO_REFUND = "downgrade_no_refund"


class SmsProviderChoice(str, Enum):
    SEMAPHORE = "semaphore"
    PHILSMS = "philsms"
    TWILIO = "twilio"


class AddressCheckingChoice(str, Enum):
    BUILT_IN = "built_in"
    SKIP = "skip"


class ReceiptIngestionChoice(str, Enum):
    UPLOAD_ONLY = "upload_only"
    """Always available, nothing to set up — the wizard's own stated default."""
    CAMERA = "camera"
    GOOGLE_DRIVE = "google_drive"


@dataclass(frozen=True)
class WizardState:
    tenancy_mode: str
    owner_created: bool
    initial_tier: str
    drive_restore_offered: bool
    completed_at: datetime | None


@dataclass(frozen=True)
class AccountEnrollment:
    method: LoginMethod
    identity_ref: str
    """An opaque reference into Auth's own store — Setup never holds a credential itself,
    consistent with Setup's own §1 boundary ("Setup's wizard is only where a license key gets
    *entered*, not where it's validated or enforced," applied here to identity as well)."""


@runtime_checkable
class AccountEnrollmentGateway(Protocol):
    """Step 1 — Auth & Tenancy's own enrollment surface, as seen from here."""

    async def enroll_owner(self, method: LoginMethod, tenancy: TenancyChoice) -> AccountEnrollment: ...


@runtime_checkable
class StartupRegistrar(Protocol):
    """§7.1's own sketch, restated here as the seam the wizard calls through. Concrete providers
    (`WindowsTaskSchedulerRegistrar`, `WindowsStartupFolderRegistrar`,
    `LinuxSystemdUserRegistrar`) are a Provider Registry, auto-selected from the already-detected
    `HardwareProfile`'s OS but swappable — see §7.1's own text for the full reasoning."""

    async def register(self, launcher_path: Path) -> None: ...
    async def deregister(self) -> None: ...
    async def is_registered(self) -> bool: ...


@runtime_checkable
class TunnelSetupGateway(Protocol):
    """Step 3 — Gateway's Tunnel Exposure sub-API (`v3-deepdive-43-tunnel-exposure.md`), as seen
    from here. That sub-API has no implementation yet (not even scaffolding) as of this wizard's
    own build — the seam exists so Setup does not need to wait on it; an unreachable collaborator
    degrades this one step, never the whole wizard (`docs/PRINCIPLES.md` §4.4)."""

    async def start_tunnel_login(self) -> str:
        """Returns the `cloudflared tunnel login` flow's own next-step URL/instruction."""
        ...

    async def confirm_hostname(self, hostname: str) -> TunnelSetupResult: ...


@dataclass(frozen=True)
class TunnelSetupResult:
    hostname: str
    public_facing: bool
    """Always `True` on success — completing this step is the real signal that Auth's 2FA
    enforcement floor tightens automatically (§7.2), not a separate setting an owner has to
    remember to also configure."""


@runtime_checkable
class GroupsSetupGateway(Protocol):
    """Step 4 — Groups API, as seen from here."""

    async def create_shared_space(self, name: str) -> str:
        """Returns the new group's id."""
        ...


@runtime_checkable
class BillingSetupGateway(Protocol):
    """Step 5 — Billing's own PSP setup (`v3-deepdive-22-billing-subscription-api.md` §3.2), as
    seen from here. `core/billing/psp/` is this project's own worked example of a Provider
    Registry group with independently-selectable providers — this seam calls into it, it does
    not reimplement any part of it."""

    async def configure_psp(
        self, provider: str, credentials: FrozenDict
    ) -> BillingSetupResult: ...

    async def set_proration_policy(
        self, upgrade: BillingProrationChoice, downgrade: BillingProrationChoice
    ) -> None: ...


@dataclass(frozen=True)
class BillingSetupResult:
    provider: str
    configured: bool


@runtime_checkable
class SmsSetupGateway(Protocol):
    """Step 6 — Notifications API's own provider-specific guided setup
    (`v3-deepdive-09-notifications-inbox-api.md` §4.3), as seen from here."""

    async def configure_provider(
        self, provider: SmsProviderChoice, credentials: FrozenDict
    ) -> SmsSetupResult: ...

    async def register_sender_name(self, provider: SmsProviderChoice, sender_name: str) -> None:
        """Semaphore/PhilSMS-specific — Philippine carriers filter unregistered sender names as
        spam. A no-op for Twilio, which the wizard never calls this for."""
        ...


@dataclass(frozen=True)
class SmsSetupResult:
    provider: SmsProviderChoice
    configured: bool
    sender_name_required: bool
    """`True` for Semaphore/PhilSMS specifically — tells the wizard whether the sender-name
    sub-step (`docs/SETUP_WIZARD_SCRIPT.md` Step 6's own "one more thing") applies."""


@runtime_checkable
class IngestionChannelGateway(Protocol):
    """Step 7 — Ingestion's Google Drive channel, as seen from here. `core/ingestion/` is
    0-byte scaffolding as of this wizard's own build; the seam is what lets Setup's own wizard
    be complete without waiting on it."""

    async def provision_drive_channel(self) -> IngestionChannelsResult: ...


@dataclass(frozen=True)
class IngestionChannelsResult:
    service_account_email: str
    """The address the wizard shows the owner to share their receipts folder with."""


@runtime_checkable
class AddressCheckingGateway(Protocol):
    """Step 8 — Geo/Address's own built-in provider, as seen from here."""

    async def enable_built_in_provider(self) -> None: ...


@runtime_checkable
class WebappBuilder(Protocol):
    """Gateway's `build_webapp()` (`v3-deepdive-19-gateway-api.md` §4.1), as seen from here.

    "Every fresh clone, including this first one, builds its own webapp bundle as part of this
    same routine, not a separately-scheduled step" (deep-dive §7.4). `services/gateway/` is
    0-byte scaffolding as of this module's own build — the seam is what lets the finalize
    routine be complete without waiting on it, the same posture `TunnelSetupGateway` and
    `IngestionChannelGateway` already take toward their own unbuilt siblings.
    """

    async def build(self, clone_dir: Path) -> None: ...


@dataclass(frozen=True)
class BootstrapReport:
    """The finalize routine's own outcome (§7.4), in the order its steps actually run.

    `venv_provision` is not in §7.4's own list — that section was written before
    `docs/VENV_AND_IMPORTS.md` existed to describe per-service venv provisioning at all. It
    belongs in this sequence for the same reason strip and webapp-build do: all three are
    one-time, whole-clone setup steps that must complete before Supervisor's Boot Sequence can
    trust the clone.
    """

    strip: StripReport
    venv_provision: ProvisionReport
    webapp_built: bool
    top_level_files_cleaned: tuple[str, ...]

    launcher_scripts_copied: tuple[str, ...] = ()
    """`start.bat`/`start.sh`, copied from the clone to the install root as siblings of every
    release directory (`docs/PRINCIPLES.md` §1.6, §4's own "the top-level directory structure...
    the `start.bat`/`start.sh` launcher... built as siblings"). Not in §7.4's own listed sequence
    — a real gap that sequence never named, closed here rather than left silently unbuilt."""

    install_config_written: bool = False
    """Whether `<install_root>/config/install.json`'s `dev_mode` flag was written by *this*
    finalize call. `False` on a second finalize against an already-configured install root — the
    flag is set once, at first clone, and read (never re-asked) by every later one (§4.1)."""

    @property
    def ok(self) -> bool:
        """Whether this clone is genuinely ready for Supervisor's Boot Sequence.

        Mirrors `ProvisionReport.fully_provisioned`'s own fail-closed posture: a clone with any
        step incomplete is not eligible, full stop — half-finalized is not a degraded state
        Supervisor should ever hand traffic to.
        """
        return self.strip.ok and self.venv_provision.fully_provisioned


@runtime_checkable
class AgentTokenSeedGateway(Protocol):
    """Agent Control's own token issuance, as seen from `dev_fixtures.py`.

    **Not a self-provisioning hole** — `core/agent_control/token_lifecycle.py`'s own rule
    is "a token is always issued by a real human"; this seam is only ever called from the
    `setup-dev` path, and running `setup-dev` at all is itself the same kind of explicit
    human decision §4.1 already treats as authorizing the trivial, silent implicit-owner
    creation for dev mode. `issued_by` is `"setup-dev-bootstrap"`, naming that decision as
    the authorizing act rather than pretending a specific person did it.
    """

    async def issue_dev_token(self, label: str) -> str:
        """Returns the new token's plaintext. Scoped to `DEV_OBSERVABILITY`-tier tools and
        below by the concrete implementation, never `owner`-equivalent — see
        `core/agent_control/token_lifecycle.py`'s own hard ceiling."""
        ...


@dataclass(frozen=True)
class DevFixturesReport:
    """`dev_fixtures.seed_dev_environment()`'s own outcome (§4.1)."""

    config_path: Path
    written: bool
    """`False` when a dev config already existed and was left alone — idempotent, matching
    every other Setup mechanism's own re-runnability."""

    agent_token_path: Path | None = None
    """Where the auto-issued dev agent token's plaintext was written, if
    `seed_dev_environment` was given an `AgentTokenSeedGateway`. `None` when no gateway was
    supplied — MCP access is opt-in to this seam, never assumed."""


@dataclass(frozen=True)
class SetupMetrics:
    """This API's own counters, snapshotted (`metrics.py`).

    Field names are the counter names — `metrics.py` derives them from this contract so the two
    cannot drift apart, the same convention `core/health/metrics.py` already established.
    """

    hardware_detections_run: int = 0
    hardware_detections_failed: int = 0
    external_reports_merged: int = 0
    venvs_provisioned: int = 0
    venvs_provision_failed: int = 0
    strip_operations_run: int = 0
    strip_errors: int = 0
    wizard_steps_completed: int = 0
    wizard_steps_skipped: int = 0


@dataclass(frozen=True)
class TermsAcceptance:
    accepted: bool
    accepted_at: datetime | None
    show_public_service_notice: bool
    """`True` only for `UseCase.PUBLIC` — the paragraph telling the owner they are responsible
    for their own legal review before real people trust them with data
    (`docs/SETUP_WIZARD_SCRIPT.md` Step 10, `docs/LEGAL_REVIEW_NEEDED.md`)."""
