"""Email delivery (`v3-deepdive-09-notifications-inbox-api.md` §4.2).

**Postmark is the reasoned default provider, not SendGrid** — the deep-dive's own §4.2
reasoning: this project's email need is pure transactional (run-complete alerts, export-ready
links, deletion-grace-period reminders), Postmark's Message Streams separate transactional
from broadcast infrastructure in a way that gives it a real deliverability edge at this
project's likely volume, and its API is simpler for exactly this "send one clean transactional
email" case. It sits behind `EmailProvider` so switching is a config change
(`docs/PRINCIPLES.md` §1.3), not a rewrite.

**No HTTP client dependency was added for this.** `requirements.txt` is out of this task's own
write boundary, and Postmark's HTTP API is a single `POST` of a JSON body with one auth header
— well within what the standard library's `urllib.request` does directly. `HttpTransport` is
the swappable seam (§1.3 at library granularity, the same reasoning
`core/architect/vendor_directory/wikidata_bootstrap.py::SparqlTransport` applies to its own
HTTP call): production uses `UrllibTransport`, tests inject a fake one, and a future move to a
richer client (`httpx`, connection pooling) is an edit to this one adapter.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from ..contracts import DeliveryOutcome, DeliveryStatus, Notification, utcnow
from .base import unconfigured_status

POSTMARK_ENDPOINT = "https://api.postmarkapp.com/email"


@runtime_checkable
class HttpTransport(Protocol):
    """One POST, blocking. `EmailChannel.send` is what wraps this in `asyncio.to_thread`, so
    a transport implementation stays a plain synchronous function — the same split
    `core/logs/sinks.py`'s own docstring describes for why sinks are synchronous and the
    writer owns the event-loop boundary."""

    def post(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        """Returns `(status_code, response_text)`. Raises only for a genuine transport
        failure (DNS, connection refused, timeout) — an HTTP error status is a normal return,
        not an exception, since a 422 from Postmark is data about the send, not a crash."""


class UrllibTransport:
    """The real transport: `urllib.request`, stdlib-only (see this module's own docstring)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def post(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")


@runtime_checkable
class EmailProvider(Protocol):
    async def is_configured(self) -> bool: ...

    async def send_email(self, to: str, subject: str, body: str) -> tuple[bool, str]:
        """Returns `(sent, detail)`. Never raises — a provider that cannot send reports
        `(False, reason)`, matching `OutboundChannel.send`'s own never-raise contract."""


class UnconfiguredEmailProvider:
    """The correct state before a real API token is set — reports unconfigured and sends
    nothing, the identical posture `core/auth/auth_methods/notifications.py::UnavailableChannel`
    takes for its own not-yet-reachable dependency (`docs/PRINCIPLES.md` §4.4)."""

    async def is_configured(self) -> bool:
        return False

    async def send_email(self, to: str, subject: str, body: str) -> tuple[bool, str]:
        return False, "no email provider configured"


class PostmarkEmailProvider:
    """A real `EmailProvider` against Postmark's transactional email API.

    `api_token` and `from_address` empty means "not configured" — `is_configured` reports that
    honestly rather than attempting a send that Postmark would reject, and `dispatch.py` then
    records `SKIPPED_UNCONFIGURED` rather than `FAILED` for the distinction §7's own
    bounded-retry test cares about (a retry loop for "nobody set up email" would never help).
    """

    def __init__(
        self,
        api_token: str = "",
        from_address: str = "",
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._token = api_token
        self._from = from_address
        self._transport = transport or UrllibTransport()

    async def is_configured(self) -> bool:
        return bool(self._token and self._from)

    async def send_email(self, to: str, subject: str, body: str) -> tuple[bool, str]:
        import asyncio

        if not await self.is_configured():
            return False, "Postmark is not configured (missing token or from-address)"
        payload = json.dumps(
            {
                "From": self._from,
                "To": to,
                "Subject": subject,
                "TextBody": body,
            }
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": self._token,
        }
        try:
            status, text = await asyncio.to_thread(
                self._transport.post, POSTMARK_ENDPOINT, headers, payload
            )
        except OSError as exc:  # DNS failure, connection refused, timeout
            return False, f"Postmark unreachable: {exc}"
        if 200 <= status < 300:
            return True, ""
        return False, f"Postmark returned {status}: {text[:200]}"


class EmailChannel:
    """The `OutboundChannel` wrapper around whichever `EmailProvider` this install configured."""

    def __init__(self, provider: EmailProvider | None = None) -> None:
        self._provider = provider or UnconfiguredEmailProvider()

    @property
    def name(self) -> str:
        return "email"

    async def is_configured(self) -> bool:
        return await self._provider.is_configured()

    async def send(self, user_id: str, notification: Notification, *, recipient: str) -> DeliveryStatus:
        if not await self._provider.is_configured():
            return unconfigured_status("email", "email provider is not configured")
        if not recipient:
            return unconfigured_status("email", "no recipient address resolved for this user")
        sent, detail = await self._provider.send_email(recipient, notification.title, notification.body)
        if sent:
            return DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT, delivered_at=utcnow())
        return DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED, error_detail=detail)


__all__ = [
    "POSTMARK_ENDPOINT",
    "EmailChannel",
    "EmailProvider",
    "HttpTransport",
    "PostmarkEmailProvider",
    "UnconfiguredEmailProvider",
    "UrllibTransport",
]
