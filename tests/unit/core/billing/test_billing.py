"""Webhook verification, the deletion hold, proration, and billing-off-by-default (§3–§5, §9).

Both testing hooks §9 names:

* **Webhook signature rejection test** — "an unsigned or incorrectly-signed webhook payload is
  rejected, never processed as a real event — direct validation of §5's hard requirement."
* **Deletion-hold state transition test** — "confirms `pending_deletion_hold` correctly blocks
  new charges immediately while allowing final invoice resolution, matching Account Guardian's
  own `BILLING_HOLD` expectations exactly."

The webhook one is signed with a **real HMAC** rather than a stubbed verifier. §5 calls the
unverified endpoint "a real, exploitable surface (anyone who discovers the URL could fake a
'payment succeeded' event without this check)", and a test that mocked `verify_webhook` would
prove only that the code calls a function — not that the function rejects anything. So these
tests compute genuine signatures and tamper with genuine payloads.

§3.1's billing-off-by-default gets real coverage too, because it is the state a fresh install is
actually in and the easiest thing to accidentally break by treating it as an error condition.
"""

from __future__ import annotations

import asyncio

import pytest

from common.frozen_dict import FrozenDict
from core.billing.contracts import (
    BILLING_DISABLED_BY_DEFAULT,
    DEFAULT_PROVIDER,
    FREE_TIER,
    BillingConfig,
    DowngradeProrationPolicy,
    PaymentStatus,
    SubscriptionStatus,
    UpgradeProrationPolicy,
)
from core.billing.psp.base import (
    ProviderRegistry,
    UnconfiguredProvider,
    constant_time_signature_matches,
    hmac_sha256_hex,
)
from core.billing.psp.paymongo_provider import PayMongoProvider
from core.billing.psp.xendit_provider import XenditProvider
from core.billing.subscription import (
    SubscriptionService,
    prorate_downgrade,
    prorate_upgrade,
)

WEBHOOK_SECRET = "whsec_test_do_not_use"
PAYLOAD = b'{"event":"payment.paid","data":{"id":"ch_123","amount":49900}}'


def run(coro):
    return asyncio.run(coro)


def signed(payload: bytes = PAYLOAD, secret: str = WEBHOOK_SECRET) -> str:
    """A genuine signature for `payload`, computed the way the provider computes it."""
    return hmac_sha256_hex(secret, payload)


def configured_service(**overrides) -> SubscriptionService:
    """A service with billing enabled and a real PayMongo provider registered."""
    providers = ProviderRegistry()
    providers.register(PayMongoProvider(webhook_secret=WEBHOOK_SECRET))
    config = BillingConfig(
        enabled=True,
        provider="paymongo",
        credentials=FrozenDict({"paymongo_webhook_secret": WEBHOOK_SECRET}),
        **overrides,
    )
    return SubscriptionService(config, providers=providers)


# ------------------------------------------------------- §3.1: billing is off by default


def test_a_fresh_install_has_billing_disabled():
    """§3.1 calls this "a real correction worth being explicit about".

    This API existing in an install does not mean tiers are active — the default is every tier
    free with no PSP configured, and an owner opts in later.
    """
    assert BILLING_DISABLED_BY_DEFAULT
    assert not BillingConfig().enabled
    assert not BillingConfig().configured


def test_enabled_without_credentials_is_not_configured():
    """A real misconfiguration rather than a half-state to tolerate.

    It would gate paid tiers while no charge could ever be taken, so callers check `configured`
    rather than `enabled` alone.
    """
    config = BillingConfig(enabled=True, provider="paymongo")

    assert config.enabled
    assert not config.configured


def test_billing_off_still_allows_tier_assignment():
    """What billing being off removes is charging, not the concept of a tier.

    §1 is explicit that a self-hosted owner can "run every tier free (no PSP configured, tier
    gates simply never trigger)" — so subscription creation has to keep working with no PSP.
    """
    service = SubscriptionService()

    result = service.create_subscription("user-1", "pro")

    assert result.ok
    assert result.subscription.tier == "pro"


def test_billing_off_resolves_to_the_unconfigured_provider():
    """Which refuses charges and invents nothing.

    A stub that pretended a charge succeeded would grant a paid tier nobody paid for.
    """
    assert isinstance(SubscriptionService().provider(), UnconfiguredProvider)


def test_a_provider_named_in_config_but_never_registered_falls_back_safely():
    """A config typo must not take the service down — but must not open it either.

    Falling back to `UnconfiguredProvider` means charges are refused, which is the safe reading
    of "the provider you named does not exist".
    """
    service = SubscriptionService(
        BillingConfig(enabled=True, provider="not-a-real-psp"), providers=ProviderRegistry()
    )

    assert isinstance(service.provider(), UnconfiguredProvider)


