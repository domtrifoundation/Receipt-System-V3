"""The `OutboundChannel` Provider Registry (`v3-deepdive-09-notifications-inbox-api.md` §4.1)
— named in the deep-dive's own §2 package layout as this file's job.

**Decision, straight from §4.1**: `OutboundChannel` is a Provider Registry interface
(`docs/PRINCIPLES.md` §1.2), with email and SMS as the two initial channel types. **More than
one channel can be enabled at once** — a user who opted into both email and SMS should get
both, not one selected from config — which is exactly the "running several simultaneously adds
real value" shape §1.2 asks for, the same reasoning `core/logs/sinks.py::SinkRegistry` and
`core/audit/sinks.py::SinkRegistry` apply to their own destinations.

A failing channel degrades on its own and never fails the notification that triggered it
(`docs/PRINCIPLES.md` §4.4, deep-dive §8's own resolved delivery-failure handling) — `send()`
below is the one place that guarantee is enforced structurally: it always returns a
`DeliveryStatus`, never raises, so `dispatch.py` can never have one channel's exception take
down another's attempt or the in-app write that already happened.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..contracts import DeliveryOutcome, DeliveryStatus, Notification


@runtime_checkable
class OutboundChannel(Protocol):
    """One delivery channel, per the deep-dive's own §4.1 sketch."""

    @property
    def name(self) -> str:
        """Stable identifier — a `ChannelPreference.channel` value, the registry key, and
        the label used in metrics and `DeliveryStatus.channel`."""

    async def is_configured(self) -> bool:
        """Whether this install can actually use this channel at all right now (an API key
        present, a sender name registered) — distinct from whether *this user* opted in,
        which is `preferences.py`'s question, not this one."""

    async def send(self, user_id: str, notification: Notification, *, recipient: str) -> DeliveryStatus:
        """Attempt one delivery. Never raises — an implementation that cannot send reports
        `DeliveryOutcome.FAILED` with `error_detail` rather than propagating an exception,
        since this is called from `dispatch.py`'s fan-out and one channel's own failure must
        never disturb another's attempt (§4.4)."""


@runtime_checkable
class RecipientResolver(Protocol):
    """The seam onto Auth's own `User` record (`core/auth/contracts.py::User.email` /
    `.phone_number`) for the *default* contact address, when a `ChannelPreference` carries no
    `contact_override`. Deliberately not an import of Auth — this package holds no notion of
    how a user record is structured, only "what address does this channel send to."""

    def resolve(self, user_id: str, channel: str) -> str | None:
        """The address to send to, or `None` if it cannot be resolved — treated as
        "this channel degrades to unconfigured for this user", never as a reason to fail the
        notification (§4.4); this is not a security check."""


class NoRecipientResolver:
    """The honest default before Auth is wired in: every resolution comes back `None`, which
    makes every outbound channel report `SKIPPED_UNCONFIGURED` for every user rather than being
    offered and then failing after an attempt (the same posture
    `core/auth/auth_methods/notifications.py::UnavailableChannel` takes from the other
    direction, before this API existed)."""

    def resolve(self, user_id: str, channel: str) -> str | None:
        return None


def unconfigured_status(channel: str, detail: str) -> DeliveryStatus:
    """The shared "this channel is not usable right now" result — used by every provider's
    own unconfigured default and by `dispatch.py` when no recipient resolves, so the same
    outcome is spelled identically everywhere rather than three slightly different strings."""
    return DeliveryStatus(channel=channel, outcome=DeliveryOutcome.SKIPPED_UNCONFIGURED, error_detail=detail)


class ChannelRegistry:
    """Holds every registered channel and which of them are install-level enabled.

    Two independent gates sit on top of each other by design: a channel must be both
    **registered and enabled here** (an install-level decision — SMS is off by default per
    §4.3, a real-cost capability nobody should be opted into by a fresh install) **and** the
    specific user must have opted into it (`preferences.py`) before `dispatch.py` attempts a
    send. Genuinely mutable internal registry populated at startup, so a plain `dict`/`set`,
    never `FrozenDict` (`docs/PRINCIPLES.md` §2.1.1) — the identical distinction
    `core/logs/sinks.py::SinkRegistry` and `core/audit/sinks.py::SinkRegistry` already draw.
    """

    def __init__(self) -> None:
        self._channels: dict[str, OutboundChannel] = {}
        self._enabled: set[str] = set()

    def register(self, channel: OutboundChannel, *, enabled: bool = True) -> None:
        self._channels[channel.name] = channel
        if enabled:
            self._enabled.add(channel.name)
        else:
            self._enabled.discard(channel.name)

    def enable(self, name: str) -> bool:
        if name not in self._channels:
            return False
        self._enabled.add(name)
        return True

    def disable(self, name: str) -> None:
        self._enabled.discard(name)

    def get(self, name: str) -> OutboundChannel | None:
        return self._channels.get(name)

    def enabled(self) -> tuple[OutboundChannel, ...]:
        return tuple(self._channels[n] for n in sorted(self._enabled))


__all__ = [
    "ChannelRegistry",
    "NoRecipientResolver",
    "OutboundChannel",
    "RecipientResolver",
    "unconfigured_status",
]
