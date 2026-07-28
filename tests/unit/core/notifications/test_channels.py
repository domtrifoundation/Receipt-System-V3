"""Outbound channel adapters (§4.2, §4.3): the unconfigured-by-default posture, and real
provider send outcomes against a fake `HttpTransport` — never a real network call.

**No test here ever reaches the network.** `HttpTransport`/`SmsProvider`'s own transport seam
(`channels/email_channel.py`, `channels/sms_channel.py`) exists specifically so this is true —
a fake transport records what it was asked to send and returns a scripted response, which is
what makes these tests deterministic and offline.
"""

from __future__ import annotations

import asyncio

from core.notifications.channels.email_channel import (
    EmailChannel,
    PostmarkEmailProvider,
    UnconfiguredEmailProvider,
)
from core.notifications.channels.sms_channel import (
    PhilSmsProvider,
    SemaphoreSmsProvider,
    SmsChannel,
    TwilioSmsProvider,
    UnconfiguredSmsProvider,
)
from core.notifications.contracts import DeliveryOutcome, Notification, utcnow


def run(coro):
    return asyncio.run(coro)


class FakeTransport:
    """Records every call and returns a scripted `(status, body)`."""

    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, dict, bytes]] = []

    def post(self, url, headers, body):
        self.calls.append((url, headers, body))
        return self.status, self.body


def _notification() -> Notification:
    return Notification(
        notification_id="ntf_1", user_id="user-1", category="run_complete",
        title="Run finished", body="details", created_at=utcnow(),
    )


# ------------------------------------------------------------------------- email


def test_unconfigured_email_provider_reports_not_configured():
    channel = EmailChannel(UnconfiguredEmailProvider())
    assert run(channel.is_configured()) is False


def test_email_channel_skips_unconfigured_rather_than_attempting_a_send():
    channel = EmailChannel(UnconfiguredEmailProvider())
    status = run(channel.send("user-1", _notification(), recipient="user@example.com"))
    assert status.outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED


def test_email_channel_skips_with_no_recipient_even_if_configured():
    provider = PostmarkEmailProvider("token", "noreply@domtri.example", transport=FakeTransport())
    channel = EmailChannel(provider)
    status = run(channel.send("user-1", _notification(), recipient=""))
    assert status.outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED


def test_postmark_provider_is_configured_only_with_both_token_and_from_address():
    assert run(PostmarkEmailProvider("", "").is_configured()) is False
    assert run(PostmarkEmailProvider("tok", "").is_configured()) is False
    assert run(PostmarkEmailProvider("tok", "from@example.com").is_configured()) is True


def test_postmark_success_reaches_the_channel_as_sent():
    transport = FakeTransport(status=200, body='{"MessageID": "abc"}')
    provider = PostmarkEmailProvider("tok", "from@example.com", transport=transport)
    channel = EmailChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="to@example.com"))

    assert status.ok
    assert status.delivered_at is not None
    assert transport.calls[0][0] == "https://api.postmarkapp.com/email"
    assert transport.calls[0][1]["X-Postmark-Server-Token"] == "tok"


def test_postmark_http_error_reaches_the_channel_as_failed_not_an_exception():
    transport = FakeTransport(status=422, body='{"ErrorCode": 300}')
    provider = PostmarkEmailProvider("tok", "from@example.com", transport=transport)
    channel = EmailChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="to@example.com"))

    assert status.outcome is DeliveryOutcome.FAILED
    assert "422" in status.error_detail


def test_postmark_transport_failure_degrades_to_failed_not_a_raise():
    class ExplodingTransport:
        def post(self, url, headers, body):
            raise OSError("network unreachable")

    provider = PostmarkEmailProvider("tok", "from@example.com", transport=ExplodingTransport())
    channel = EmailChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="to@example.com"))

    assert status.outcome is DeliveryOutcome.FAILED
    assert "unreachable" in status.error_detail


# --------------------------------------------------------------------------- sms


def test_sms_channel_is_off_by_default_shape_reports_unconfigured():
    """§4.3: SMS is off by default — the channel itself reports unconfigured until a real
    provider is set up, the same posture email's own `UnconfiguredEmailProvider` takes."""
    channel = SmsChannel(UnconfiguredSmsProvider("sms"))
    assert run(channel.is_configured()) is False


def test_semaphore_requires_both_api_key_and_registered_sender_name():
    """§4.3's own real, distinct requirement for PH-market providers: an API key alone is not
    enough, or SMS reports 'configured' but is silently filtered as spam."""
    assert run(SemaphoreSmsProvider("", "").is_configured()) is False
    assert run(SemaphoreSmsProvider("key", "").is_configured()) is False
    assert run(SemaphoreSmsProvider("", "SenderName").is_configured()) is False
    assert run(SemaphoreSmsProvider("key", "SenderName").is_configured()) is True


def test_philsms_requires_both_token_and_registered_sender_name():
    assert run(PhilSmsProvider("tok", "").is_configured()) is False
    assert run(PhilSmsProvider("tok", "SenderName").is_configured()) is True


def test_twilio_needs_no_sender_name_registration():
    """§4.3: Twilio's own flow has no sender-name-registration step, unlike the two PH-market
    providers — a genuinely simpler configuration surface."""
    assert run(TwilioSmsProvider("sid", "token", "").is_configured()) is False
    assert run(TwilioSmsProvider("sid", "token", "+15550001111").is_configured()) is True


def test_semaphore_send_success_reaches_the_channel_as_sent():
    transport = FakeTransport(status=200, body="{}")
    provider = SemaphoreSmsProvider("key", "DOMTRI", transport=transport)
    channel = SmsChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="+639171234567"))

    assert status.ok
    assert transport.calls[0][0] == "https://semaphore.co/api/v4/messages"


def test_philsms_send_failure_is_reported_not_raised():
    transport = FakeTransport(status=400, body="bad request")
    provider = PhilSmsProvider("tok", "DOMTRI", transport=transport)
    channel = SmsChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="+639171234567"))

    assert status.outcome is DeliveryOutcome.FAILED
    assert "400" in status.error_detail


def test_twilio_send_success_uses_basic_auth_and_form_body():
    transport = FakeTransport(status=201, body="{}")
    provider = TwilioSmsProvider("SID123", "authtoken", "+15550001111", transport=transport)
    channel = SmsChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient="+15550002222"))

    assert status.ok
    url, headers, body = transport.calls[0]
    assert url == "https://api.twilio.com/2010-04-01/Accounts/SID123/Messages.json"
    assert headers["Authorization"].startswith("Basic ")


def test_sms_channel_skips_with_no_recipient_even_if_configured():
    provider = TwilioSmsProvider("sid", "token", "+15550001111", transport=FakeTransport())
    channel = SmsChannel(provider)

    status = run(channel.send("user-1", _notification(), recipient=""))

    assert status.outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED
