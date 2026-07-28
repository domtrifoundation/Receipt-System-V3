"""The orchestrator: always write the in-app record, then fan out to outbound channels.

**Not in the deep-dive's §2 package layout.** The layout names `inbox.py` (in-app storage) and
`channels/` (the outbound Provider Registry) as separate concerns, but something has to call
both in the right order and enforce §8's own resolved delivery-failure handling — that a
failing outbound send never fails the in-app write, and that a send failing three times gets
surfaced rather than silently dropped. Putting that in `service.py` would make the *thin gRPC
translation layer* also own the bounded-retry policy, exactly the thing
`core/logs/service.py`'s own docstring says never to do; putting it in `inbox.py` would make
the in-app store responsible for outbound channels it does not otherwise know exist. One small
orchestrator module is the shape every other Wave 1 API already uses for this (`core/audit`'s
`writer.py` calling into `sinks.py`'s registry).

**§7's bounded-retry test, and what "over the following day" actually means here.** The
deep-dive specifies three attempts with backoff *spread across a day* before a failure
escalates to staff. Actually spreading attempts across a day is Background Workers' own
idle-time scheduling — and Background Workers does not exist as an implemented Core API in
this codebase yet. What is built here is the **policy** the deep-dive states — exactly three
attempts, escalate only once all three are spent — with the *delay between attempts* as an
injectable, testable seam (`backoff_seconds`) rather than a literal `asyncio.sleep` of hours.
Wiring that seam to Background Workers' real day-spanning schedule is that API's own future
integration; the retry-count and escalate-on-exhaustion behaviour this module implements is
correct and fully tested today regardless of what drives the delay.

**Escalation degrades to a metrics counter today, and that is a real, flagged gap, not a
silent shortcut.** Surfacing a failure "to staff" needs to know who staff/owner *is* for this
install, which is Auth's own `Role`/`User` model (`core/auth/contracts.py`) — wiring that in
means this module gains an `OwnerResolver`-shaped seam and calls back into `Notifier.notify`
itself to raise a `notification_delivery_failed` notification for that owner, a closed loop
this design supports cleanly once that resolver exists. Until then, `StaffEscalator`'s default
implementation only increments `channel_failures_escalated`, and that is the honest current
behaviour rather than an invented notification with an invented recipient.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Protocol, runtime_checkable

from .channels.base import (
    ChannelRegistry,
    NoRecipientResolver,
    OutboundChannel,
    RecipientResolver,
    unconfigured_status,
)
from .channels.email_channel import EmailChannel, UnconfiguredEmailProvider
from .channels.sms_channel import SmsChannel, UnconfiguredSmsProvider
from .contracts import DeliveryOutcome, DeliveryStatus, Notification, NotifyRequest, NotifyResult
from .errors import NotificationsError, code_for
from .inbox import InboxStore
from .metrics import NotificationsMetricsCollector
from .preferences import PreferenceStore

#: Exactly three attempts (§7, §8) — not configurable per-call, since the whole point of a
#: closed policy is that a caller cannot quietly weaken it for one notification.
MAX_ATTEMPTS = 3

#: No real delay by default: tests and an unwired install both get the policy's *shape*
#: (retry, then escalate) without waiting on a clock. A real Background Workers integration
#: passes its own schedule in here instead of using this default (see module docstring).
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (0.0, 0.0)


@runtime_checkable
class StaffEscalator(Protocol):
    """What happens once every attempt on one channel has failed (§8)."""

    def escalate(
        self, user_id: str, channel: str, notification: Notification, attempts: tuple[DeliveryStatus, ...]
    ) -> None: ...


class MetricsOnlyEscalator:
    """The honest default before an `OwnerResolver` exists — see this module's own docstring
    on why inventing a notification recipient here would be worse than an explicit gap."""

    def escalate(self, user_id, channel, notification, attempts) -> None:
        return None


def default_channel_registry() -> ChannelRegistry:
    """The startup default: email registered and enabled with `UnconfiguredEmailProvider`
    (reports itself unusable until a real Postmark token is set — §4.4), SMS registered but
    **disabled**, matching §4.3's "off by default" for a real-cost capability nobody should be
    opted into by a fresh install."""
    registry = ChannelRegistry()
    registry.register(EmailChannel(UnconfiguredEmailProvider()), enabled=True)
    registry.register(SmsChannel(UnconfiguredSmsProvider("sms")), enabled=False)
    return registry


class Notifier:
    """Consumes one `NotifyRequest` (deep-dive §1's own list of callers: Auth's break-glass,
    Execution Core, Content Security, Account Guardian, Review/Flagging) and produces one
    `NotifyResult` — the in-app record plus every enabled channel's own `DeliveryStatus`."""

    def __init__(
        self,
        inbox: InboxStore,
        preferences: PreferenceStore,
        registry: ChannelRegistry | None = None,
        *,
        recipient_resolver: RecipientResolver | None = None,
        escalator: StaffEscalator | None = None,
        metrics: NotificationsMetricsCollector | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self._inbox = inbox
        self._preferences = preferences
        self._registry = registry or default_channel_registry()
        self._recipients = recipient_resolver or NoRecipientResolver()
        self._escalator = escalator or MetricsOnlyEscalator()
        self._metrics = metrics or inbox.metrics
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff_seconds

    async def notify(self, request: NotifyRequest) -> NotifyResult:
        """The in-app write happens first and unconditionally (§8's own core guarantee): a
        `NotificationsError` here is a real failure of this API's own durable record, and is
        the only thing that makes `NotifyResult.ok` false. Every outbound channel's own
        outcome lives in `channel_statuses` and never changes `ok`."""
        try:
            notification = self._inbox.create(request)
        except NotificationsError as exc:
            return NotifyResult(ok=False, error_code=code_for(exc), error_detail=str(exc))

        statuses = tuple(
            [
                await self._dispatch_one(channel, request.user_id, notification)
                for channel in self._registry.enabled()
            ]
        )
        return NotifyResult(ok=True, notification=notification, channel_statuses=statuses)

    async def _dispatch_one(
        self, channel: OutboundChannel, user_id: str, notification: Notification
    ) -> DeliveryStatus:
        """One channel's full attempt, including the bounded retry. Never raises — a channel
        implementation that somehow does is still this module's problem to contain, since a
        broken channel must never take down another channel's attempt or the caller of
        `notify()` (`docs/PRINCIPLES.md` §4.4)."""
        if not self._preferences.is_enabled(user_id, channel.name):
            self._metrics.increment("channel_sends_skipped_disabled")
            return DeliveryStatus(
                channel=channel.name,
                outcome=DeliveryOutcome.SKIPPED_DISABLED,
                error_detail="this user has not opted into this channel",
            )
        try:
            configured = await channel.is_configured()
        except Exception:  # noqa: BLE001 - a broken is_configured() degrades to "not configured"
            configured = False
        if not configured:
            self._metrics.increment("channel_sends_skipped_unconfigured")
            return unconfigured_status(channel.name, "channel is not configured for this install")

        recipient = self._recipients.resolve(user_id, channel.name)
        if not recipient:
            self._metrics.increment("channel_sends_skipped_unconfigured")
            return unconfigured_status(channel.name, "no recipient address resolved for this user")

        attempts: list[DeliveryStatus] = []
        for attempt in range(1, self._max_attempts + 1):
            self._metrics.increment("channel_sends_attempted")
            try:
                status = await channel.send(user_id, notification, recipient=recipient)
            except Exception as exc:  # noqa: BLE001 - a raising channel is a failed attempt
                status = DeliveryStatus(
                    channel=channel.name, outcome=DeliveryOutcome.FAILED,
                    error_detail=f"{type(exc).__name__}: {exc}",
                )
            status = replace(status, attempt=attempt)
            attempts.append(status)
            if status.ok:
                self._metrics.increment("channel_sends_succeeded")
                return status
            if attempt < self._max_attempts:
                self._metrics.increment("channel_send_retries")
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)] if self._backoff else 0.0
                if delay:
                    await asyncio.sleep(delay)

        self._metrics.increment("channel_sends_failed")
        self._metrics.increment("channel_failures_escalated")
        self._escalator.escalate(user_id, channel.name, notification, tuple(attempts))
        return attempts[-1]

    def close(self) -> None:
        self._inbox.close()
        self._preferences.close()


__all__ = [
    "DEFAULT_BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "MetricsOnlyEscalator",
    "Notifier",
    "StaffEscalator",
    "default_channel_registry",
]
