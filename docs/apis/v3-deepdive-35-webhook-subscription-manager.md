# V3 Deep Dive: Webhook Subscription Manager (Ingestion sub-API)

**Parent API:** `v3-deepdive-04-ingestion-api.md` §4.1.3. **Companion files:** `v3-deepdive-12-background-workers-api.md` (renewal runs as an idle-time job), `v3-deepdive-34-watchdog.md` (Circadian's own liveness-inference cousin).

**Status:** Sub-API deep-dive, full treatment — expanding the already-substantial detail in Ingestion's own document.

---

## 1. Scope & boundary

Webhook Subscription Manager owns **generic, provider-agnostic push-notification subscription handling** — registering, renewing, and receiving callbacks for any push-capable source (Drive today, OneDrive/Microsoft Graph or others later via a different provider adapter). It does not:
- **decide run boundaries** — emits a "new file available" event per changed item; Execution Core's own debounce-coalescing logic (its deep-dive §5.2) decides how those events batch into an actual run.
- **care which Drive credential strategy is active** — already designed provider-agnostic with respect to service-account-vs-OAuth (Ingestion deep-dive §4.1.2's own note), a genuine, confirmed design property, not just an aspiration.

---

## 2. Package layout

```
core/ingestion/webhook_manager/
  __init__.py
  contracts.py             # WebhookSubscription, ChangeEvent, error types
  subscription.py             # register/renew/deregister
  circadian.py                   # inferred third-party delivery health — see §4
  callback_handler.py              # receives the actual webhook POST
  errors.py
```

---

## 3. Renewal — register-new-then-confirm-then-deregister-old, never stop-then-start
```python
async def renew(sub: WebhookSubscription) -> WebhookSubscription:
    new_sub = await _register_new_channel(sub.provider)    # a genuinely new channel ID, not reusing the old one
    await _confirm_active(new_sub)                            # a real check the new channel is actually live before touching the old one
    await _deregister(sub)                                       # only now, after confirmation
    return new_sub
```
Stop-then-start would open a real delivery gap between the old channel dying and the new one being confirmed live — a file arriving in that window would simply never trigger anything. Renewal runs proactively, ahead of the provider's own stated expiry, via a Background Worker (idle-time class, its own deep-dive) — the exact lead time is config-tunable, trading unnecessary renewal churn against margin for a slow renewal attempt.

---

## 4. Webhook Circadian — inferred health for a channel with no ping endpoint
No true "is this webhook still healthy" status check exists for these providers — Circadian infers it from delivery *rhythm* rather than a direct query: proactive renewal against the known expiry (§3) is the primary defense, plus a much-less-frequent fallback poll (daily default — its only job is catching the rare case a healthy webhook should have already reported, not serving as a primary mechanism) as a safety net. **Distinct from Watchdog** (its own sub-API deep-dive): Watchdog proves *this program's own* process is alive via kicks it controls; Circadian infers a *third party's* delivery health from timing it doesn't control — genuinely different kinds of liveness signal, correctly kept as two separate mechanisms rather than merged into one "is everything okay" check.

---

## 5. Callback handling — provider-specific quirks isolated to the adapter
```python
async def handle_drive_webhook(payload: bytes) -> tuple[ChangeEvent, ...]:
    """Drive's own webhook POST carries no payload, just a signal that
    something changed — this handler's entire job on receipt is one
    follow-up changes.list() call to find out what, then emit one
    ChangeEvent per changed item. A future OneDrive/Graph adapter would
    have its own equivalent quirk-handling here, isolated to its own
    provider module, never leaking into the generic subscription/
    renewal/Circadian machinery above."""
```

---

## 6. Asyncio
Subscription registration, renewal, and callback handling are all genuine network I/O — no compute-bound work of its own, consistent with Ingestion's own parent-level conclusion (its deep-dive §7).

---

## 7. gRPC surface

```protobuf
service WebhookManagerService {
  rpc RegisterSubscription(RegisterRequest) returns (SubscriptionResponse);
  rpc HandleCallback(CallbackPayload) returns (CallbackAck);   // internal, Gateway forwards the raw provider callback here
}
```

---

## 8. Config

```
webhook_manager:
  renewal_lead_time_hours: 24
  fallback_poll_interval: daily
```

---

## 9. Testing hooks
- **Renewal gap test**: confirms no delivery window exists between old-channel deregistration and new-channel confirmation — direct validation of §3's register-new-first ordering, not just trusted from reading the code.
- **Circadian fallback-catch test**: a simulated silently-dead webhook channel (no renewal failure signal, just stops delivering) is still caught by the fallback poll within its configured interval.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Renewal lead-time default, locked in as a reasoned starting placeholder.** Real observed Drive channel-expiry behavior can tune it once there's actual usage data; the mechanism itself (proactive renewal well ahead of expiry, register-new-then-confirm-then-deregister-old) is what matters for shipping correctly.
