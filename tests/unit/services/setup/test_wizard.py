"""`WizardEngine` (`v3-deepdive-11-setup-api.md` §7, `docs/SETUP_WIZARD_SCRIPT.md`).

Every collaborator here is a `Protocol`, so every fake below is checked against the real
`Protocol` it stands in for — `docs/HANDOFF_TO_LOCAL.md`'s own named lesson: "mismatched fakes
were the single most common failure across this whole phase."
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.setup.contracts import (
    AccountEnrollment,
    AccountEnrollmentGateway,
    AddressCheckingGateway,
    BillingSetupGateway,
    BillingSetupResult,
    GroupsSetupGateway,
    HardwareProfile,
    IngestionChannelGateway,
    IngestionChannelsResult,
    LoginMethod,
    RecommendedTier,
    SmsProviderChoice,
    SmsSetupGateway,
    SmsSetupResult,
    StartupRegistrar,
    TenancyChoice,
    TierProfile,
    TunnelSetupGateway,
    TunnelSetupResult,
    UseCase,
    WizardAnswer,
    WizardStepId,
)
from services.setup.wizard import WizardEngine


def _profile() -> HardwareProfile:
    return HardwareProfile(
        cpu_name="Test CPU", cores=8, threads=16, ram_gb=32, gpus=(), npus=(),
        detected_at=datetime.now(timezone.utc), source="os_probe",
    )


class _FakeScorer:
    def recommend(self, profile):
        return RecommendedTier(tier=TierProfile.BALANCED, reasoned=False)


class _FakeAccountGateway:
    def __init__(self):
        self.calls = []

    async def enroll_owner(self, method, tenancy):
        self.calls.append((method, tenancy))
        return AccountEnrollment(method=method, identity_ref="fake-owner-id")


class _FakeStartupRegistrar:
    def __init__(self):
        self.registered_with: Path | None = None

    async def register(self, launcher_path):
        self.registered_with = launcher_path

    async def deregister(self):
        self.registered_with = None

    async def is_registered(self):
        return self.registered_with is not None


class _FakeTunnelGateway:
    def __init__(self):
        self.confirmed_hostname: str | None = None

    async def start_tunnel_login(self):
        return "https://fake-login-url"

    async def confirm_hostname(self, hostname):
        self.confirmed_hostname = hostname
        return TunnelSetupResult(hostname=hostname, public_facing=True)


class _FakeGroupsGateway:
    def __init__(self):
        self.created: list[str] = []

    async def create_shared_space(self, name):
        self.created.append(name)
        return "fake-group-id"


class _FakeBillingGateway:
    def __init__(self):
        self.configured_provider: str | None = None
        self.proration: tuple | None = None

    async def configure_psp(self, provider, credentials):
        self.configured_provider = provider
        return BillingSetupResult(provider=provider, configured=True)

    async def set_proration_policy(self, upgrade, downgrade):
        self.proration = (upgrade, downgrade)


class _FakeSmsGateway:
    def __init__(self, sender_name_required=True):
        self._sender_name_required = sender_name_required
        self.configured_provider = None
        self.registered_sender_name = None

    async def configure_provider(self, provider, credentials):
        self.configured_provider = provider
        return SmsSetupResult(
            provider=provider, configured=True, sender_name_required=self._sender_name_required
        )

    async def register_sender_name(self, provider, sender_name):
        self.registered_sender_name = sender_name


class _FakeIngestionGateway:
    def __init__(self):
        self.provisioned = False

    async def provision_drive_channel(self):
        self.provisioned = True
        return IngestionChannelsResult(service_account_email="fake@example.iam.gserviceaccount.com")


class _FakeAddressGateway:
    def __init__(self):
        self.enabled = False

    async def enable_built_in_provider(self):
        self.enabled = True


def _conforms(fake, protocol) -> None:
    assert isinstance(fake, protocol), f"{fake!r} does not conform to {protocol!r}"


def test_every_fake_conforms_to_its_real_protocol():
    """The guard `docs/HANDOFF_TO_LOCAL.md` names as the single most-repeated failure mode this
    phase kept hitting: a mismatched fake."""
    _conforms(_FakeAccountGateway(), AccountEnrollmentGateway)
    _conforms(_FakeStartupRegistrar(), StartupRegistrar)
    _conforms(_FakeTunnelGateway(), TunnelSetupGateway)
    _conforms(_FakeGroupsGateway(), GroupsSetupGateway)
    _conforms(_FakeBillingGateway(), BillingSetupGateway)
    _conforms(_FakeSmsGateway(), SmsSetupGateway)
    _conforms(_FakeIngestionGateway(), IngestionChannelGateway)
    _conforms(_FakeAddressGateway(), AddressCheckingGateway)


async def _drive(engine, use_case, answers_by_step, *, accept_tos=True):
    """Runs the whole wizard for one branch, answering each step from `answers_by_step` when
    present, skipping (or auto-completing a mandatory step) otherwise. Returns the ordered list
    of steps actually shown.
    """
    gen = engine.run()
    prompt = await anext(gen)
    seen = [prompt.step_id]

    answer = WizardAnswer(step_id=WizardStepId.WELCOME, skipped=False, data={"use_case": use_case.value})
    try:
        prompt = await gen.asend(answer)
        seen.append(prompt.step_id)
        while True:
            if prompt.step_id in answers_by_step:
                ans = answers_by_step[prompt.step_id]
            elif prompt.step_id is WizardStepId.ACCOUNT:
                ans = WizardAnswer(step_id=prompt.step_id, skipped=False, data={"method": "sso"})
            elif prompt.step_id is WizardStepId.TERMS_OF_SERVICE:
                ans = WizardAnswer(step_id=prompt.step_id, skipped=False, data={"accepted": accept_tos})
            else:
                ans = WizardAnswer(step_id=prompt.step_id, skipped=True)
            prompt = await gen.asend(ans)
            seen.append(prompt.step_id)
    except StopAsyncIteration:
        pass
    return seen


# --- branch applicability, against the real script -----------------------------------------


def test_the_personal_branch_skips_tunnel_groups_billing_and_sms():
    """`docs/SETUP_WIZARD_SCRIPT.md`: Steps 3/4/5/6 are all explicitly "skipped for [1]"."""
    engine = WizardEngine(launcher_path=Path("start.sh"))
    seen = asyncio.run(_drive(engine, UseCase.PERSONAL, {}))

    assert WizardStepId.TUNNEL_EXPOSURE not in seen
    assert WizardStepId.GROUPS not in seen
    assert WizardStepId.BILLING not in seen
    assert WizardStepId.SMS_NOTIFICATIONS not in seen
    assert seen == [
        WizardStepId.WELCOME, WizardStepId.ACCOUNT, WizardStepId.RUN_ON_STARTUP,
        WizardStepId.RECEIPT_INGESTION, WizardStepId.ADDRESS_CHECKING, WizardStepId.HARDWARE_TIER,
        WizardStepId.TERMS_OF_SERVICE, WizardStepId.FINALIZE,
    ]


def test_the_team_branch_sees_every_step_including_groups():
    """Groups is `{TEAM}`-only per Step 4's own "Applies to: branch [2] only.\""""
    engine = WizardEngine(launcher_path=Path("start.sh"))
    seen = asyncio.run(_drive(engine, UseCase.TEAM, {}))

    assert WizardStepId.GROUPS in seen
    assert WizardStepId.TUNNEL_EXPOSURE in seen
    assert WizardStepId.BILLING in seen
    assert WizardStepId.SMS_NOTIFICATIONS in seen


