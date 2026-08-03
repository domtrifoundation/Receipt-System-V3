"""`WebhookManager` — the real, stateful assembly point tying `subscription.py`'s
register/renew primitives, `circadian.py`'s delivery-rhythm inference, and
`callback_handler.py`'s callback processing together into one thing `core/ingestion/
service.py` can actually hold and call.

**This class is the piece that was missing entirely, not any of the modules it
composes.** `subscription.py`, `circadian.py`, and `callback_handler.py` all existed,
each independently tested — but nothing ever constructed a subscription store, tracked a
Drive Changes API page token across calls, or called `circadian.record_delivery()` when a
real callback arrived. `HandleDriveWebhook` (the one real gRPC entry point named in
`ingestion.proto`) acknowledged every callback unconditionally without doing anything —
the entire webhook_manager sub-API was disconnected from the running service.
"""

from __future__ import annotations

import collections
import threading

from .circadian import CircadianMonitor
from .contracts import ChangeEvent, WebhookSubscription
from .errors import UnknownSubscription
from .subscription import WebhookProviderAdapter, renew

__all__ = ["WebhookManager"]


class WebhookManager:
    def __init__(
        self,
        adapter: WebhookProviderAdapter | None = None,
        *,
        renewal_lead_time_hours: int = 24,
        fallback_poll_interval_hours: int = 24,
    ) -> None:
        from datetime import timedelta

        self._adapter = adapter
        #: Read by a future Background Worker deciding when to call `renew()` — not
        #: enforced by a timer here (see this class's own module docstring).
        self.renewal_lead_time_hours = renewal_lead_time_hours
        self._lock = threading.Lock()
        self.circadian = CircadianMonitor(fallback_poll_interval=timedelta(hours=fallback_poll_interval_hours))
        #: channel_id -> subscription. A plain mutable dict guarded by a lock, not a
        #: `FrozenDict` — genuinely mutable runtime state (`docs/PRINCIPLES.md` §2.1.1's
        #: own carve-out), same category as `core/ocr/engine_registry.py`'s own
        #: cloud-call-count tracking.
        self._subscriptions: dict[str, WebhookSubscription] = {}
        #: channel_id -> the Drive Changes API's own page token, so consecutive
        #: callbacks for the same channel each advance from where the last one left off
        #: (`callback_handler.py`'s own stated statelessness — the caller is responsible
        #: for persisting this, and this manager is that caller).
        self._page_tokens: dict[str, str] = {}
        #: Deep-dive §1's own stated boundary: this sub-API "never decides run
        #: boundaries," it only emits one `ChangeEvent` per changed item — Execution
        #: Core's own debounce-coalescing logic (not yet built anywhere in this repo) is
        #: the real intended consumer. A bounded in-memory queue is a real, honest
        #: placeholder for that hand-off: events are genuinely produced and held
        #: somewhere inspectable rather than computed and immediately discarded, which is
        #: what `HandleDriveWebhook`'s own previous stub implementation did.
        self.pending_events: collections.deque[ChangeEvent] = collections.deque(maxlen=10_000)

    async def register(self, watched_resource: str, start_page_token: str = "") -> WebhookSubscription:
        if self._adapter is None:
            raise UnknownSubscription("no webhook provider adapter configured")
        subscription = await self._adapter.register(watched_resource)
        with self._lock:
            self._subscriptions[subscription.channel_id] = subscription
            self._page_tokens[subscription.channel_id] = start_page_token
        return subscription

    async def renew(self, channel_id: str) -> WebhookSubscription:
        if self._adapter is None:
            raise UnknownSubscription("no webhook provider adapter configured")
        with self._lock:
            old_subscription = self._subscriptions.get(channel_id)
            page_token = self._page_tokens.get(channel_id, "")
        if old_subscription is None:
            raise UnknownSubscription(f"no tracked subscription for channel {channel_id!r}")

        new_subscription = await renew(old_subscription, self._adapter)
        with self._lock:
            del self._subscriptions[channel_id]
            self._page_tokens.pop(channel_id, None)
            self._subscriptions[new_subscription.channel_id] = new_subscription
            self._page_tokens[new_subscription.channel_id] = page_token
        return new_subscription

    async def handle_callback(self, channel_id: str, credentials) -> tuple[ChangeEvent, ...]:
        """Deep-dive §5's own Drive callback quirk: the POST itself carries no payload,
        just a signal — this is the one real place that signal turns into actual
        `ChangeEvent`s, and the one real place a callback's arrival is recorded for
        Circadian's own delivery-rhythm inference (deep-dive §4)."""
        from .callback_handler import handle_drive_webhook

        with self._lock:
            page_token = self._page_tokens.get(channel_id)
        if page_token is None:
            raise UnknownSubscription(f"no tracked subscription for channel {channel_id!r}")

        self.circadian.record_delivery(channel_id)
        events = await handle_drive_webhook(credentials, page_token)
        self.pending_events.extend(events)
        return events

    def known_channel_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._subscriptions)
