"""The first-run wizard's own orchestration (deep-dive §7).

`docs/SETUP_WIZARD_SCRIPT.md` is the word-for-word user-facing copy; this module carries none of
it. `WizardEngine.run()` is an async generator — it `yield`s a `WizardStepPrompt` and receives
the client's `WizardAnswer` back via `.asend(...)`, one step at a time, applying whichever
collaborator's own effect that step calls for before advancing. This shape maps directly onto a
bidirectional-streaming gRPC RPC (`service.py`'s own concern) without coupling the engine itself
to gRPC at all — every collaborator is a `Protocol`, so the whole flow is testable end to end
with fakes, the same posture `services/execution_core/pipeline.py` already established for its
own seven collaborators.

**Every collaborator argument may be `None`.** Several of the real APIs behind these seams —
Gateway's Tunnel Exposure sub-API, Ingestion — are 0-byte scaffolding as of this module's own
build. A `None` collaborator degrades that one step to "not configured" and the wizard keeps
moving (`docs/PRINCIPLES.md` §4.4) — it never blocks a first-run install on a sibling that has
not been built yet.

**Protocol misuse raises; a legitimately unreachable collaborator does not.** Skipping a step
this module's own `STEP_DEFINITIONS` marks `skippable=False`, or omitting a step's required
answer field, is a caller-side programming error — `ValueError`, the same distinction
`services/execution_core/state_machine.py`'s own `transition()` draws between an invalid
business transition (returned as data) and calling the object wrong at all. `service.py`'s own
gRPC layer is what translates a raised `ValueError` into a real `INVALID_ARGUMENT` status for an
actual client — this module is not itself the gRPC boundary `docs/PRINCIPLES.md` §4.1 governs.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

from .contracts import (
    DEFAULT_STEP_SEQUENCE,
    STEP_DEFINITIONS,
    AccountEnrollmentGateway,
    AddressCheckingGateway,
    BillingProrationChoice,
    BillingSetupGateway,
    FrozenDict,
    GroupsSetupGateway,
    HardwareProfile,
    HardwareScorer,
    IngestionChannelGateway,
    LoginMethod,
    RecommendedTier,
    SmsProviderChoice,
    SmsSetupGateway,
    StartupRegistrar,
    TenancyChoice,
    TunnelSetupGateway,
    UseCase,
    WizardAnswer,
    WizardState,
    WizardStepId,
    WizardStepPrompt,
)

__all__ = ["WizardEngine"]


def _tenancy_for(use_case: UseCase) -> TenancyChoice:
    """Step 0's own stated mapping: `tenancy_mode: single` for personal, `multi` for the other
    two — the one piece of Step 0's technical footnote that is pure data, not a side effect."""
    return TenancyChoice.SINGLE if use_case is UseCase.PERSONAL else TenancyChoice.MULTI


@dataclass
class _WizardProgress:
    """Mutable accumulator, private to one `run()` call — never shared across concurrent
    wizard runs, since each is its own generator instance with its own local state."""

    use_case: UseCase | None = None
    owner_created: bool = False
    drive_restore_offered: bool = False
    initial_tier: str = ""


