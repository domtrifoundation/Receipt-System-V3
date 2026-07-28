# Billing & Subscription API

Billing owns payment/subscription management for **hosted multi-tenant customers only** — tier-profile assignment tied to a paid subscription, GCash/bank-transfer payment via a Philippine payment aggregator. **Worth stating precisely, surfaced during the Setup Sequence walkthrough: "hosted multi-tenant customers only" describes who this API's own default configuration serves, not a restriction on self-hosted installs using the tier system at all.** A self-hosted install can genuinely run `tenancy_mode: multi` too (a company self-hosting for its whole team, per Auth's own Groups design, its deep-dive §7) — and that owner has real, independent choices about tiers that don't route through DOMTRI's own hosted billing at all: run every tier free (no PSP configured, tier gates simply never trigger), or configure this same swappable PSP interface (§3) pointed at their *own* merchant account, running their own internal billing entirely independently of DOMTRI's hosted service. This isn't new scope this API needs to build — it's the direct, already-designed consequence of the swappable-PSP-credential requirement (§3) already being per-install, not hardcoded to one merchant account.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no payment, subscription, or tier concept — it was a single-user local program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

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