def test_the_public_branch_gets_tunnel_billing_and_sms_but_not_groups():
    """Step 4's own reasoning: "not offered here since a public sign-up service's initial users
    aren't yet organized into any team" — Groups is excluded for PUBLIC specifically, the one
    step that is NOT simply "all non-personal branches."
    """
    engine = WizardEngine(launcher_path=Path("start.sh"))
    seen = asyncio.run(_drive(engine, UseCase.PUBLIC, {}))

    assert WizardStepId.GROUPS not in seen
    assert WizardStepId.TUNNEL_EXPOSURE in seen
    assert WizardStepId.BILLING in seen
    assert WizardStepId.SMS_NOTIFICATIONS in seen


# --- protocol-misuse validation --------------------------------------------------------------


def test_welcome_cannot_be_skipped():
    async def go():
        engine = WizardEngine(launcher_path=Path("start.sh"))
        gen = engine.run()
        await anext(gen)
        await gen.asend(WizardAnswer(step_id=WizardStepId.WELCOME, skipped=True))

    with pytest.raises(ValueError, match="cannot be skipped"):
        asyncio.run(go())


def test_an_invalid_use_case_value_raises_rather_than_silently_defaulting():
    async def go():
        engine = WizardEngine(launcher_path=Path("start.sh"))
        gen = engine.run()
        await anext(gen)
        await gen.asend(WizardAnswer(step_id=WizardStepId.WELCOME, skipped=False, data={"use_case": "not_a_real_use_case"}))

    with pytest.raises(ValueError):
        asyncio.run(go())


