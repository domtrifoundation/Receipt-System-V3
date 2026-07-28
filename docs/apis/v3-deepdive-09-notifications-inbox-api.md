# V3 Deep Dive: Notifications/Inbox API

**Companion files:** all prior deep-dives, especially `v3-deepdive-05-auth-tenancy-api.md` (break-glass is this API's clearest existing consumer) and `v3-deepdive-06-account-guardian-api.md` (deletion/export completion signals).

**Status:** Ninth deep-dive session. Genuinely new territory — file 00's audit confirmed no V2 notification mechanism existed at all, not even a primitive one, so like Auth/Account Guardian this is derived fresh rather than reacting to a V2 failure mode.

---

## 1. Scope & boundary

Notifications/Inbox owns delivering a signal to a user (owner, staff, or client) that something happened — currently in-app only, with outbound channels (email, SMS) as this deep-dive's actual design task per file 01's own framing. It does not:
- **decide what's worth notifying about** — every consumer (Auth's break-glass, Execution Core's run completion, Content Security's rejection, Account Guardian's export/deletion completion, **Review/Flagging's new-flag creation** — `v3-deepdive-25-review-flagging-api.md` §5, a real connection that had only ever been stated from that document's own side until a full pipeline walkthrough found it never actually listed here) decides *when* to notify; this API decides *how* the notification actually reaches the person.
- **own the underlying event** — a notification references what happened (a break-glass grant, a completed run), it doesn't duplicate that event's own record. Auth's `BreakGlassGrant`, Execution Core's run record, and so on remain the source of truth; a `Notification` carries a reference, not a copy.

---

## 2. Package layout

```
core/notifications/
  __init__.py
  contracts.py           # Notification, NotificationChannel, DeliveryStatus, error types
  service.py                # thin gRPC service implementation
  inbox.py                    # in-app inbox storage/read-status — the only channel actually built today
  channels/
    __init__.py
    base.py                    # OutboundChannel protocol
    email_channel.py             # swappable provider behind this — see §4
    sms_channel.py                 # swappable provider behind this — see §4
  preferences.py              # per-user channel opt-in/opt-out, see §5
  errors.py
  metrics.py
```

---

## 3. In-app inbox — the one channel that's fully designed today

```python
@dataclass(frozen=True)
class Notification:
    notification_id: str
    user_id: str
    category: str                # "break_glass", "run_complete", "run_error", "export_ready", "deletion_grace_period", ...
    title: str
    body: str
    reference: str | None          # e.g. a break_glass grant_id, a run_id — links back to the source event, not duplicated data
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```
Storage lives in each user's own Persistence database (a `notifications` table) — unlike Auth/Audit's cross-user infrastructure, a notification genuinely belongs to one specific user and fits Persistence's existing per-user folder/repo isolation model cleanly, no separate top-level database needed here. Owner/staff-directed notifications (break-glass alerts to the owner) are the one exception worth naming — the owner's own account has its own Persistence database like any user, so an owner notification is still "one user's data," just that user happens to be the owner.

---

## 4. Outbound channels — the actual design work, built as swappable providers

### 4.1 Why this needs a real design, not just "add email later"
A client not actively looking at the app needs a way to learn "your run finished" or "your export is ready" without opening it — the in-app inbox alone doesn't reach someone who isn't currently in the app. **Decision: `OutboundChannel` is a Provider Registry interface** (same pattern as every other swappable external dependency in this project), with email and SMS as two initial channel types, each with a swappable underlying provider:
```python
class OutboundChannel(Protocol):
    async def send(self, user_id: str, notification: Notification) -> DeliveryStatus: ...
```

### 4.2 Email — Postmark is the reasoned pick for this specific workload, not SendGrid
This project's actual email need is **pure transactional** (run-complete alerts, export-ready links, deletion-grace-period reminders) — no marketing/broadcast email at all. Current comparisons are consistent on this exact split: Postmark's transactional/broadcast infrastructure separation (Message Streams) gives it a real deliverability edge specifically for transactional mail at this project's likely volume (well under the ~50K/month threshold where SendGrid's pricing advantage would start to matter), and its API/docs are noted as simpler for exactly the "send one clean transactional email" case this project needs, without SendGrid's marketing-platform surface area being relevant here at all. **Reasoned pick: Postmark as the default provider**, behind the swappable interface so switching is a config change, not a rewrite — consistent with the swappable-adapter discipline already applied everywhere else (Billing's PSP interface, Ingestion's Drive credential strategy).

