"""The orchestrator (`dispatch.py`): always create the in-app record, honor preferences, and
degrade a failing channel alone without ever failing the event that triggered it (§7, §8).

The single most important guarantee tested here is
`test_in_app_notification_is_created_even_when_every_channel_fails` — deep-dive §7's own named
testing hook ("confirms the in-app notification lands regardless of outbound channel outcome —
the core guarantee §7's own delivery-failure resolution depends on"). Every other test in this
file is really in service of that one claim: a channel is allowed to fail in as many ways as
it likes, and none of them may reach back and un-create the notification that already happened.
"""

from __future__ import annotations

from core.notifications.channels.base import ChannelRegistry, NoRecipientResolver
from core.notifications.contracts import (
    DeliveryOutcome,
    DeliveryStatus,
    NotifyRequest,
)
from core.notifications.dispatch import MetricsOnlyEscalator, Notifier
from core.notifications.inbox import InboxStore
from core.notifications.preferences import PreferenceStore

from .conftest import ExplodingChannel, FakeChannel, FakeRecipientResolver, run


def _notifier(
    top_level, *, registry=None, recipient_resolver=None, escalator=None, backoff=(0.0, 0.0)
):
    inbox = InboxStore(top_level)
    preferences = PreferenceStore(top_level)
    notifier = Notifier(
        inbox,
        preferences,
        registry,
        recipient_resolver=recipient_resolver or FakeRecipientResolver(),
        escalator=escalator,
        backoff_seconds=backoff,
    )
    return notifier, inbox, preferences


def _enabled_registry(channel) -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register(channel, enabled=True)
    return registry


# --------------------------------------------------------------- the core §7/§8 guarantee


def test_in_app_notification_is_created_even_when_every_channel_fails(top_level, preferences):
    """§7's own named hook, verbatim: the in-app record lands regardless of outbound outcome."""
    channel = FakeChannel(outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED)])
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_error", title="Run failed", body="oops")
    ))

    assert result.ok
    assert result.notification is not None
    assert result.channel_statuses[0].outcome is DeliveryOutcome.FAILED
    inbox.close()
    prefs.close()


def test_a_broken_channel_never_prevents_the_in_app_write(top_level):
    """A channel raising outright — not just returning `FAILED` — must not propagate past
    `dispatch.py` and take the in-app write down with it (`docs/PRINCIPLES.md` §4.4)."""
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(ExplodingChannel()))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_error", title="t", body="b")
    ))

    assert result.ok
    assert result.channel_statuses[0].outcome is DeliveryOutcome.FAILED
    assert "blew up" in result.channel_statuses[0].error_detail
    inbox.close()
    prefs.close()


def test_the_in_app_write_failing_is_the_only_thing_that_makes_ok_false(top_level):
    notifier, inbox, prefs = _notifier(top_level)

    result = run(notifier.notify(NotifyRequest(user_id="", category="x", title="t", body="b")))

    assert not result.ok
    assert result.error_code == "INVALID_NOTIFICATION"
    inbox.close()
    prefs.close()


# ------------------------------------------------------------------- preference honoring


def test_a_disabled_channel_is_skipped_and_never_attempted(top_level):
    channel = FakeChannel()
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    # deliberately never opted in

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SKIPPED_DISABLED
    assert channel.send_calls == []  # never even attempted
    inbox.close()
    prefs.close()


def test_an_enabled_channel_is_attempted(top_level):
    channel = FakeChannel()
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SENT
    assert channel.send_calls == ["user@example.com"]
    inbox.close()
    prefs.close()


def test_preference_is_evaluated_per_channel_independently(top_level):
    """Two channels enabled at the install level, only one opted into by the user — the other
    must be skipped on its own, not follow the first channel's own outcome."""
    email = FakeChannel(name="email")
    sms = FakeChannel(name="sms")
    registry = ChannelRegistry()
    registry.register(email, enabled=True)
    registry.register(sms, enabled=True)
    notifier, inbox, prefs = _notifier(top_level, registry=registry)
    prefs.set("user-1", "email", True)
    # sms deliberately left disabled

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    by_channel = {s.channel: s.outcome for s in result.channel_statuses}
    assert by_channel["email"] is DeliveryOutcome.SENT
    assert by_channel["sms"] is DeliveryOutcome.SKIPPED_DISABLED
    inbox.close()
    prefs.close()


# ---------------------------------------------------------------- channel-failure degradation


def test_channel_not_configured_is_skipped_not_failed(top_level):
    channel = FakeChannel(configured=False)
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED
    assert channel.send_calls == []
    inbox.close()
    prefs.close()


def test_no_resolvable_recipient_is_skipped_not_failed(top_level):
    channel = FakeChannel()
    notifier, inbox, prefs = _notifier(
        top_level, registry=_enabled_registry(channel), recipient_resolver=FakeRecipientResolver(None)
    )
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED
    assert channel.send_calls == []
    inbox.close()
    prefs.close()