def test_terms_of_service_cannot_be_skipped():
    async def go():
        engine = WizardEngine(launcher_path=Path("start.sh"))
        seen = await _drive(engine, UseCase.PERSONAL, {
            WizardStepId.TERMS_OF_SERVICE: WizardAnswer(step_id=WizardStepId.TERMS_OF_SERVICE, skipped=True),
        })
        return seen

    with pytest.raises(ValueError, match="not skippable"):
        asyncio.run(go())


def test_declining_terms_of_service_acceptance_is_rejected():
    """Skippable-vs-accepted are two different axes for this one step: `skipped=False` but
    `accepted=False` is a real answer, not a protocol violation, and must still be rejected on
    its own separate ground.
    """
    async def go():
        engine = WizardEngine(launcher_path=Path("start.sh"))
        await _drive(engine, UseCase.PERSONAL, {}, accept_tos=False)

    with pytest.raises(ValueError, match="requires acceptance"):
        asyncio.run(go())


def test_an_answer_for_the_wrong_step_is_rejected():
    async def go():
        engine = WizardEngine(launcher_path=Path("start.sh"))
        gen = engine.run()
        await anext(gen)
        prompt = await gen.asend(WizardAnswer(step_id=WizardStepId.WELCOME, skipped=False, data={"use_case": "personal"}))
        assert prompt.step_id is WizardStepId.ACCOUNT
        await gen.asend(WizardAnswer(step_id=WizardStepId.BILLING, skipped=True))

    with pytest.raises(ValueError, match="expected an answer"):
        asyncio.run(go())


# --- collaborator side effects ---------------------------------------------------------------


def test_account_step_calls_the_gateway_with_the_right_method_and_tenancy():
    account_gw = _FakeAccountGateway()
    engine = WizardEngine(launcher_path=Path("start.sh"), account_gateway=account_gw)

    asyncio.run(_drive(engine, UseCase.TEAM, {
        WizardStepId.ACCOUNT: WizardAnswer(step_id=WizardStepId.ACCOUNT, skipped=False, data={"method": "passkey"}),
    }))

    assert account_gw.calls == [(LoginMethod.PASSKEY, TenancyChoice.MULTI)]


def test_run_on_startup_only_registers_when_the_owner_says_yes():
    registrar = _FakeStartupRegistrar()
    launcher = Path("start.sh")
    engine = WizardEngine(launcher_path=launcher, startup_registrar=registrar)

    asyncio.run(_drive(engine, UseCase.PERSONAL, {
        WizardStepId.RUN_ON_STARTUP: WizardAnswer(step_id=WizardStepId.RUN_ON_STARTUP, skipped=False, data={"enable": True}),
    }))

    assert registrar.registered_with == launcher


def test_run_on_startup_skipped_never_touches_the_registrar():
    registrar = _FakeStartupRegistrar()
    engine = WizardEngine(launcher_path=Path("start.sh"), startup_registrar=registrar)

    asyncio.run(_drive(engine, UseCase.PERSONAL, {
        WizardStepId.RUN_ON_STARTUP: WizardAnswer(step_id=WizardStepId.RUN_ON_STARTUP, skipped=True),
    }))

    assert registrar.registered_with is None


