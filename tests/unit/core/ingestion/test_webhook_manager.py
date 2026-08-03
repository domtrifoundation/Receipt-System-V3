"""Webhook Subscription Manager sub-API (`v3-deepdive-35-webhook-subscription-manager.md`)
— renewal ordering (§3) and Circadian's delivery-rhythm inference (§4), both against real
logic, no live Drive credentials needed since these are provider-agnostic by design.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.ingestion.webhook_manager.contracts import WebhookProvider, WebhookSubscription
from core.ingestion.webhook_manager.errors import ConfirmationFailed, RenewalFailed
from core.ingestion.webhook_manager.subscription import renew
from core.ingestion.webhook_manager.circadian import CircadianMonitor

from .conftest import run


def _old_subscription() -> WebhookSubscription:
    return WebhookSubscription(
        channel_id="old-chan", resource_id="old-res", provider=WebhookProvider.GOOGLE_DRIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1), watched_resource="folder1",
    )


class _TrackingAdapter:
    def __init__(self, confirm_result: bool = True, fail_register: bool = False) -> None:
        self.calls: list[str] = []
        self._confirm_result = confirm_result
        self._fail_register = fail_register

    async def register(self, watched_resource: str) -> WebhookSubscription:
        self.calls.append("register")
        if self._fail_register:
            raise RuntimeError("registration boom")
        return WebhookSubscription(
            channel_id="new-chan", resource_id="new-res", provider=WebhookProvider.GOOGLE_DRIVE,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7), watched_resource=watched_resource,
        )

    async def confirm_active(self, subscription: WebhookSubscription) -> bool:
        self.calls.append("confirm")
        return self._confirm_result

    async def deregister(self, subscription: WebhookSubscription) -> None:
        self.calls.append("deregister")


def test_renew_registers_confirms_then_deregisters_in_order():
    adapter = _TrackingAdapter()
    new_sub = run(renew(_old_subscription(), adapter))
    assert adapter.calls == ["register", "confirm", "deregister"]
    assert new_sub.channel_id == "new-chan"


def test_renew_never_deregisters_the_old_channel_if_confirmation_fails():
    """The concrete validation of the deep-dive's own §3 no-delivery-gap guarantee: a
    confirmation failure must leave the old (still-active) channel untouched."""
    adapter = _TrackingAdapter(confirm_result=False)
    with pytest.raises(ConfirmationFailed):
        run(renew(_old_subscription(), adapter))
    assert "deregister" not in adapter.calls


def test_renew_raises_renewal_failed_when_registration_itself_fails():
    adapter = _TrackingAdapter(fail_register=True)
    with pytest.raises(RenewalFailed):
        run(renew(_old_subscription(), adapter))
    assert adapter.calls == ["register"]


def test_circadian_needs_poll_when_channel_never_delivered():
    monitor = CircadianMonitor(fallback_poll_interval=timedelta(hours=1))
    assert monitor.needs_fallback_poll("chan1") is True


def test_circadian_does_not_need_poll_within_the_interval():
    monitor = CircadianMonitor(fallback_poll_interval=timedelta(hours=1))
    monitor.record_delivery("chan1", at=datetime.now(timezone.utc) - timedelta(minutes=30))
    assert monitor.needs_fallback_poll("chan1") is False


def test_circadian_catches_a_channel_that_silently_stopped_delivering():
    """Deep-dive §9's own named test: a channel that stops delivering with no renewal
    failure signal is still caught by the fallback poll within its configured interval."""
    monitor = CircadianMonitor(fallback_poll_interval=timedelta(hours=1))
    monitor.record_delivery("chan1", at=datetime.now(timezone.utc) - timedelta(hours=2))
    assert monitor.needs_fallback_poll("chan1") is True
