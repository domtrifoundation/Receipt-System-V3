# Billing & Subscription API

Billing owns payment/subscription management for **hosted multi-tenant customers only** — tier-profile assignment tied to a paid subscription, GCash/bank-transfer payment via a Philippine payment aggregator. **Worth stating precisely, surfaced during the Setup Sequence walkthrough: "hosted multi-tenant customers only" describes who this API's own default configuration serves, not a restriction on self-hosted installs using the tier system at all.** A self-hosted install can genuinely run `tenancy_mode: multi` too (a company self-hosting for its whole team, per Auth's own Groups design, its deep-dive §7) — and that owner has real, independent choices about tiers that don't route through DOMTRI's own hosted billing at all: run every tier free (no PSP configured, tier gates simply never trigger), or configure this same swappable PSP interface (§3) pointed at their *own* merchant account, running their own internal billing entirely independently of DOMTRI's hosted service. This isn't new scope this API needs to build — it's the direct, already-designed consequence of the swappable-PSP-credential requirement (§3) already being per-install, not hardcoded to one merchant account.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no payment, subscription, or tier concept — it was a single-user local program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.02`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-22-billing-subscription-api.md`](../../docs/apis/v3-deepdive-22-billing-subscription-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **handle self-hosted licensing** — a real, previously-caught design flaw (file 01): putting license-validation logic inside this API would ship it inside every self-hosted release clone, fully readable and patchable by the person it's meant to validate. Self-hosted licensing is Keymaster, a completely separate, closed external system (Update API's own territory) — genuinely independent of whether that same self-hosted install also runs its own internal tier/billing structure per the paragraph above.
- **take on PCI scope** — both aggregator candidates are tokenizing (card/GCash credentials never touch this system directly), keeping this API firmly out of card-data handling.
- **decide tier-profile *content*** — what a `pro` tier actually unlocks (OCR engine count, inference model tier) is each consuming API's own config bundle (file 03's per-run performance tier decision); Billing only tracks which tier a subscription is currently paying for and reports that fact.
- **force a tier decision during first-run setup** — Setup API's own wizard (its deep-dive §7) only establishes `tenancy_mode` and the owner account; tier/billing configuration (including "should this even use tiers at all") is a separate, later admin action through this API's own onboarding, not crammed into first boot.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Self-hosted licensing is deliberately *not* here. Putting license validation inside this API would ship it inside every self-hosted release clone, on the exact machine it is meant to check, fully readable and patchable by the person it validates — a check that is not a check. That is Keymaster, a separate closed system.

**Billing is off by default, and that is the ordinary state rather than an edge case** (§3.1).
A fresh install runs every tier free with no PSP configured; `BillingNotConfigured` is what a
correct install looks like before an owner opts in. Any code path treating it as a failure
breaks the common case rather than an exceptional one. `BillingConfig.configured` exists because
enabled-without-credentials is a real misconfiguration — it would gate paid tiers while no
charge could ever be taken — so callers check that rather than `enabled` alone. What billing
being off removes is *charging*, not the concept of a tier: subscription creation still works,
because §1 explicitly supports an owner running every tier free indefinitely.

**Webhook verification is the one place this package fails closed hard** (§5), and the deep-dive
is blunt about why: an unverified endpoint means "anyone who discovers the URL could fake a
'payment succeeded' event". So verification runs first with no path around it, signatures are
compared in constant time (`hmac.compare_digest` — a byte-by-byte `==` leaks the correct
signature one character at a time to anyone who can call the endpoint repeatedly), a verifier
that raises counts as unverified, and an install with no webhook secret verifies nothing rather
than skipping the check. **Duplicate detection deliberately runs after verification**: an
unsigned duplicate is still an unsigned payload, and reporting it as a duplicate would tell
someone probing the endpoint which event ids exist. The two rejections stay distinct in metrics
for the same reason — duplicates are every PSP's normal retry behaviour, signature failures are
someone probing.

**`PENDING_DELETION_HOLD` is a status this API owns on behalf of a contract Account Guardian's
document specified** (§4). New charges stop immediately while the final invoice still settles,
which is exactly why it is not a variant of `CANCELLED` — a cancelled subscription is finished,
this one still has money to resolve. Releasing the hold lands in `CANCELLED`, never back in
`ACTIVE`: the user asked to be deleted, and reactivating a paid subscription after settling
would start charging them again. Account Guardian polls `billing_resolved()` rather than reading
the enum, so renaming a status member cannot silently change when deletions proceed.

**Upgrade and downgrade proration are two independent axes** (§3.3), not one policy. An upgrade
gives the user something; a downgrade takes something away, and generosity means a different
thing in each direction. `GENEROUS_DEFERRED` and `IMMEDIATE_REFUND` exist because a self-hosted
owner running this for their own company or community may want a more generous posture than the
industry default — the same owner-decides-their-own-posture principle applied to 2FA enforcement
and session TTL. Amounts are signed minor units: negative means owed back, so a caller summing
outcomes gets the right answer without knowing which direction produced each one. Minor units
rather than a decimal because a currency amount in binary floating point is a rounding bug
waiting for a real invoice.

**Both PSPs are real** (§3 resolves the either/or explicitly). Implementing only the default
would make "never requiring a rewrite to switch" false the moment anyone tried. They keep
*separate* status vocabularies — Xendit says `settled` where PayMongo says `paid` — because one
merged table would quietly accept a status from the wrong provider as valid. An unrecognised
status is `UNKNOWN`, never guessed: an unreachable PSP treated as a failed charge would either
refund money that was taken or re-charge a card that already paid.

**Credentials are per-instance, never module globals.** §3's requirement is architectural: a
hardcoded merchant account would route every self-hosted buyer's payments through the reference
deployment's own account. A module-level secret would violate that silently.

**Files here that the deep-dive's §2 package layout does not list**: none — every module matches
§2, and `psp/base.py` holds the Provider Registry §3 asks for.

**The `.proto` gap this section used to describe is now closed.** `billing.proto` defines
the four RPCs the deep-dive names (`CreateSubscription`/`CancelSubscription`/
`GetSubscriptionStatus`/`HandleWebhook`), and `service.py`'s `BillingServicer` wires the
real `SubscriptionService` to all four — it never executes a charge, transfer, or refund
itself; that stays each PSP provider's own job behind `psp/base.py`. Confirmed live: a
real subscription created and returned as `active`; a missing-tier request rejected; a
status lookup on both a real and an unknown subscription id; a cancellation moving to
`cancelled`/`free`; and a webhook call against a fresh, unconfigured (billing-off-by-
default) instance correctly failing closed rather than accepting an unverifiable payload.

**`SubscriptionService` still keeps subscriptions in memory rather than in its own
store** — that half of the original "Known gaps" note is real and unchanged; only the
wire translation was built this pass. A future session's persistence-adapter work should
follow the same shape `core/task_scheduler/store.py` already established for a per-user
Persistence-backed table, not a second in-package SQLite wrapper.