def test_paymongo_is_the_documented_default():
    assert DEFAULT_PROVIDER == "paymongo"


# --------------------------------------------------------- §9's webhook signature hook


def test_a_correctly_signed_webhook_is_accepted():
    """The positive case, so the rejections below are not passing vacuously."""
    service = configured_service()

    result = run(service.handle_webhook(PAYLOAD, signed()))

    assert result.accepted
    assert result.verified


def test_an_unsigned_webhook_is_rejected():
    """§9's hook, first half: "an unsigned ... payload is rejected"."""
    service = configured_service()

    result = run(service.handle_webhook(PAYLOAD, ""))

    assert not result.accepted
    assert not result.verified
    assert result.error_code == "WEBHOOK_SIGNATURE_INVALID"


def test_an_incorrectly_signed_webhook_is_rejected():
    """§9's hook, second half — and the one an attacker would actually attempt."""
    service = configured_service()

    result = run(service.handle_webhook(PAYLOAD, "deadbeef" * 8))

    assert not result.accepted
    assert result.error_code == "WEBHOOK_SIGNATURE_INVALID"


def test_a_tampered_payload_fails_its_own_signature():
    """The whole point of signing: the signature covers the content, not just the request.

    This is the concrete attack §5 describes — someone who found the URL editing an amount, or
    faking a "payment succeeded" for a charge that never happened.
    """
    service = configured_service()
    honest_signature = signed()
    tampered = PAYLOAD.replace(b'"amount":49900', b'"amount":1')

    result = run(service.handle_webhook(tampered, honest_signature))

    assert not result.accepted


def test_a_signature_from_the_wrong_secret_is_rejected():
    """An attacker signing with their own secret gains nothing."""
    service = configured_service()

    result = run(service.handle_webhook(PAYLOAD, signed(secret="attackers_own_secret")))

    assert not result.accepted


def test_an_install_with_no_webhook_secret_verifies_nothing():
    """"Unverifiable" must never widen into "accepted".

    An install that cannot verify has no basis to trust anything, so the check returns False
    rather than being skipped.
    """
    provider = PayMongoProvider(webhook_secret="")

    assert not run(provider.verify_webhook(PAYLOAD, signed()))


def test_a_duplicate_of_a_verified_event_is_rejected_as_a_duplicate_not_a_forgery():
    """Every payment provider retries delivery; that is normal, not an attack.

    Keeping the two rejections distinct is what lets an operator tell "someone is probing the
    endpoint" from "the PSP retried", which mean completely different things.
    """
    service = configured_service()
    run(service.handle_webhook(PAYLOAD, signed()))

    result = run(service.handle_webhook(PAYLOAD, signed()))

    assert not result.accepted
    assert result.verified
    assert result.error_code == "DUPLICATE_WEBHOOK_EVENT"


def test_duplicate_detection_runs_after_verification_not_before():
    """An unsigned duplicate is still an unsigned payload.

    Reporting it as a duplicate would tell an attacker probing the endpoint which event ids
    already exist — a small disclosure, and free to avoid by ordering the checks correctly.
    """
    service = configured_service()
    run(service.handle_webhook(PAYLOAD, signed()))

    result = run(service.handle_webhook(PAYLOAD, "not-a-signature"))

    assert result.error_code == "WEBHOOK_SIGNATURE_INVALID"


def test_a_verifier_that_raises_is_treated_as_unverified():
    """An erroring verifier has not verified anything.

    Any other reading would turn a provider bug into an open endpoint.
    """

    class Exploding(PayMongoProvider):
        async def verify_webhook(self, payload: bytes, signature: str) -> bool:
            raise RuntimeError("provider blew up")

    providers = ProviderRegistry()
    providers.register(Exploding(webhook_secret=WEBHOOK_SECRET))
    service = SubscriptionService(
        BillingConfig(enabled=True, provider="paymongo"), providers=providers
    )

    assert not run(service.handle_webhook(PAYLOAD, signed())).accepted


def test_signature_comparison_is_constant_time():
    """A byte-by-byte `==` leaks the correct signature one character at a time.

    Against an endpoint an attacker can call repeatedly, that is enough to reconstruct a valid
    signature — exactly the "real, exploitable surface" §5 names.
    """
    assert constant_time_signature_matches("abc123", "abc123")
    assert not constant_time_signature_matches("abc123", "abc124")
    assert not constant_time_signature_matches("", "abc123")
    assert not constant_time_signature_matches("abc123", "")


