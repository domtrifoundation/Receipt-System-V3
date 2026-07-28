# V3 Deep Dive: Billing & Subscription API

**Companion files:** `v3-deepdive-06-account-guardian-api.md` (the `BILLING_HOLD` deletion-stage interaction, §6.3 there), `v3-deepdive-11-setup-api.md` §7.3 (the optional guided-setup step for owners who want billing configured during first-run).

**Status:** Twenty-second deep-dive session.

---

## 1. Scope & boundary

Billing owns payment/subscription management for **hosted multi-tenant customers only** — tier-profile assignment tied to a paid subscription, GCash/bank-transfer payment via a Philippine payment aggregator. **Worth stating precisely, surfaced during the Setup Sequence walkthrough: "hosted multi-tenant customers only" describes who this API's own default configuration serves, not a restriction on self-hosted installs using the tier system at all.** A self-hosted install can genuinely run `tenancy_mode: multi` too (a company self-hosting for its whole team, per Auth's own Groups design, its deep-dive §7) — and that owner has real, independent choices about tiers that don't route through DOMTRI's own hosted billing at all: run every tier free (no PSP configured, tier gates simply never trigger), or configure this same swappable PSP interface (§3) pointed at their *own* merchant account, running their own internal billing entirely independently of DOMTRI's hosted service. This isn't new scope this API needs to build — it's the direct, already-designed consequence of the swappable-PSP-credential requirement (§3) already being per-install, not hardcoded to one merchant account. It does not:
- **handle self-hosted licensing** — a real, previously-caught design flaw (file 01): putting license-validation logic inside this API would ship it inside every self-hosted release clone, fully readable and patchable by the person it's meant to validate. Self-hosted licensing is Keymaster, a completely separate, closed external system (Update API's own territory) — genuinely independent of whether that same self-hosted install also runs its own internal tier/billing structure per the paragraph above.
- **take on PCI scope** — both aggregator candidates are tokenizing (card/GCash credentials never touch this system directly), keeping this API firmly out of card-data handling.
- **decide tier-profile *content*** — what a `pro` tier actually unlocks (OCR engine count, inference model tier) is each consuming API's own config bundle (file 03's per-run performance tier decision); Billing only tracks which tier a subscription is currently paying for and reports that fact.
- **force a tier decision during first-run setup** — Setup API's own wizard (its deep-dive §7) only establishes `tenancy_mode` and the owner account; tier/billing configuration (including "should this even use tiers at all") is a separate, later admin action through this API's own onboarding, not crammed into first boot.

---

## 2. Package layout

```
core/billing/
  __init__.py
  contracts.py            # Subscription, PaymentEvent, error types
  psp/
    __init__.py
    base.py                   # PaymentProvider protocol — swappable, see §3
    paymongo_provider.py
    xendit_provider.py
  subscription.py               # tier assignment, renewal, cancellation
  errors.py
  metrics.py
```

---

