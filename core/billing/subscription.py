"""Tier assignment, renewal, cancellation, and the Account Guardian hold (§3.3, §4, §5).

Three things live here and nothing else does:

* **The subscription lifecycle**, including `PENDING_DELETION_HOLD` — §4's cross-API contract
  with Account Guardian's `DeletionStage.BILLING_HOLD`. A deletion request "stops new charges
  immediately ... and the subscription enters this status until final invoice/proration/refund
  resolves, at which point Billing reports clean resolution back and Account Guardian's deletion
  flow proceeds." That state is this API's to own; the other document only specified it.
* **Proration**, as §3.3's two independent axes. Upgrade and downgrade are configured
  separately because "an upgrade is the owner giving the user something; a downgrade or
  cancellation is taking something away, and generosity in each direction means something
  different."
* **Webhook admission**, which is where §5's security requirement is actually enforced.

**Billing is off by default and that is not an edge case** (§3.1). A fresh install runs every
tier free with no PSP configured, so `BillingNotConfigured` is the ordinary state, not a
failure — every method here has to behave sensibly in it rather than treating it as broken.

**This API never decides what a tier unlocks** (§1): it tracks which tier is being paid for and
reports that fact. `tier` is a plain string for exactly that reason — an enum here would make
Billing the owner of a taxonomy it explicitly does not own (`docs/PRINCIPLES.md` §3.4).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from .contracts import (
    FREE_TIER,
    BillingConfig,
    DowngradeProrationPolicy,
    PaymentEvent,
    ProrationOutcome,
    Subscription,
    SubscriptionResult,
    SubscriptionStatus,
    UpgradeProrationPolicy,
    WebhookResult,
    utcnow,
)
from .errors import (
    BillingError,
    ChargesBlockedByDeletionHold,
    DuplicateWebhookEvent,
    InvalidTierChange,
    UnknownSubscription,
    WebhookSignatureInvalid,
    code_for,
)
from .metrics import BillingMetricsCollector
from .psp.base import PaymentProvider, ProviderRegistry, UnconfiguredProvider

#: A billing cycle. One month is what every tier in this project's own pricing is quoted at;
#: 30 days rather than calendar-month arithmetic keeps proration a simple day count, which is
#: what §3.3's `IMMEDIATE_CHARGE` ("prorated charge right away, to the day") actually needs.
CYCLE = timedelta(days=30)


def new_subscription_id() -> str:
    return f"sub_{uuid.uuid4().hex[:16]}"


def prorate_upgrade(
    policy: UpgradeProrationPolicy,
    *,
    price_delta_minor: int,
    days_remaining: int,
    cycle_days: int = CYCLE.days,
) -> ProrationOutcome:
    """What an upgrade costs now, under `policy` (§3.3).

    The three policies genuinely differ in *when* money moves, not merely how much:

    * `IMMEDIATE_CHARGE` — the industry default, charged to the day.
    * `NEXT_CYCLE` — benefits now, charged from the next boundary. Nothing moves today.
    * `GENEROUS_DEFERRED` — benefits now and the charge deferred past the *next* full cycle, so
      a user upgrading near a boundary gets the rest of this cycle plus all of the next before
      paying anything. §3.3 keeps this specifically for an owner running the system for their
      own company or community who wants a more generous posture than the industry default.
    """
    if policy is UpgradeProrationPolicy.IMMEDIATE_CHARGE:
        amount = round(price_delta_minor * max(days_remaining, 0) / max(cycle_days, 1))
        return ProrationOutcome(
            direction="upgrade",
            policy=policy.value,
            amount_minor=amount,
            detail=f"prorated for {days_remaining} of {cycle_days} days",
        )
    if policy is UpgradeProrationPolicy.NEXT_CYCLE:
        return ProrationOutcome(
            direction="upgrade",
            policy=policy.value,
            amount_minor=0,
            effective_at_cycle_boundary=True,
            detail="benefits apply now, billed from the next cycle",
        )
    return ProrationOutcome(
        direction="upgrade",
        policy=policy.value,
        amount_minor=0,
        effective_at_cycle_boundary=True,
        detail="benefits apply now, charge deferred until after the next full cycle",
    )


def prorate_downgrade(
    policy: DowngradeProrationPolicy,
    *,
    price_delta_minor: int,
    days_remaining: int,
    cycle_days: int = CYCLE.days,
) -> ProrationOutcome:
    """What a downgrade returns, under `policy` (§3.3).

    Amounts are negative for anything owed back to the user, which is what makes the sign
    meaningful across both axes: a caller summing proration outcomes gets the right answer
    without knowing which direction produced each one.
    """
    unused = round(price_delta_minor * max(days_remaining, 0) / max(cycle_days, 1))
    if policy is DowngradeProrationPolicy.IMMEDIATE_REFUND:
        return ProrationOutcome(
            direction="downgrade",
            policy=policy.value,
            amount_minor=-unused,
            detail=f"refunding {days_remaining} unused days",
        )
    if policy is DowngradeProrationPolicy.CREDIT_NEXT_CYCLE:
        return ProrationOutcome(
            direction="downgrade",
            policy=policy.value,
            amount_minor=-unused,
            effective_at_cycle_boundary=True,
            detail="credited toward the next cycle rather than refunded",
        )
    return ProrationOutcome(
        direction="downgrade",
        policy=policy.value,
        amount_minor=0,
        effective_at_cycle_boundary=True,
        detail="takes effect at the next cycle boundary, no refund for the remainder",
    )


class SubscriptionService:
    """Subscription state, proration, and webhook admission. One instance per Billing process."""

    def __init__(
        self,
        config: BillingConfig | None = None,
        *,
        providers: ProviderRegistry | None = None,
        metrics: BillingMetricsCollector | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._config = config or BillingConfig()
        self._providers = providers or ProviderRegistry()
        self._metrics = metrics or BillingMetricsCollector()
        self._now = now
        self._lock = threading.Lock()
        self._subscriptions: dict[str, Subscription] = {}
        self._seen_events: set[str] = set()

    @property
    def config(self) -> BillingConfig:
        return self._config

    @property
    def metrics(self) -> BillingMetricsCollector:
        return self._metrics

    def provider(self) -> PaymentProvider:
        """The configured provider, or `UnconfiguredProvider` when billing is off (§3.1)."""
        if not self._config.enabled:
            return UnconfiguredProvider()
        return self._providers.get(self._config.provider)

    # ------------------------------------------------------------------------ lifecycle

    def create_subscription(self, user_id: str, tier: str) -> SubscriptionResult:
        """Start a subscription at `tier`.

        Works with billing disabled, deliberately: §3.1's default install runs every tier free,
        and a self-hosted owner still wants tier *assignment* to mean something even with no
        PSP configured. What billing being off removes is charging, not the concept of a tier.
        """
        if not user_id or not tier:
            exc = InvalidTierChange("a subscription needs a user and a tier")
            return SubscriptionResult(error_code=code_for(exc), error_detail=str(exc))

        now = self._now()
        subscription = Subscription(
            subscription_id=new_subscription_id(),
            user_id=user_id,
            tier=tier,
            status=SubscriptionStatus.ACTIVE,
            current_period_end=now + CYCLE,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._subscriptions[subscription.subscription_id] = subscription
        self._metrics.increment("subscriptions_created")
        return SubscriptionResult(subscription=subscription)

    def get(self, subscription_id: str) -> Subscription | None:
        with self._lock:
            return self._subscriptions.get(subscription_id)

    def _require(self, subscription_id: str) -> Subscription:
        found = self.get(subscription_id)
        if found is None:
            raise UnknownSubscription(subscription_id)
        return found

    def change_tier(self, subscription_id: str, new_tier: str, *, price_delta_minor: int = 0):
        """Move a subscription between tiers, applying §3.3's configured proration.

        Returns `(SubscriptionResult, ProrationOutcome | None)`. The proration is returned rather
        than acted on here: charging or refunding is the provider's job, and a method that did
        both would make the policy untestable without a live PSP.
        """
        try:
            subscription = self._require(subscription_id)
            if not new_tier or new_tier == subscription.tier:
                raise InvalidTierChange(f"{new_tier!r} is not a change from the current tier")
            if not subscription.accepts_new_charges:
                raise ChargesBlockedByDeletionHold(subscription_id)
        except BillingError as exc:
            if isinstance(exc, ChargesBlockedByDeletionHold):
                self._metrics.increment("charges_blocked_by_hold")
            return SubscriptionResult(error_code=code_for(exc), error_detail=str(exc)), None

        days_remaining = self._days_remaining(subscription)
        upgrading = price_delta_minor > 0
        if upgrading:
            outcome = prorate_upgrade(
                self._config.upgrade_proration,
                price_delta_minor=price_delta_minor,
                days_remaining=days_remaining,
            )
            self._metrics.increment("tier_upgrades")
        else:
            outcome = prorate_downgrade(
                self._config.downgrade_proration,
                price_delta_minor=abs(price_delta_minor),
                days_remaining=days_remaining,
            )
            self._metrics.increment("tier_downgrades")

        updated = self._replace(subscription, tier=new_tier)
        with self._lock:
            self._subscriptions[subscription_id] = updated
        return SubscriptionResult(subscription=updated), outcome

    def cancel_subscription(self, subscription_id: str) -> SubscriptionResult:
        try:
            subscription = self._require(subscription_id)
        except BillingError as exc:
            return SubscriptionResult(error_code=code_for(exc), error_detail=str(exc))

        updated = self._replace(
            subscription, status=SubscriptionStatus.CANCELLED, tier=FREE_TIER
        )
        with self._lock:
            self._subscriptions[subscription_id] = updated
        self._metrics.increment("subscriptions_cancelled")
        return SubscriptionResult(subscription=updated)

    # ---------------------------------------------------- §4's Account Guardian contract

    def place_deletion_hold(self, subscription_id: str) -> SubscriptionResult:
        """Stop new charges immediately, pending final settlement (§4).

        Called by Account Guardian when a deletion request is filed. The subscription is not
        cancelled — money may still be owed, and §4 requires that final invoice to resolve
        before deletion proceeds. Cancelling here would lose that obligation.
        """
        try:
            subscription = self._require(subscription_id)
        except BillingError as exc:
            return SubscriptionResult(error_code=code_for(exc), error_detail=str(exc))

        updated = self._replace(subscription, status=SubscriptionStatus.PENDING_DELETION_HOLD)
        with self._lock:
            self._subscriptions[subscription_id] = updated
        self._metrics.increment("deletion_holds_placed")
        return SubscriptionResult(subscription=updated)

    def release_deletion_hold(self, subscription_id: str) -> SubscriptionResult:
        """Report clean resolution back to Account Guardian (§4).

        The subscription lands in `CANCELLED` rather than back in `ACTIVE`: the hold exists
        because the user asked to be deleted, and returning them to an active paid subscription
        after settling the final invoice would start charging them again.
        """
        try:
            subscription = self._require(subscription_id)
        except BillingError as exc:
            return SubscriptionResult(error_code=code_for(exc), error_detail=str(exc))

        updated = self._replace(
            subscription, status=SubscriptionStatus.CANCELLED, tier=FREE_TIER
        )
        with self._lock:
            self._subscriptions[subscription_id] = updated
        self._metrics.increment("deletion_holds_released")
        return SubscriptionResult(subscription=updated)

    def billing_resolved(self, subscription_id: str) -> bool:
        """What Account Guardian's `BILLING_HOLD` stage actually polls (§4).

        True once nothing is outstanding — which for this build means the hold was released.
        Exposed as its own method rather than leaving Account Guardian to read the status
        directly, so the cross-API contract is one call rather than a shared understanding of
        an enum.
        """
        found = self.get(subscription_id)
        if found is None:
            return False
        return found.status is not SubscriptionStatus.PENDING_DELETION_HOLD

    # ------------------------------------------------------------------ §5's webhooks

    async def handle_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        """Verify, then admit (§5).

        Verification comes first and there is no path around it. §5: "an unverified webhook
        endpoint is a real, exploitable surface (anyone who discovers the URL could fake a
        'payment succeeded' event without this check)."

        Duplicate detection sits *after* verification on purpose: an unsigned duplicate is still
        an unsigned payload, and reporting it as a duplicate would tell an attacker probing the
        endpoint which event ids exist.
        """
        provider = self.provider()
        try:
            verified = await provider.verify_webhook(payload, signature)
        except Exception:  # noqa: BLE001 - an erroring verifier has not verified anything
            verified = False

        if not verified:
            self._metrics.increment("webhooks_rejected_signature")
            exc = WebhookSignatureInvalid("payload signature did not verify")
            return WebhookResult(
                accepted=False, verified=False, error_code=code_for(exc), error_detail=str(exc)
            )

        event_id = self._event_id_from(payload)
        with self._lock:
            duplicate = event_id in self._seen_events
            if not duplicate:
                self._seen_events.add(event_id)
        if duplicate:
            self._metrics.increment("webhooks_rejected_duplicate")
            exc = DuplicateWebhookEvent(event_id)
            return WebhookResult(
                accepted=False, verified=True, error_code=code_for(exc), error_detail=str(exc)
            )

        self._metrics.increment("webhooks_accepted")
        return WebhookResult(accepted=True, verified=True)

    @staticmethod
    def _event_id_from(payload: bytes) -> str:
        """A stable identity for a verified payload.

        Hashing the payload rather than trusting an `id` field inside it: a PSP retrying
        delivery sends byte-identical content, which is exactly what should be deduplicated,
        and it needs no assumption about either provider's own JSON shape.
        """
        import hashlib

        return hashlib.sha256(payload).hexdigest()

    # ---------------------------------------------------------------------- internals

    def _days_remaining(self, subscription: Subscription) -> int:
        if subscription.current_period_end is None:
            return 0
        remaining = (subscription.current_period_end - self._now()).days
        return max(remaining, 0)

    def _replace(self, subscription: Subscription, **changes) -> Subscription:
        return Subscription(
            subscription_id=subscription.subscription_id,
            user_id=subscription.user_id,
            tier=changes.get("tier", subscription.tier),
            status=changes.get("status", subscription.status),
            current_period_end=changes.get(
                "current_period_end", subscription.current_period_end
            ),
            created_at=subscription.created_at,
            updated_at=self._now(),
        )


__all__ = [
    "CYCLE",
    "SubscriptionService",
    "new_subscription_id",
    "prorate_downgrade",
    "prorate_upgrade",
]