def test_both_providers_verify_their_own_signatures():
    """§3: both are "real, concrete implementations — not a deferred either/or".

    A Xendit that could not verify a webhook would make "never requiring a rewrite to switch"
    false the moment anyone tried.
    """
    for provider in (
        PayMongoProvider(webhook_secret=WEBHOOK_SECRET),
        XenditProvider(webhook_secret=WEBHOOK_SECRET),
    ):
        assert run(provider.verify_webhook(PAYLOAD, signed()))
        assert not run(provider.verify_webhook(PAYLOAD, "wrong"))


# ------------------------------------------------------- §9's deletion-hold hook (§4)


def test_a_deletion_hold_blocks_new_charges_immediately():
    """§9's hook, first half — and §4's cross-API contract with Account Guardian.

    "A deletion request stops new charges immediately." Charging someone who has asked to be
    deleted is the kind of thing that becomes a complaint rather than a bug report.
    """
    service = configured_service()
    subscription = service.create_subscription("user-1", "pro").subscription

    service.place_deletion_hold(subscription.subscription_id)
    held = service.get(subscription.subscription_id)

    assert held.status is SubscriptionStatus.PENDING_DELETION_HOLD
    assert not held.accepts_new_charges


def test_a_held_subscription_still_settles_its_final_invoice():
    """§9's hook, second half: the hold "allow[s] final invoice resolution".

    This is why `PENDING_DELETION_HOLD` is its own status rather than a variant of `CANCELLED` —
    a cancelled subscription is finished, while this one still has money to settle before
    Account Guardian's deletion may proceed.
    """
    service = configured_service()
    subscription = service.create_subscription("user-1", "pro").subscription
    service.place_deletion_hold(subscription.subscription_id)

    assert service.get(subscription.subscription_id).settles_final_invoice


def test_a_tier_change_is_refused_while_on_hold():
    """New charges stopped means stopped, including the ones a tier upgrade would create."""
    service = configured_service()
    subscription = service.create_subscription("user-1", "basic").subscription
    service.place_deletion_hold(subscription.subscription_id)

    result, proration = service.change_tier(
        subscription.subscription_id, "pro", price_delta_minor=20000
    )

    assert not result.ok
    assert result.error_code == "CHARGES_BLOCKED_BY_DELETION_HOLD"
    assert proration is None
    assert service.metrics.snapshot().charges_blocked_by_hold == 1


def test_account_guardian_polls_one_method_rather_than_reading_the_enum():
    """The cross-API contract is a call, not a shared understanding of a status value.

    Account Guardian reading `SubscriptionStatus` directly would couple its deletion flow to
    this API's enum, and renaming a member would silently change when deletions proceed.
    """
    service = configured_service()
    subscription = service.create_subscription("user-1", "pro").subscription

    assert service.billing_resolved(subscription.subscription_id)
    service.place_deletion_hold(subscription.subscription_id)
    assert not service.billing_resolved(subscription.subscription_id)
    service.release_deletion_hold(subscription.subscription_id)
    assert service.billing_resolved(subscription.subscription_id)


def test_releasing_a_hold_cancels_rather_than_reactivating():
    """The user asked to be deleted.

    Returning them to an active paid subscription after settling the final invoice would start
    charging them again — the opposite of what the request meant.
    """
    service = configured_service()
    subscription = service.create_subscription("user-1", "pro").subscription
    service.place_deletion_hold(subscription.subscription_id)

    released = service.release_deletion_hold(subscription.subscription_id).subscription

    assert released.status is SubscriptionStatus.CANCELLED
    assert released.tier == FREE_TIER


def test_billing_resolved_is_false_for_a_subscription_that_does_not_exist():
    """Account Guardian must not proceed with a deletion on the strength of a missing record."""
    assert not configured_service().billing_resolved("sub_does_not_exist")


# --------------------------------------------------------------- §3.3's two axes


def test_upgrade_and_downgrade_policies_are_configured_independently():
    """§3.3: "not one shared policy governing both directions".

    The situations have different stakes — an upgrade gives the user something, a downgrade
    takes something away — and generosity means a different thing in each direction.
    """
    config = BillingConfig(
        upgrade_proration=UpgradeProrationPolicy.GENEROUS_DEFERRED,
        downgrade_proration=DowngradeProrationPolicy.NO_REFUND,
    )

    assert config.upgrade_proration is UpgradeProrationPolicy.GENEROUS_DEFERRED
    assert config.downgrade_proration is DowngradeProrationPolicy.NO_REFUND