## 3. Swappable PSP interface — resolved with real direction: both providers, default PayMongo, billing off by default
File 03 already states the architectural requirement regardless of which aggregator wins: PSP credentials must be per-install config, never hardcoded to one merchant account (or self-hosted buyers would route payments through the reference deployment's own account), and this API is built against a small internal payment-provider interface (verify webhook, create charge, check status) so the PSP is swappable — the same pattern already applied to Ingestion's Drive credential strategy and Notifications' outbound channels.
```python
class PaymentProvider(Protocol):
    async def create_charge(self, amount: int, currency: str, method: str) -> PaymentEvent: ...
    async def verify_webhook(self, payload: bytes, signature: str) -> bool: ...
    async def check_status(self, charge_id: str) -> str: ...
```
**Resolved: both `PayMongoProvider` and `XenditProvider` are real, concrete implementations — not a deferred either/or.** PayMongo is the default (transparent public pricing, PH-first simplicity, faster solo-dev integration — the same reasoning file 03 already laid out); Xendit remains genuinely available behind the identical interface for an owner who wants it (broader SEA reach, built-in recurring billing/disbursement), never requiring a rewrite to switch.

### 3.1 The true default is "off" — billing is an entirely optional feature, not assumed-on
**A real correction worth being explicit about**: this API's own existence in an install doesn't mean tiers/billing are active. The actual default state for a fresh install, before any owner configuration, is every tier free and no PSP configured at all — consistent with Setup API's own already-corrected first-run wizard (its deep-dive §7, "no forced tier selection") and Billing's own scope correction (§1) that self-hosted owners can run everything free indefinitely. Configuring a PSP and enabling paid tiers is something an owner opts into later, through this API's own admin onboarding (§3.2) — not a step the system assumes every install eventually takes.

### 3.2 Easy owner configuration — a real settings surface, and a genuine step inside Setup's own guided wizard
A dedicated TUI/webapp settings screen (`MenuItemSpec`-driven, the same declarative pattern as every other settings entry, `v3-deepdive-14-interface-api.md` §3) lets an owner pick a provider, enter credentials, and enable specific tiers — no code change, no redeploy, a config action through the normal admin surface. **Genuinely offered as one of the optional steps inside Setup API's own first-run wizard** (`v3-deepdive-11-setup-api.md` §7.3, for `multi`-tenant installs specifically) for an owner going through initial setup who already knows they want paid tiers — skippable like every other wizard step, with the same settings entry remaining available anytime an owner decides to configure it later instead.

### 3.3 Proration policy — resolved, two independent axes, four real options each
**Upgrade and downgrade proration are independently configurable, not one shared policy governing both directions** — a real, deliberate richness given the two situations have genuinely different stakes (an upgrade is the owner giving the user something; a downgrade or cancellation is taking something away, and generosity in each direction means something different).
```python
class UpgradeProrationPolicy(str, Enum):
    IMMEDIATE_CHARGE = "immediate_charge"        # prorated charge right away, to the day
    NEXT_CYCLE = "next_cycle"                       # new tier's benefits apply now, billed starting the next cycle boundary — no immediate charge
    GENEROUS_DEFERRED = "generous_deferred"           # new tier's benefits apply immediately; the charge itself is deferred until AFTER the next full cycle completes — a user upgrading near the end of a cycle effectively gets the rest of this cycle plus all of the next one before paying anything extra

class DowngradeProrationPolicy(str, Enum):
    IMMEDIATE_REFUND = "immediate_refund"           # prorated refund processed right away
    CREDIT_NEXT_CYCLE = "credit_next_cycle"            # credited toward the next billing cycle rather than refunded directly
    NO_REFUND = "no_refund"                              # takes effect at the next cycle boundary, no refund for the unused remainder of the current one
```
**Owner-configurable, same two entry points as everything else in this batch**: during Setup's own first-run wizard if billing is being configured at all (`v3-deepdive-11-setup-api.md` §7.3), or anytime afterward through the same settings screen §3.2 already establishes — never a one-time, locked-in-at-setup choice. `GENEROUS_DEFERRED` and `IMMEDIATE_REFUND` are real, available options precisely because a self-hosted owner running this for their own company or community might genuinely want the most generous posture toward their own users, not just the industry-standard immediate-proration default — the same "the owner decides their own risk/generosity posture" principle already applied to 2FA enforcement and session TTL.

---

## 4. Subscription lifecycle and the Account Guardian interaction
```python
@dataclass(frozen=True)
class Subscription:
    subscription_id: str
    user_id: str
    tier: str
    status: Literal["active", "past_due", "cancelled", "pending_deletion_hold"]
    current_period_end: datetime
```
`pending_deletion_hold` is the status Account Guardian's own `DeletionStage.BILLING_HOLD` (its deep-dive §6.3) actually checks against — a deletion request stops new charges immediately (this API's own responsibility, called by Account Guardian) and the subscription enters this status until final invoice/proration/refund resolves, at which point Billing reports clean resolution back and Account Guardian's deletion flow proceeds. This is the concrete implementation of a cross-API contract that document specified but this one owns the actual state for.

---

## 5. Webhook verification — a real security requirement, not a formality
Every PSP webhook (payment confirmation, subscription renewal) must be signature-verified before being trusted (`verify_webhook()` in the provider interface) — an unverified webhook endpoint is a real, exploitable surface (anyone who discovers the URL could fake a "payment succeeded" event without this check), not a theoretical concern.

---

## 6. Asyncio
PSP API/webhook calls are network I/O — file 02's own table already classifies this API as async for exactly this reason, no compute-bound work of its own.

---

## 7. gRPC surface

```protobuf
service BillingService {
  rpc CreateSubscription(CreateSubRequest) returns (SubscriptionResponse);
  rpc CancelSubscription(CancelSubRequest) returns (SubscriptionResponse);
  rpc GetSubscriptionStatus(StatusRequest) returns (SubscriptionResponse);
  rpc HandleWebhook(WebhookPayload) returns (WebhookAck);
}
```

---

## 8. Config

```
billing:
  enabled: false                # true default — every tier free, no PSP configured, until an owner opts in, see §3.1
  provider: paymongo              # paymongo | xendit — default resolved, both fully implemented, see §3
  paymongo:
    secret_key: ""
    webhook_secret: ""
  xendit:
    secret_key: ""
    webhook_secret: ""
  proration:
    upgrade: immediate_charge         # immediate_charge | next_cycle | generous_deferred — see §3.3
    downgrade: immediate_refund         # immediate_refund | credit_next_cycle | no_refund — see §3.3
```

---

## 9. Testing hooks
- **Webhook signature rejection test**: an unsigned or incorrectly-signed webhook payload is rejected, never processed as a real event — direct validation of §5's hard requirement.
- **Deletion-hold state transition test**: confirms `pending_deletion_hold` correctly blocks new charges immediately while allowing final invoice resolution, matching Account Guardian's own `BILLING_HOLD` expectations exactly.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- (PayMongo vs. Xendit — resolved, no longer open. Both fully implemented behind the same `PaymentProvider` interface, PayMongo as the default. Billing itself defaults to entirely off — full design in §3.)
- (Proration policy on mid-cycle tier changes or cancellations — resolved, no longer open. Two independent axes, owner-configurable during Setup or in settings — full design in §3.3.)
