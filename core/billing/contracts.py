"""Billing & Subscription data contracts (`v3-deepdive-22-billing-subscription-api.md` §3–§5, §7).

This module holds types and no logic (`docs/PRINCIPLES.md` §1.1). It is the only file in this
package that anything outside `core/billing/` imports from.

Three decisions here carry the weight:

* **`BILLING_DISABLED_BY_DEFAULT` is `True`, and §3.1 calls that "a real correction worth being
  explicit about".** This API existing in an install does not mean tiers are active. The actual
  default for a fresh install is every tier free with no PSP configured at all, and enabling
  paid tiers is something an owner opts into later. A default of "on" would silently gate
  features on a self-hosted install whose owner never asked for billing.
* **Upgrade and downgrade proration are two independent axes** (§3.3), not one shared policy.
  The situations have genuinely different stakes: an upgrade is the owner giving a user
  something; a downgrade is taking something away, and generosity means a different thing in
  each direction.
* **`PENDING_DELETION_HOLD` is a subscription status, not a flag.** Account Guardian's own
  `DeletionStage.BILLING_HOLD` checks against it (§4), so it is a real state this API owns on
  behalf of a cross-API contract the other document specified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict

#: §3.1's resolved default. Billing is entirely optional; a fresh install runs every tier free
#: with no PSP configured until an owner opts in.
BILLING_DISABLED_BY_DEFAULT: bool = True

#: §3's resolved default provider. Both are fully implemented behind one interface; PayMongo
#: leads on transparent public pricing and PH-first simplicity.
DEFAULT_PROVIDER: str = "paymongo"

#: The tier every install starts on, and the only tier that exists when billing is off.
FREE_TIER: str = "free"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SubscriptionStatus(str, Enum):
    """§4's own status list.

    `PENDING_DELETION_HOLD` is the one with a cross-API contract behind it: Account Guardian's
    `DeletionStage.BILLING_HOLD` checks against exactly this value, and §4 is explicit that a
    deletion request "stops new charges immediately ... and the subscription enters this status
    until final invoice/proration/refund resolves". It is not a variant of `CANCELLED` — a
    cancelled subscription is finished, while this one still has money to settle.

    Values are stable wire strings. Adding a member is fine; renaming or reusing one is a
    breaking change to the `.proto` surface and to Account Guardian's own expectations.
    """

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    PENDING_DELETION_HOLD = "pending_deletion_hold"


class UpgradeProrationPolicy(str, Enum):
    """§3.3's upgrade axis, verbatim.

    `GENEROUS_DEFERRED` exists because §3.3 argues a self-hosted owner running this for their
    own company or community "might genuinely want the most generous posture toward their own
    users, not just the industry-standard immediate-proration default" — the same
    owner-decides-their-own-posture principle already applied to 2FA enforcement and session TTL.
    """

    IMMEDIATE_CHARGE = "immediate_charge"
    NEXT_CYCLE = "next_cycle"
    GENEROUS_DEFERRED = "generous_deferred"


class DowngradeProrationPolicy(str, Enum):
    """§3.3's downgrade axis, verbatim and deliberately separate from the upgrade one."""

    IMMEDIATE_REFUND = "immediate_refund"
    CREDIT_NEXT_CYCLE = "credit_next_cycle"
    NO_REFUND = "no_refund"


