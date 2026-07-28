"""SMS delivery (`v3-deepdive-09-notifications-inbox-api.md` §4.3) — resolved, not open.

**All three providers ship as real, concrete implementations**: Semaphore, PhilSMS, and
Twilio, each behind the identical `SmsProvider` interface the deep-dive's own §4.3 sketches,
matching `docs/PRINCIPLES.md` §1.2 rather than picking one winner. **Off by default** — SMS
costs real money per message, so `channels/__init__.py`'s registry wiring registers this
channel with `enabled=False`, the same "opt-in, real-cost capability" posture Billing and
Tunnel Exposure already apply elsewhere in this project.

**Sender name registration is a real, distinct configuration field, not an oversight.** The
deep-dive is specific about why: PH telco networks (Globe/Smart/Sun) generally filter SMS from
an unregistered sender as spam, so Semaphore and PhilSMS each require `sender_name` in addition
to an API key before `is_configured()` can honestly report `True` — Twilio's own flow (account
SID, auth token, phone number) has no equivalent requirement, which is why its own
`is_configured` check does not ask for one. Skipping that field for the PH providers is exactly
the "SMS reports configured but silently never delivers" gap the deep-dive calls out.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from ..contracts import DeliveryOutcome, DeliveryStatus, Notification, utcnow
from .base import unconfigured_status
from .email_channel import HttpTransport, UrllibTransport


@runtime_checkable
class SmsProvider(Protocol):
    """The deep-dive's own §4.3 sketch, verbatim."""

    async def send_sms(self, to: str, message: str) -> DeliveryStatus: ...

    async def is_configured(self) -> bool: ...


class UnconfiguredSmsProvider:
    """The honest default for whichever provider name an install has not set up."""

    def __init__(self, provider_name: str) -> None:
        self._name = provider_name

    async def is_configured(self) -> bool:
        return False

    async def send_sms(self, to: str, message: str) -> DeliveryStatus:
        return unconfigured_status("sms", f"{self._name} is not configured")


def _text_response(status: int, text: str) -> tuple[bool, str]:
    if 200 <= status < 300:
        return True, ""
    return False, f"HTTP {status}: {text[:200]}"


class SemaphoreSmsProvider:
    """https://semaphore.co — one of the two PH-specific providers requiring `sender_name`
    registration (this module's own docstring) in addition to an API key."""

    _ENDPOINT = "https://semaphore.co/api/v4/messages"

    def __init__(
        self, api_key: str = "", sender_name: str = "", *, transport: HttpTransport | None = None
    ) -> None:
        self._api_key = api_key
        self._sender_name = sender_name
        self._transport = transport or UrllibTransport()

    async def is_configured(self) -> bool:
        return bool(self._api_key and self._sender_name)

    async def send_sms(self, to: str, message: str) -> DeliveryStatus:
        import asyncio

        if not await self.is_configured():
            return unconfigured_status(
                "sms", "Semaphore requires both an API key and a registered sender name"
            )
        body = json.dumps(
            {"apikey": self._api_key, "number": to, "message": message, "sendername": self._sender_name}
        ).encode("utf-8")
        try:
            status, text = await asyncio.to_thread(
                self._transport.post, self._ENDPOINT, {"Content-Type": "application/json"}, body
            )
        except OSError as exc:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=f"Semaphore unreachable: {exc}")
        sent, detail = _text_response(status, text)
        if sent:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.SENT, delivered_at=utcnow())
        return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=detail)


class PhilSmsProvider:
    """https://philsms.com — the second PH-specific provider, same `sender_name` requirement
    as Semaphore, per this module's own docstring."""

    _ENDPOINT = "https://app.philsms.com/api/v3/sms/send"

    def __init__(
        self, api_token: str = "", sender_name: str = "", *, transport: HttpTransport | None = None
    ) -> None:
        self._api_token = api_token
        self._sender_name = sender_name
        self._transport = transport or UrllibTransport()

    async def is_configured(self) -> bool:
        return bool(self._api_token and self._sender_name)

    async def send_sms(self, to: str, message: str) -> DeliveryStatus:
        import asyncio

        if not await self.is_configured():
            return unconfigured_status(
                "sms", "PhilSMS requires both an API token and a registered sender name"
            )
        body = json.dumps(
            {"recipient": to, "sender_id": self._sender_name, "message": message}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_token}"}
        try:
            status, text = await asyncio.to_thread(self._transport.post, self._ENDPOINT, headers, body)
        except OSError as exc:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=f"PhilSMS unreachable: {exc}")
        sent, detail = _text_response(status, text)
        if sent:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.SENT, delivered_at=utcnow())
        return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=detail)


class TwilioSmsProvider:
    """https://www.twilio.com — no sender-name registration step (this module's own
    docstring): a genuinely simpler flow of account SID, auth token, and a provisioned
    from-number for anyone already familiar with Twilio."""

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        from_number: str = "",
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._transport = transport or UrllibTransport()

    async def is_configured(self) -> bool:
        return bool(self._sid and self._token and self._from)

    async def send_sms(self, to: str, message: str) -> DeliveryStatus:
        import asyncio
        import base64
        import urllib.parse

        if not await self.is_configured():
            return unconfigured_status("sms", "Twilio requires an account SID, auth token, and from-number")
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        body = urllib.parse.urlencode({"To": to, "From": self._from, "Body": message}).encode("utf-8")
        auth = base64.b64encode(f"{self._sid}:{self._token}".encode()).decode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth}",
        }
        try:
            status, text = await asyncio.to_thread(self._transport.post, endpoint, headers, body)
        except OSError as exc:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=f"Twilio unreachable: {exc}")
        sent, detail = _text_response(status, text)
        if sent:
            return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.SENT, delivered_at=utcnow())
        return DeliveryStatus(channel="sms", outcome=DeliveryOutcome.FAILED, error_detail=detail)


class SmsChannel:
    """The `OutboundChannel` wrapper around whichever `SmsProvider` this install selected —
    Semaphore, PhilSMS, Twilio, or `UnconfiguredSmsProvider` if none is set up yet."""

    def __init__(self, provider: SmsProvider | None = None) -> None:
        self._provider = provider or UnconfiguredSmsProvider("sms")

    @property
    def name(self) -> str:
        return "sms"

    async def is_configured(self) -> bool:
        return await self._provider.is_configured()

    async def send(self, user_id: str, notification: Notification, *, recipient: str) -> DeliveryStatus:
        if not recipient:
            return unconfigured_status("sms", "no recipient phone number resolved for this user")
        if not await self._provider.is_configured():
            return unconfigured_status("sms", "no SMS provider is configured for this install")
        return await self._provider.send_sms(recipient, f"{notification.title}: {notification.body}")


__all__ = [
    "PhilSmsProvider",
    "SemaphoreSmsProvider",
    "SmsChannel",
    "SmsProvider",
    "TwilioSmsProvider",
    "UnconfiguredSmsProvider",
]