def test_one_failing_channel_never_affects_a_sibling_channels_own_attempt(top_level):
    """§4.4's own general statement, applied to two channels at once: a broken email channel
    must not stop the SMS channel from being tried."""
    email = ExplodingChannel()
    sms = FakeChannel(name="sms")
    registry = ChannelRegistry()
    registry.register(email, enabled=True)
    registry.register(sms, enabled=True)
    notifier, inbox, prefs = _notifier(top_level, registry=registry)
    prefs.set("user-1", "email", True)
    prefs.set("user-1", "sms", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    by_channel = {s.channel: s.outcome for s in result.channel_statuses}
    assert by_channel["email"] is DeliveryOutcome.FAILED
    assert by_channel["sms"] is DeliveryOutcome.SENT
    inbox.close()
    prefs.close()


# -------------------------------------------------------------------- §7 bounded retry


def test_a_channel_that_succeeds_on_its_second_attempt_is_retried_not_abandoned(top_level):
    channel = FakeChannel(outcomes=[
        DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED),
        DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT),
    ])
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SENT
    assert result.channel_statuses[0].attempt == 2
    assert len(channel.send_calls) == 2
    inbox.close()
    prefs.close()


def test_retries_are_bounded_at_exactly_three_attempts(top_level):
    """§7/§8: exactly three attempts, never more — a policy this test pins down explicitly
    rather than leaving as an implicit consequence of whatever loop happens to be written."""
    channel = FakeChannel(outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED)])
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert len(channel.send_calls) == 3
    assert result.channel_statuses[0].outcome is DeliveryOutcome.FAILED
    assert result.channel_statuses[0].attempt == 3
    inbox.close()
    prefs.close()


def test_exhausted_retries_escalate_to_staff(top_level):
    """§8: once every attempt on one channel has failed, the failure is surfaced rather than
    silently dropped — `MetricsOnlyEscalator` is the honest current implementation (see
    `dispatch.py`'s own module docstring on why it does not yet raise a real notification),
    but it must still be *invoked*."""
    escalated = []

    class RecordingEscalator(MetricsOnlyEscalator):
        def escalate(self, user_id, channel, notification, attempts):
            escalated.append((user_id, channel, len(attempts)))

    channel = FakeChannel(outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED)])
    notifier, inbox, prefs = _notifier(
        top_level, registry=_enabled_registry(channel), escalator=RecordingEscalator()
    )
    prefs.set("user-1", "email", True)

    run(notifier.notify(NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")))

    assert escalated == [("user-1", "email", 3)]
    inbox.close()
    prefs.close()


def test_a_successful_retry_never_escalates(top_level):
    escalated = []

    class RecordingEscalator(MetricsOnlyEscalator):
        def escalate(self, user_id, channel, notification, attempts):
            escalated.append(channel)

    channel = FakeChannel(outcomes=[
        DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED),
        DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT),
    ])
    notifier, inbox, prefs = _notifier(
        top_level, registry=_enabled_registry(channel), escalator=RecordingEscalator()
    )
    prefs.set("user-1", "email", True)

    run(notifier.notify(NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")))

    assert escalated == []
    inbox.close()
    prefs.close()


def test_metrics_reflect_the_full_dispatch_lifecycle(top_level):
    channel = FakeChannel(outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.FAILED)])
    notifier, inbox, prefs = _notifier(top_level, registry=_enabled_registry(channel))
    prefs.set("user-1", "email", True)

    run(notifier.notify(NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")))

    snapshot = inbox.metrics.snapshot()
    assert snapshot.notifications_created == 1
    assert snapshot.channel_sends_attempted == 3
    assert snapshot.channel_send_retries == 2
    assert snapshot.channel_sends_failed == 1
    assert snapshot.channel_failures_escalated == 1
    inbox.close()
    prefs.close()


def test_default_channel_registry_ships_email_enabled_and_sms_disabled():
    """§4.3: SMS is off by default for a fresh install — a real-cost capability nobody should
    be opted into without a deliberate setup step."""
    from core.notifications.dispatch import default_channel_registry

    registry = default_channel_registry()
    enabled_names = {c.name for c in registry.enabled()}

    assert "email" in enabled_names
    assert "sms" not in enabled_names
    assert registry.get("sms") is not None  # registered, just not enabled


def test_no_recipient_resolver_default_skips_every_channel(top_level):
    """`NoRecipientResolver` is the honest default before Auth's `User` record is wired in —
    every channel degrades to unconfigured rather than a broken address reaching a provider."""
    channel = FakeChannel()
    notifier, inbox, prefs = _notifier(
        top_level, registry=_enabled_registry(channel), recipient_resolver=NoRecipientResolver()
    )
    prefs.set("user-1", "email", True)

    result = run(notifier.notify(
        NotifyRequest(user_id="user-1", category="run_complete", title="t", body="b")
    ))

    assert result.channel_statuses[0].outcome is DeliveryOutcome.SKIPPED_UNCONFIGURED