def test_billing_step_configures_the_psp_and_sets_independent_proration_policies():
    billing_gw = _FakeBillingGateway()
    engine = WizardEngine(launcher_path=Path("start.sh"), billing_gateway=billing_gw)

    asyncio.run(_drive(engine, UseCase.TEAM, {
        WizardStepId.BILLING: WizardAnswer(step_id=WizardStepId.BILLING, skipped=False, data={
            "provider": "paymongo",
            "upgrade_policy": "upgrade_immediate_prorated",
            "downgrade_policy": "downgrade_no_refund",
        }),
    }))

    assert billing_gw.configured_provider == "paymongo"
    assert billing_gw.proration is not None


def test_sms_step_registers_a_sender_name_only_when_the_provider_requires_it():
    """Semaphore/PhilSMS require it; Twilio's own `_FakeSmsGateway(sender_name_required=False)`
    stands in for that distinction (`docs/SETUP_WIZARD_SCRIPT.md` Step 6's own carve-out).
    """
    sms_gw = _FakeSmsGateway(sender_name_required=True)
    engine = WizardEngine(launcher_path=Path("start.sh"), sms_gateway=sms_gw)

    asyncio.run(_drive(engine, UseCase.TEAM, {
        WizardStepId.SMS_NOTIFICATIONS: WizardAnswer(step_id=WizardStepId.SMS_NOTIFICATIONS, skipped=False, data={
            "provider": "semaphore", "sender_name": "MyReceipts",
        }),
    }))

    assert sms_gw.configured_provider is SmsProviderChoice.SEMAPHORE
    assert sms_gw.registered_sender_name == "MyReceipts"


def test_sms_step_does_not_register_a_sender_name_when_not_required():
    sms_gw = _FakeSmsGateway(sender_name_required=False)
    engine = WizardEngine(launcher_path=Path("start.sh"), sms_gateway=sms_gw)

    asyncio.run(_drive(engine, UseCase.TEAM, {
        WizardStepId.SMS_NOTIFICATIONS: WizardAnswer(step_id=WizardStepId.SMS_NOTIFICATIONS, skipped=False, data={
            "provider": "twilio", "sender_name": "should be ignored",
        }),
    }))

    assert sms_gw.registered_sender_name is None


def test_receipt_ingestion_only_provisions_drive_when_that_channel_is_chosen():
    ingestion_gw = _FakeIngestionGateway()
    engine = WizardEngine(launcher_path=Path("start.sh"), ingestion_gateway=ingestion_gw)

    asyncio.run(_drive(engine, UseCase.PERSONAL, {
        WizardStepId.RECEIPT_INGESTION: WizardAnswer(step_id=WizardStepId.RECEIPT_INGESTION, skipped=False, data={"channel": "upload_only"}),
    }))
    assert ingestion_gw.provisioned is False

    ingestion_gw2 = _FakeIngestionGateway()
    engine2 = WizardEngine(launcher_path=Path("start.sh"), ingestion_gateway=ingestion_gw2)
    asyncio.run(_drive(engine2, UseCase.PERSONAL, {
        WizardStepId.RECEIPT_INGESTION: WizardAnswer(step_id=WizardStepId.RECEIPT_INGESTION, skipped=False, data={"channel": "google_drive"}),
    }))
    assert ingestion_gw2.provisioned is True


def test_hardware_tier_prompt_carries_the_recommended_tier_in_context():
    engine = WizardEngine(
        launcher_path=Path("start.sh"), hardware_profile=_profile(), hardware_scorer=_FakeScorer(),
    )

    async def get_hardware_prompt():
        gen = engine.run()
        prompt = await anext(gen)
        answer = WizardAnswer(step_id=WizardStepId.WELCOME, skipped=False, data={"use_case": "personal"})
        prompt = await gen.asend(answer)
        while prompt.step_id is not WizardStepId.HARDWARE_TIER:
            skip = WizardAnswer(step_id=prompt.step_id, skipped=True)
            if prompt.step_id is WizardStepId.ACCOUNT:
                skip = WizardAnswer(step_id=prompt.step_id, skipped=False, data={"method": "sso"})
            prompt = await gen.asend(skip)
        return prompt

    prompt = asyncio.run(get_hardware_prompt())
    assert prompt.context["recommended_tier"] == "balanced"
    assert prompt.context["reasoned"] is False


