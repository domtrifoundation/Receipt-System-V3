"""A disabled channel receives nothing, whatever the notification is (§7, §8).

§7's channel-preference hook has a clause that is easy to read past:

> **Channel-preference test**: confirms a user who disabled a channel genuinely receives
> nothing on it, **including for high-priority notification types**.

The emphasis is the test. Honoring a preference for routine notifications is the easy half;
the failure mode worth guarding is the plausible-sounding exception — "surely a security alert
or a deletion grace-period reminder should still go out by email even if they turned email
off". That reasoning is how a preference becomes advisory, and a user who turned a channel off
and still gets messages on it has been told their setting does not mean what it says.

There is no `priority` field on `NotifyRequest` to test against, and that is itself the design:
§8 resolved per-category channel preferences as out of scope for v1, so the preference is
per-channel and unconditional. What that makes testable — and what these tests assert — is that
**no category can bypass a disabled channel**, exercised specifically with the categories most
likely to tempt someone into adding an exception later.

The in-app record is created regardless, so nothing is lost by honoring the preference: the
user still sees the notification, in the one place they never opted out of. That is what makes
"no exceptions" a defensible policy rather than a dangerous one, and it is asserted here too
rather than assumed from the other test module.
"""

from __future__ import annotations

import pytest

from core.notifications.channels.base import ChannelRegistry
from core.notifications.contracts import (
    DeliveryOutcome,
    DeliveryStatus,
    InboxQuery,
    NotifyRequest,
)
from core.notifications.dispatch import Notifier
from core.notifications.inbox import InboxStore
from core.notifications.preferences import PreferenceStore

from .conftest import FakeChannel, FakeRecipientResolver, run

#: Categories a future maintainer is most likely to argue deserve an exception. Each is a real
#: notification this system genuinely sends, not a hypothetical: an account deletion moving
#: toward its irreversible stage, a device revocation the user may not have initiated, a
#: break-glass grant against their data, a subscription lapsing.
URGENT_LOOKING_CATEGORIES = [
    "account_deletion_grace_period",
    "security_device_revoked",
    "break_glass_access_granted",
    "billing_subscription_past_due",
    "account_recovery_initiated",
]


def _notifier(top_level, channel):
    registry = ChannelRegistry()
    registry.register(channel, enabled=True)
    inbox = InboxStore(top_level)
    preferences = PreferenceStore(top_level)
    notifier = Notifier(
        inbox,
        preferences,
        registry,
        recipient_resolver=FakeRecipientResolver(),
        backoff_seconds=(0.0, 0.0),
    )
    return notifier, inbox, preferences


@pytest.mark.parametrize("category", URGENT_LOOKING_CATEGORIES)
def test_a_disabled_channel_is_skipped_even_for_the_most_urgent_categories(top_level, category):
    """§7's hook, on exactly the notifications that invite an exception.

    Parametrised over real urgent categories rather than one generic case, because the bug
    this guards against is not a blanket failure — it is a special case someone adds for one
    category that seems important enough to justify it.
    """
    channel = FakeChannel(
        outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT)]
    )
    notifier, _inbox, prefs = _notifier(top_level, channel)
    prefs.set("user-1", "email", False)

    result = run(
        notifier.notify(
            NotifyRequest(
                user_id="user-1",
                category=category,
                title="Something important",
                body="acted on your account",
            )
        )
    )

    assert channel.send_calls == []
    assert not any(s.channel == "email" for s in result.channel_statuses if s.outcome is DeliveryOutcome.SENT)


@pytest.mark.parametrize("category", URGENT_LOOKING_CATEGORIES)
def test_the_user_still_gets_the_urgent_notification_in_app(top_level, category):
    """Why honoring the preference absolutely is safe rather than reckless.

    The user has not been kept in the dark — the in-app record is always created (§7's other
    hook). They opted out of one delivery path, not out of being told. If this assertion ever
    failed, the case for "no exceptions" above would genuinely weaken.
    """
    channel = FakeChannel(
        outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT)]
    )
    notifier, inbox, prefs = _notifier(top_level, channel)
    prefs.set("user-1", "email", False)

    result = run(
        notifier.notify(
            NotifyRequest(
                user_id="user-1", category=category, title="Important", body="details"
            )
        )
    )

    assert result.notification is not None
    assert result.notification.category == category
    stored = inbox.query(InboxQuery(user_id="user-1", requesting_user_id="user-1"))
    assert any(n.category == category for n in stored.notifications)


def test_a_channel_never_configured_at_all_is_treated_as_opted_out(top_level):
    """The default has to be off, not on.

    A user who never touched their settings has not consented to email or SMS. Defaulting to
    enabled would make the first urgent notification the moment they discover the channel
    exists — the opposite of an opt-in.
    """
    channel = FakeChannel(
        outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT)]
    )
    notifier, _inbox, _prefs = _notifier(top_level, channel)

    run(
        notifier.notify(
            NotifyRequest(
                user_id="never-configured",
                category="security_device_revoked",
                title="t",
                body="b",
            )
        )
    )

    assert channel.send_calls == []


def test_re_enabling_a_channel_takes_effect_on_the_very_next_notification(top_level):
    """The preference is read live, not cached at construction.

    A cached answer would leave a user who just turned email back on still receiving nothing,
    with no way to tell whether the setting took.
    """
    channel = FakeChannel(
        outcomes=[
            DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT),
            DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT),
        ]
    )
    notifier, _inbox, prefs = _notifier(top_level, channel)
    prefs.set("user-1", "email", False)
    run(notifier.notify(NotifyRequest(user_id="user-1", category="c", title="t", body="b")))
    assert channel.send_calls == []

    prefs.set("user-1", "email", True)
    run(notifier.notify(NotifyRequest(user_id="user-1", category="c", title="t", body="b")))

    assert len(channel.send_calls) == 1


def test_one_user_s_preference_never_governs_another_s_delivery(top_level):
    """Preferences are per-user; a shared read would leak one user's choice onto another."""
    channel = FakeChannel(
        outcomes=[DeliveryStatus(channel="email", outcome=DeliveryOutcome.SENT)]
    )
    notifier, _inbox, prefs = _notifier(top_level, channel)
    prefs.set("user-1", "email", False)
    prefs.set("user-2", "email", True)

    run(notifier.notify(NotifyRequest(user_id="user-2", category="c", title="t", body="b")))

    assert len(channel.send_calls) == 1