### 4.3 SMS — resolved: all three providers, genuinely swappable, off by default with a real guided setup flow
**All three ship as real, concrete `SmsProvider` implementations** — Semaphore, PhilSMS, and Twilio, each behind the identical `OutboundChannel` interface, matching this project's own modularity principle rather than picking one winner. **Off by default**, consistent with every other real-cost, opt-in capability in this project (Billing, Tunnel Exposure) — SMS costs real money per message, and silently enabling it for a fresh install would mean surprise charges nobody explicitly asked for.

```python
class SmsProvider(Protocol):
    async def send_sms(self, to: str, message: str) -> DeliveryStatus: ...
    async def is_configured(self) -> bool: ...
```

**A real, provider-specific guided setup flow — not just a bare config form**, since these three genuinely have different real-world setup requirements a generic "enter your API key" form would get wrong:
- **Semaphore / PhilSMS** (PH-specific providers): the guide walks through account creation, API key entry, *and* **sender name registration** — a real, distinct step these PH-market providers require that Twilio doesn't, since PH telco networks (Globe/Smart/Sun) generally need a registered sender ID for SMS to actually deliver reliably rather than being filtered as spam. Skipping this step is exactly the kind of thing that would leave an owner with SMS "configured" but not actually working.
- **Twilio**: the guide walks through account SID, auth token, and phone-number provisioning — a genuinely simpler, more familiar flow for anyone who's used Twilio before.

**Available in two places, both calling the identical setup logic**: as a real, skippable step in Setup's own first-run wizard (`v3-deepdive-11-setup-api.md` §7, alongside Tunnel Exposure and Billing's own guided steps, for `multi`-tenant installs) — and as a persistent settings-menu entry (Notifications' own `MenuItemSpec`) reachable anytime after initial setup, the same two-entry-point pattern already established for run-on-startup (Setup deep-dive §7.1) — a wizard offer for the common case, a real persistent home for changing it later.

---

## 5. Per-user channel preferences
```python
@dataclass(frozen=True)
class ChannelPreference:
    user_id: str
    channel: str                  # "email" | "sms"
    enabled: bool
    contact_override: str | None   # e.g. a different notification email than the account's SSO email, if ever supported
```
Outbound channels are opt-in, not opt-out — a user who never enabled email/SMS delivery only ever sees in-app notifications, consistent with not sending unsolicited external messages to someone who never asked for them. Category-level granularity (e.g. "email me for run failures, but not routine completions") is a reasonable future refinement, not built in v1 — flagged in §7.

---

## 6. Asyncio and profiling
Outbound channel sends are genuine network I/O (Postmark/Semaphore API calls) — the same I/O-bound shape as every other thin-external-API-wrapper API in this batch (Tool Call, Account Guardian). In-app inbox writes are local Persistence I/O, async-wrapped the same way. Nothing further to add beyond that cross-reference — no compute-bound work anywhere in this API's scope.

---

## 7. Testing hooks — a real gap found during a pre-development sweep
- **In-app-always-created test**: confirms the in-app notification lands regardless of outbound channel outcome — the core guarantee §7's own delivery-failure resolution depends on.
- **Bounded-retry test**: confirms a failing outbound send retries exactly three times with backoff, then surfaces to staff rather than retrying forever or failing silently.
- **Channel-preference test**: confirms a user who disabled a channel genuinely receives nothing on it, including for high-priority notification types.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- (SMS provider choice — resolved, no longer open. All three — Semaphore, PhilSMS, Twilio — full design in §4.3, including the real provider-specific guided setup flow.)
- **Category-level channel preferences, resolved: not for v1.** Per-channel opt-in (email/SMS/in-app) covers the real need at launch; per-category granularity on top of that is a real future refinement once actual usage shows it's wanted, not built speculatively now.
- **Delivery failure handling, resolved.** The in-app notification is always created regardless of outbound delivery outcome — the reliable source of truth this API's own design already establishes elsewhere. For an outbound send failure specifically: a bounded retry (three attempts with backoff over the following day) rather than a single silent failure; if every retry fails, the failure itself surfaces to staff (the same Telemetrees-adjacent visibility pattern this project uses for other silent-failure risks) rather than disappearing quietly — but the in-app record was never depending on the outbound channel succeeding in the first place, so a time-sensitive notification like a deletion grace-period reminder is never actually lost, only potentially delayed in reaching the person outside the app.
