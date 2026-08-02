"""The one adapter between Auth and Notifications API's delivery channels.

Auth does not send email or SMS. Notifications API already owns both channels, including the
Philippine SMS provider roster its own deep-dive names, and standing up a second independent
sending capability here would be duplicating a capability that already exists elsewhere in
the system — the specific mistake deep-dive §4.4 calls out.

So: one small internal adapter (`docs/PRINCIPLES.md` §1.3), one Protocol, and every OTP
provider talks to that rather than importing a transport anywhere. Swapping how delivery
actually happens is an edit to this file, not to the providers.

**`UnavailableChannel` is the honest default, not a stub.** Notifications API is not
implemented yet. A channel that reports unavailable makes the email/SMS login options
disappear from the login screen (`docs/PRINCIPLES.md` §4.4) rather than being offered and
then failing after the user has typed their address in. When Notifications lands,
`NotificationsApiChannel` gets a real gRPC client and nothing above this file changes.

**Assumption recorded**: `NotificationsApiChannel` is written against the channel shape
Notifications API's own deep-dive describes (an async send over a named channel with a
recipient and a rendered body). Its `contracts.py` does not exist yet; when it does, the
`_client` seam below is where its stub is plugged in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class NotificationChannel(Protocol):
    """A one-way delivery channel. Deliberately minimal: Auth needs "send this short text
    to this address" and nothing else, and a wider interface here would invite Auth to
    start owning message composition, which is Notifications' job."""

    @property
    def name(self) -> str: ...

    async def is_available(self) -> bool: ...

    async def send(self, recipient: str, subject: str, body: str) -> bool: ...


@dataclass
class UnavailableChannel:
    """Reports unavailable and sends nothing. The correct state when Notifications API is
    not reachable — and, today, when it does not exist yet."""

    channel_name: str
    reason: str = "Notifications API is not reachable"

    @property
    def name(self) -> str:
        return self.channel_name

    async def is_available(self) -> bool:
        return False

    async def send(self, recipient: str, subject: str, body: str) -> bool:
        return False


@dataclass
class NotificationsApiChannel:
    """Delegates to Notifications API over its own gRPC surface.

    `client` is injected rather than constructed here so this module never imports a
    transport. It must expose `async send(channel, recipient, subject, body) -> bool` and
    `async is_available(channel) -> bool`; that is the entire contract this adapter needs,
    and keeping it that narrow is what makes the eventual real client a drop-in.
    """

    channel_name: str
    client: object | None = None

    @property
    def name(self) -> str:
        return self.channel_name

    async def is_available(self) -> bool:
        if self.client is None:
            return False
        probe = getattr(self.client, "is_available", None)
        if probe is None:
            return False
        try:
            return bool(await probe(self.channel_name))
        except Exception:  # noqa: BLE001 - unreachable service is unavailability, not failure
            return False

    async def send(self, recipient: str, subject: str, body: str) -> bool:
        if self.client is None:
            return False
        try:
            return bool(await self.client.send(  # type: ignore[attr-defined]
                self.channel_name, recipient, subject, body
            ))
        except Exception:  # noqa: BLE001 - a failed send is a failed login attempt, not a crash
            return False


__all__ = ["NotificationChannel", "NotificationsApiChannel", "UnavailableChannel"]