def test_immediate_charge_prorates_to_the_day():
    """§3.3's industry default: "prorated charge right away, to the day"."""
    outcome = prorate_upgrade(
        UpgradeProrationPolicy.IMMEDIATE_CHARGE, price_delta_minor=30000, days_remaining=15
    )

    assert outcome.amount_minor == 15000
    assert not outcome.effective_at_cycle_boundary


def test_next_cycle_charges_nothing_now():
    outcome = prorate_upgrade(
        UpgradeProrationPolicy.NEXT_CYCLE, price_delta_minor=30000, days_remaining=15
    )

    assert outcome.amount_minor == 0
    assert outcome.effective_at_cycle_boundary


def test_generous_deferred_charges_nothing_now_and_says_why():
    """§3.3 keeps this specifically for an owner who wants a more generous posture than the
    industry default toward their own company or community."""
    outcome = prorate_upgrade(
        UpgradeProrationPolicy.GENEROUS_DEFERRED, price_delta_minor=30000, days_remaining=2
    )

    assert outcome.amount_minor == 0
    assert "deferred" in outcome.detail


def test_a_refund_is_signed_negative_so_the_two_axes_sum_correctly():
    """A caller summing proration outcomes gets the right answer without knowing which
    direction produced each one."""
    refund = prorate_downgrade(
        DowngradeProrationPolicy.IMMEDIATE_REFUND, price_delta_minor=30000, days_remaining=10
    )

    assert refund.amount_minor == -10000


def test_no_refund_returns_nothing_and_defers_to_the_boundary():
    outcome = prorate_downgrade(
        DowngradeProrationPolicy.NO_REFUND, price_delta_minor=30000, days_remaining=10
    )

    assert outcome.amount_minor == 0
    assert outcome.effective_at_cycle_boundary


def test_a_tier_change_applies_the_configured_upgrade_policy():
    service = configured_service(upgrade_proration=UpgradeProrationPolicy.NEXT_CYCLE)
    subscription = service.create_subscription("user-1", "basic").subscription

    result, proration = service.change_tier(
        subscription.subscription_id, "pro", price_delta_minor=30000
    )

    assert result.ok
    assert result.subscription.tier == "pro"
    assert proration.amount_minor == 0
    assert service.metrics.snapshot().tier_upgrades == 1


def test_changing_to_the_tier_already_held_is_rejected():
    service = configured_service()
    subscription = service.create_subscription("user-1", "pro").subscription

    result, proration = service.change_tier(subscription.subscription_id, "pro")

    assert not result.ok
    assert proration is None


# ------------------------------------------------------------------- charges and status


def test_an_unreachable_provider_yields_unknown_not_failed():
    """Guessing either way costs real money.

    Treating silence as failure would either refund money that was taken or re-charge a card
    that already paid.
    """
    assert run(PayMongoProvider().check_status("ch_1")) is PaymentStatus.UNKNOWN


def test_an_unrecognised_provider_status_is_unknown_rather_than_guessed():
    """A PSP adding a status we have never seen must not be read as success or failure."""

    class Transport:
        def post(self, path, body):
            return {"id": "ch_1", "status": "some_new_state", "amount": 100}

        def get(self, path):
            return {"status": "some_new_state"}

    provider = PayMongoProvider(transport=Transport())

    assert run(provider.check_status("ch_1")) is PaymentStatus.UNKNOWN


def test_an_unconfigured_provider_refuses_a_charge_rather_than_faking_one():
    from core.billing.errors import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        run(UnconfiguredProvider().create_charge(1000, "PHP", "gcash"))


def test_the_two_providers_keep_their_own_status_vocabularies():
    """Xendit says `settled` where PayMongo says `paid`.

    One merged table would quietly accept a status from the wrong provider as valid, which is
    the sort of thing that works fine until the day it does not.
    """
    from core.billing.psp.paymongo_provider import STATUS_MAP as PAYMONGO_MAP
    from core.billing.psp.xendit_provider import STATUS_MAP as XENDIT_MAP

    assert "settled" in XENDIT_MAP
    assert "settled" not in PAYMONGO_MAP


def test_a_zero_or_negative_charge_is_refused():
    from core.billing.errors import ProviderUnavailable

    class Transport:
        def post(self, path, body):
            return {}

        def get(self, path):
            return {}

    provider = PayMongoProvider(transport=Transport())

    with pytest.raises(ProviderUnavailable):
        run(provider.create_charge(0, "PHP", "gcash"))
