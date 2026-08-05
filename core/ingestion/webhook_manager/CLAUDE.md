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

`a01.00.02`

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

- **The register→confirm→deregister ordering is confirmed live against fake adapters,
  not just asserted from the code shape.** A confirmation failure (`ConfirmationFailed`)
  never triggers a deregister call — the old, still-active channel is left untouched,
  exactly the "never open a delivery gap" property this ordering exists to guarantee. A
  registration failure stops before either later step runs.
- **`DriveWebhookAdapter` (in `subscription.py`) and `callback_handler.
  handle_drive_webhook` are NOT live-tested this session** — no real Drive credentials or
  network call was made (same reason `sources/google_drive/`'s own modules aren't
  either). Built directly from the Drive v3 API's own published `watch`/`channels.stop`/
  `changes.list` shapes.
- **`CircadianMonitor`'s delivery-rhythm inference is confirmed live**: a channel that
  never delivered, one that delivered recently, and one that silently stopped delivering
  all produce the correct `needs_fallback_poll()` answer against a real interval,
  matching deep-dive §9's own named required test.

- **This entire sub-API was disconnected from the running service until caught by a
  direct "is every module actually wired in, not just individually tested" audit.**
  Every module above existed and had its own passing tests, but nothing ever
  constructed a subscription store, tracked a Drive Changes API page token across
  calls, or recorded a delivery for Circadian — `core/ingestion/service.py`'s
  `HandleDriveWebhook` RPC acknowledged every callback unconditionally without doing
  anything. Fixed: `manager.py`'s new `WebhookManager` is the real, stateful assembly
  point tying `subscription.py`/`circadian.py`/`callback_handler.py` together;
  `IngestionServicer` now holds one, built from the same shared credential provider as
  `GoogleDriveSource` (`core/ingestion/drive_assembly.py`). Confirmed live: register ->
  handle_callback -> Circadian-recording end to end against fake Drive responses, and
  an unregistered channel correctly rejected. `webhook_renewal_lead_time_hours` is
  stored on `WebhookManager` for a future Background Worker to read (deep-dive §4.1.3's
  own stated owner of the actual renewal *schedule* — this repo has no Background
  Workers API built yet); `fallback_poll_interval_hours` IS enforced right now, via
  `CircadianMonitor`'s own real interval.

## Implementation status

Implemented this session — `contracts.py`, `errors.py`, `subscription.py` (including
`DriveWebhookAdapter`, unverified against real Drive credentials — see above),
`circadian.py`, `callback_handler.py`, `manager.py` (the real assembly point — see the
gotcha above for why it had to be added after the fact). The renewal-ordering, Circadian,
and manager-integration tests are real regression tests, not placeholders.
