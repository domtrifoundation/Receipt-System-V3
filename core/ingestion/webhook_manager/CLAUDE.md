# Webhook Subscription Manager

**Sub-API of Ingestion API** (`core/ingestion/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Webhook Subscription Manager owns **generic, provider-agnostic push-notification subscription handling** — registering, renewing, and receiving callbacks for any push-capable source (Drive today, OneDrive/Microsoft Graph or others later via a different provider adapter).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's Drive ingestion was OAuth plus folder-ID polling with no push notifications at all — confirmed in `docs/apis/v3-plan-04-v2-audit-findings.md`. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-35-webhook-subscription-manager.md`](../../../docs/apis/v3-deepdive-35-webhook-subscription-manager.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide run boundaries** — emits a "new file available" event per changed item; Execution Core's own debounce-coalescing logic (its deep-dive §5.2) decides how those events batch into an actual run.
- **care which Drive credential strategy is active** — already designed provider-agnostic with respect to service-account-vs-OAuth (Ingestion deep-dive §4.1.2's own note), a genuine, confirmed design property, not just an aspiration.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Renewal creates a *new* channel ID rather than extending the old one, so the only safe order is register-new → confirm-active → deregister-old. Stop-then-start opens a real delivery gap. "Webhook Circadian" is the name for inferring a third party's delivery rhythm is healthy from timing alone — deliberately distinct from Watchdog, which proves our own process is alive. There is no ping endpoint to call for these providers; that is why the mechanism is shaped this way.