def test_declining_a_tier_choice_falls_back_to_the_scorers_recommendation():
    """`engine.progress` is the real object `run()` mutates — read directly, not mirrored."""
    engine = WizardEngine(
        launcher_path=Path("start.sh"), hardware_profile=_profile(), hardware_scorer=_FakeScorer(),
    )
    asyncio.run(_drive(engine, UseCase.PERSONAL, {
        WizardStepId.HARDWARE_TIER: WizardAnswer(step_id=WizardStepId.HARDWARE_TIER, skipped=True),
    }))

    assert engine.progress.initial_tier == "balanced"


# --- terms of service public-only notice ------------------------------------------------------


def test_the_public_service_legal_notice_only_shows_for_the_public_branch():
    """Step 10: the extra paragraph is `PUBLIC`-only; the step itself still runs for all three
    branches (`docs/SETUP_WIZARD_SCRIPT.md`'s own footnote)."""
    engine_personal = WizardEngine(launcher_path=Path("start.sh"))
    engine_public = WizardEngine(launcher_path=Path("start.sh"))

    async def get_tos_prompt(engine, use_case):
        gen = engine.run()
        prompt = await anext(gen)
        prompt = await gen.asend(WizardAnswer(step_id=WizardStepId.WELCOME, skipped=False, data={"use_case": use_case.value}))
        while prompt.step_id is not WizardStepId.TERMS_OF_SERVICE:
            ans = WizardAnswer(step_id=prompt.step_id, skipped=True)
            if prompt.step_id is WizardStepId.ACCOUNT:
                ans = WizardAnswer(step_id=prompt.step_id, skipped=False, data={"method": "sso"})
            prompt = await gen.asend(ans)
        return prompt

    personal_prompt = asyncio.run(get_tos_prompt(engine_personal, UseCase.PERSONAL))
    public_prompt = asyncio.run(get_tos_prompt(engine_public, UseCase.PUBLIC))

    assert personal_prompt.context["show_public_service_notice"] is False
    assert public_prompt.context["show_public_service_notice"] is True


# --- graceful degradation on unbuilt siblings --------------------------------------------------


def test_every_collaborator_defaulting_to_none_still_completes_the_whole_wizard():
    """The core resilience guarantee: Tunnel Exposure and Ingestion are 0-byte scaffolding as of
    this module's own build, and every other collaborator is optional too. A wizard with EVERY
    seam unset must still run start-to-finish rather than blocking on any of them
    (`docs/PRINCIPLES.md` §4.4).
    """
    engine = WizardEngine(launcher_path=Path("start.sh"))
    seen = asyncio.run(_drive(engine, UseCase.PUBLIC, {}))

    assert seen[0] is WizardStepId.WELCOME
    assert seen[-1] is WizardStepId.FINALIZE


# --- final state ------------------------------------------------------------------------------


def test_build_final_state_raises_before_welcome_is_answered():
    engine = WizardEngine(launcher_path=Path("start.sh"))
    with pytest.raises(ValueError, match="before WELCOME"):
        engine.build_final_state()


def test_build_final_state_reflects_the_real_run_tenancy_owner_and_chosen_tier():
    """Drives a real wizard run end to end and reads `engine.build_final_state()` afterward —
    the real way `service.py` is expected to use this API, and the real object `run()` mutated
    throughout, not a value the test reconstructs by hand.
    """
    engine = WizardEngine(
        launcher_path=Path("start.sh"), hardware_profile=_profile(), hardware_scorer=_FakeScorer(),
        account_gateway=_FakeAccountGateway(),
    )
    asyncio.run(_drive(engine, UseCase.PERSONAL, {
        WizardStepId.HARDWARE_TIER: WizardAnswer(step_id=WizardStepId.HARDWARE_TIER, skipped=False, data={"tier": "lightweight"}),
    }))

    final = engine.build_final_state()

    assert final.tenancy_mode == "single"
    assert final.owner_created is True
    assert final.initial_tier == "lightweight"
    assert final.completed_at is not None