class WizardEngine:
    """Owns the step sequence and dispatch; owns none of the sibling APIs it calls into."""

    def __init__(
        self,
        *,
        launcher_path: Path,
        hardware_profile: HardwareProfile | None = None,
        hardware_scorer: HardwareScorer | None = None,
        account_gateway: AccountEnrollmentGateway | None = None,
        startup_registrar: StartupRegistrar | None = None,
        tunnel_gateway: TunnelSetupGateway | None = None,
        groups_gateway: GroupsSetupGateway | None = None,
        billing_gateway: BillingSetupGateway | None = None,
        sms_gateway: SmsSetupGateway | None = None,
        ingestion_gateway: IngestionChannelGateway | None = None,
        address_gateway: AddressCheckingGateway | None = None,
    ) -> None:
        self._launcher_path = launcher_path
        self._hardware_profile = hardware_profile
        self._hardware_scorer = hardware_scorer
        self._account_gateway = account_gateway
        self._startup_registrar = startup_registrar
        self._tunnel_gateway = tunnel_gateway
        self._groups_gateway = groups_gateway
        self._billing_gateway = billing_gateway
        self._sms_gateway = sms_gateway
        self._ingestion_gateway = ingestion_gateway
        self._address_gateway = address_gateway
        self.progress = _WizardProgress()
        """The single source of truth for this run's accumulated state — a public attribute,
        deliberately, so a caller can inspect it after driving `run()` to completion without
        needing to reconstruct or mirror it externally. One `WizardEngine` instance serves
        exactly one wizard run (a fresh instance per first-run install), so there is no
        multi-run aliasing concern in giving this direct access."""

    def applicable_steps(self, use_case: UseCase) -> tuple[WizardStepId, ...]:
        """§7's step sequence, filtered to the branches `docs/SETUP_WIZARD_SCRIPT.md` actually
        shows a given `use_case` — always excludes `WELCOME` itself, since by the time a
        `use_case` exists to filter with, `WELCOME` has already been answered."""
        return tuple(
            step_id
            for step_id in DEFAULT_STEP_SEQUENCE
            if step_id is not WizardStepId.WELCOME and use_case in STEP_DEFINITIONS[step_id].applies_to
        )

    async def run(self) -> AsyncGenerator[WizardStepPrompt, WizardAnswer]:
        """The whole wizard, start to finish, as an async generator.

        Usage: `gen = engine.run(); prompt = await anext(gen)` starts it (the first `WELCOME`
        prompt costs nothing to produce and needs no prior answer); every subsequent
        `await gen.asend(answer)` both supplies the previous prompt's answer and returns the
        next prompt, until `StopAsyncIteration` — the standard Python generator-coroutine
        protocol, not a bespoke one.
        """
        welcome_answer = yield WizardStepPrompt(step_id=WizardStepId.WELCOME)
        self.progress.use_case = self._require_use_case(welcome_answer)

        for step_id in self.applicable_steps(self.progress.use_case):
            prompt = self._build_prompt(step_id, self.progress)
            answer = yield prompt
            self._validate_answer(step_id, answer)
            await self._apply_answer(step_id, self.progress, answer)

    def build_final_state(self) -> WizardState:
        """The wizard's own `WizardState` (§3), once `FINALIZE` has been reached. Kept as a
        separate call rather than something `run()` itself returns, because an async generator's
        return value is not reachable through the normal `.asend()` iteration protocol without
        catching `StopAsyncIteration` — a caller that wants the final state calls this directly
        once the generator is exhausted, reading `self.progress`, the same object `run()` was
        mutating throughout.
        """
        if self.progress.use_case is None:
            raise ValueError("cannot build a final WizardState before WELCOME has been answered")
        return WizardState(
            tenancy_mode=_tenancy_for(self.progress.use_case).value,
            owner_created=self.progress.owner_created,
            initial_tier=self.progress.initial_tier,
            drive_restore_offered=self.progress.drive_restore_offered,
            completed_at=datetime.now(timezone.utc),
        )

    # --- prompt construction --------------------------------------------------------------

    def _build_prompt(self, step_id: WizardStepId, progress: _WizardProgress) -> WizardStepPrompt:
        context: dict = {}

        if step_id is WizardStepId.HARDWARE_TIER and self._hardware_profile and self._hardware_scorer:
            recommended: RecommendedTier = self._hardware_scorer.recommend(self._hardware_profile)
            context = {"recommended_tier": recommended.tier.value, "reasoned": recommended.reasoned}

        if step_id is WizardStepId.TERMS_OF_SERVICE:
            context = {"show_public_service_notice": progress.use_case is UseCase.PUBLIC}

        return WizardStepPrompt(step_id=step_id, context=FrozenDict(context))

    # --- validation -------------------------------------------------------------------------

    def _require_use_case(self, answer: WizardAnswer) -> UseCase:
        if answer.skipped:
            raise ValueError("WELCOME cannot be skipped — every install needs a use case")
        raw = answer.data.get("use_case")
        if raw is None:
            raise ValueError("WELCOME's answer must set data['use_case']")
        return UseCase(raw)

    def _validate_answer(self, step_id: WizardStepId, answer: WizardAnswer) -> None:
        if answer.step_id is not step_id:
            raise ValueError(f"expected an answer for {step_id.value!r}, got {answer.step_id.value!r}")
        if answer.skipped and not STEP_DEFINITIONS[step_id].skippable:
            raise ValueError(f"{step_id.value!r} is not skippable")

    # --- per-step effects -------------------------------------------------------------------

    async def _apply_answer(
        self, step_id: WizardStepId, progress: _WizardProgress, answer: WizardAnswer
    ) -> None:
        # HARDWARE_TIER is the one exception to "skipped means no-op below": declining Step 9
        # means accepting the pre-selected recommendation (`docs/SETUP_WIZARD_SCRIPT.md` shows
        # it as already checked, `[x] Balanced`), which is itself a side effect — it sets
        # `initial_tier` — not the absence of one. `_apply_hardware_tier` already handles both a
        # chosen tier and a missing one via the same fallback, so it always runs.
        if step_id is WizardStepId.HARDWARE_TIER:
            await self._apply_hardware_tier(progress, answer)
            return

        if answer.skipped:
            return  # Every other skippable step's decline is itself the outcome — no call.

        handler = self._HANDLERS.get(step_id)
        if handler is not None:
            await handler(self, progress, answer)

    async def _apply_account(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._account_gateway is None:
            return
        method = LoginMethod(answer.data["method"])
        tenancy = _tenancy_for(progress.use_case)
        await self._account_gateway.enroll_owner(method, tenancy)
        progress.owner_created = True
        progress.drive_restore_offered = bool(answer.data.get("drive_restore_offered", False))

    async def _apply_run_on_startup(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._startup_registrar is None:
            return
        if answer.data.get("enable"):
            await self._startup_registrar.register(self._launcher_path)

    async def _apply_tunnel_exposure(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._tunnel_gateway is None:
            return
        hostname = answer.data.get("hostname")
        if hostname:
            await self._tunnel_gateway.confirm_hostname(str(hostname))

    async def _apply_groups(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._groups_gateway is None:
            return
        if answer.data.get("choice") == "shared_space":
            await self._groups_gateway.create_shared_space(str(answer.data.get("name", "")))

    async def _apply_billing(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._billing_gateway is None:
            return
        provider = answer.data.get("provider")
        if provider:
            await self._billing_gateway.configure_psp(str(provider), FrozenDict(answer.data.get("credentials", {})))
        upgrade = answer.data.get("upgrade_policy")
        downgrade = answer.data.get("downgrade_policy")
        if upgrade and downgrade:
            await self._billing_gateway.set_proration_policy(
                BillingProrationChoice(upgrade), BillingProrationChoice(downgrade)
            )

    async def _apply_sms(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._sms_gateway is None:
            return
        provider = answer.data.get("provider")
        if not provider:
            return
        choice = SmsProviderChoice(provider)
        result = await self._sms_gateway.configure_provider(choice, FrozenDict(answer.data.get("credentials", {})))
        sender_name = answer.data.get("sender_name")
        if result.sender_name_required and sender_name:
            await self._sms_gateway.register_sender_name(choice, str(sender_name))

    async def _apply_receipt_ingestion(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._ingestion_gateway is None:
            return
        if answer.data.get("channel") == "google_drive":
            await self._ingestion_gateway.provision_drive_channel()

    async def _apply_address_checking(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        if self._address_gateway is None:
            return
        if answer.data.get("choice") == "built_in":
            await self._address_gateway.enable_built_in_provider()

    async def _apply_hardware_tier(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        chosen = answer.data.get("tier")
        if chosen:
            progress.initial_tier = str(chosen)
        elif self._hardware_scorer is not None and self._hardware_profile is not None:
            progress.initial_tier = self._hardware_scorer.recommend(self._hardware_profile).tier.value

    async def _apply_terms_of_service(self, progress: _WizardProgress, answer: WizardAnswer) -> None:
        """Validates acceptance; does not persist a `TermsAcceptance`.

        No collaborator seam owns that storage — it is naturally Auth's territory (recording
        what an owner agreed to alongside their account), but was never specified as one of this
        wizard's own Protocol seams. Left as a real, named gap rather than inventing a seam not
        asked for; `TermsAcceptance` stays in `contracts.py` as the shape a future seam would
        return.
        """
        accepted = bool(answer.data.get("accepted", False))
        if not accepted:
            raise ValueError("TERMS_OF_SERVICE requires acceptance to proceed")

    _HANDLERS: ClassVar[dict[WizardStepId, Callable[[WizardEngine, _WizardProgress, WizardAnswer], Awaitable[None]]]] = {
        WizardStepId.ACCOUNT: _apply_account,
        WizardStepId.RUN_ON_STARTUP: _apply_run_on_startup,
        WizardStepId.TUNNEL_EXPOSURE: _apply_tunnel_exposure,
        WizardStepId.GROUPS: _apply_groups,
        WizardStepId.BILLING: _apply_billing,
        WizardStepId.SMS_NOTIFICATIONS: _apply_sms,
        WizardStepId.RECEIPT_INGESTION: _apply_receipt_ingestion,
        WizardStepId.ADDRESS_CHECKING: _apply_address_checking,
        WizardStepId.TERMS_OF_SERVICE: _apply_terms_of_service,
    }
    # HARDWARE_TIER deliberately absent — dispatched directly in `_apply_answer`, not through
    # this table, since it is the one step whose skip still has a side effect.