class PaymentStatus(str, Enum):
    """What a charge is currently doing.

    `UNKNOWN` is distinct from `FAILED` for the same reason it is everywhere else in this repo:
    a PSP that could not be reached has not told us the charge failed, and treating silence as
    failure would either refund money that was taken or re-charge a card that already paid.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BillingConfig:
    """§8's config block, as a real type.

    `enabled=False` is the shipped default (§3.1). Everything else only matters once an owner
    has turned it on, which is why the credentials are plain empty strings rather than a
    required argument — a fresh install must construct this successfully with nothing set.
    """

    enabled: bool = not BILLING_DISABLED_BY_DEFAULT
    provider: str = DEFAULT_PROVIDER
    upgrade_proration: UpgradeProrationPolicy = UpgradeProrationPolicy.IMMEDIATE_CHARGE
    downgrade_proration: DowngradeProrationPolicy = DowngradeProrationPolicy.IMMEDIATE_REFUND
    credentials: FrozenDict = field(default_factory=lambda: FrozenDict({}))

    @property
    def configured(self) -> bool:
        """Enabled *and* carrying a webhook secret for the selected provider.

        Enabled-without-credentials is a real misconfiguration rather than a half-state to
        tolerate: it would gate paid tiers while no charge could ever be taken, so callers
        check this rather than `enabled` alone.
        """
        if not self.enabled:
            return False
        return bool(self.credentials.get(f"{self.provider}_webhook_secret"))


@dataclass(frozen=True)
class Subscription:
    """§4's contract, plus the timestamps the lifecycle needs.

    `tier` is a plain string, not an enum, and that is §1's boundary showing through: this API
    "only tracks which tier a subscription is currently paying for and reports that fact" —
    what a tier unlocks belongs to each consuming API's own config bundle. An enum here would
    make Billing the owner of a taxonomy it explicitly does not own (`docs/PRINCIPLES.md` §3.4).
    """

    subscription_id: str
    user_id: str
    tier: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_end: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def accepts_new_charges(self) -> bool:
        """§4: a deletion hold "stops new charges immediately".

        Derived from the status rather than stored separately so the two cannot disagree — and
        expressed positively so a caller reads "may I charge this" rather than negating a flag.
        """
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)

    @property
    def settles_final_invoice(self) -> bool:
        """Whether a final invoice may still be resolved while on hold (§4).

        The distinction that makes `PENDING_DELETION_HOLD` worth its own status: new charges
        stop, but the money already owed still has to settle before Account Guardian's deletion
        can proceed.
        """
        return self.status is SubscriptionStatus.PENDING_DELETION_HOLD


@dataclass(frozen=True)
class PaymentEvent:
    """One charge, refund or webhook-delivered event (§3's provider interface).

    `raw` carries whatever the PSP sent, as a `FrozenDict` — a webhook payload retained
    unmodified is the only way to reconstruct what actually happened during a dispute, and one
    that could be edited in place afterwards would be worthless for exactly that.
    """

    event_id: str
    provider: str
    charge_id: str
    amount_minor: int
    currency: str
    status: PaymentStatus
    method: str = ""
    occurred_at: datetime = field(default_factory=utcnow)
    raw: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class SubscriptionResult:
    """The outcome of any single-subscription operation.

    Errors are data (`docs/PRINCIPLES.md` §4.1); nothing raises across this API's boundary.
    """

    subscription: Subscription | None = None
    error_code: str = ""
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.subscription is not None and not self.error_code


@dataclass(frozen=True)
class WebhookResult:
    """The outcome of receiving a PSP webhook (§5, §7's `HandleWebhook`).

    `accepted=False` with `verified=False` is the security case §5 exists for, and the two are
    separate fields on purpose: an operator investigating needs to distinguish "we rejected the
    signature" from "the signature was fine but the event was a duplicate".
    """

    accepted: bool
    verified: bool = False
    event: PaymentEvent | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class ProrationOutcome:
    """What a tier change means for money, given the configured policies (§3.3).

    `amount_minor` is signed: positive charges the user, negative refunds or credits them, zero
    means nothing moves now. Minor units (centavos) rather than a float, because a currency
    amount in binary floating point is a rounding bug waiting for a real invoice.
    """

    direction: str
    policy: str
    amount_minor: int = 0
    effective_at_cycle_boundary: bool = False
    detail: str = ""


@dataclass(frozen=True)
class BillingMetrics:
    """This API's own counters, snapshotted (`metrics.py`)."""

    subscriptions_created: int = 0
    subscriptions_cancelled: int = 0
    tier_upgrades: int = 0
    tier_downgrades: int = 0
    deletion_holds_placed: int = 0
    deletion_holds_released: int = 0
    charges_blocked_by_hold: int = 0
    webhooks_accepted: int = 0
    webhooks_rejected_signature: int = 0
    webhooks_rejected_duplicate: int = 0
    provider_unavailable: int = 0


__all__ = [
    "BILLING_DISABLED_BY_DEFAULT",
    "DEFAULT_PROVIDER",
    "FREE_TIER",
    "BillingConfig",
    "BillingMetrics",
    "DowngradeProrationPolicy",
    "PaymentEvent",
    "PaymentStatus",
    "ProrationOutcome",
    "Subscription",
    "SubscriptionResult",
    "SubscriptionStatus",
    "UpgradeProrationPolicy",
    "WebhookResult",
    "utcnow",
]
