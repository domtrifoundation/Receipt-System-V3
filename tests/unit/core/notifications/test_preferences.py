"""Per-user channel preferences (§5) — the opt-in guarantee, and preference honoring.

The load-bearing property here is that **`is_enabled` never defaults to `True`**: a user this
store has never seen a row for reads back as disabled on every channel, which is what makes
"a user who never enabled email/SMS delivery only ever sees in-app notifications" (deep-dive
§5) an actual guarantee rather than a default that could silently flip the day a new channel is
added to `KNOWN_CHANNELS`.
"""

from __future__ import annotations

from core.notifications.contracts import KNOWN_CHANNELS
from core.notifications.preferences import PreferenceStore


def test_a_never_configured_channel_reads_back_disabled(preferences):
    assert preferences.is_enabled("user-1", "email") is False
    assert preferences.is_enabled("user-1", "sms") is False


def test_get_all_returns_one_entry_per_known_channel_even_with_no_rows(preferences):
    result = preferences.get_all("user-1")
    assert result.ok
    assert {p.channel for p in result.preferences} == set(KNOWN_CHANNELS)
    assert all(not p.enabled for p in result.preferences)


def test_set_then_get_round_trips(preferences):
    written = preferences.set("user-1", "email", True, contact_override="alt@example.com")

    assert written.ok
    assert written.preference.enabled is True
    assert preferences.is_enabled("user-1", "email") is True
    result = preferences.get_all("user-1")
    email_pref = next(p for p in result.preferences if p.channel == "email")
    assert email_pref.enabled is True
    assert email_pref.contact_override == "alt@example.com"


def test_setting_one_channel_never_enables_the_other(preferences):
    """Opt-in is per-channel, not "the user opted into notifications generally" — enabling
    email must not quietly turn on SMS too."""
    preferences.set("user-1", "email", True)

    assert preferences.is_enabled("user-1", "email") is True
    assert preferences.is_enabled("user-1", "sms") is False


def test_re_setting_a_preference_updates_rather_than_duplicates(preferences):
    preferences.set("user-1", "email", True)
    preferences.set("user-1", "email", False)

    result = preferences.get_all("user-1")
    email_prefs = [p for p in result.preferences if p.channel == "email"]
    assert len(email_prefs) == 1
    assert email_prefs[0].enabled is False


def test_unknown_channel_is_rejected(preferences):
    result = preferences.set("user-1", "carrier_pigeon", True)
    assert not result.ok
    assert result.error_code == "INVALID_PREFERENCE"


def test_preferences_are_isolated_per_user(preferences):
    preferences.set("user-1", "sms", True)

    assert preferences.is_enabled("user-1", "sms") is True
    assert preferences.is_enabled("user-2", "sms") is False


def test_empty_user_id_is_an_invalid_query(preferences):
    result = preferences.get_all("")
    assert not result.ok
    assert result.error_code == "INVALID_PREFERENCE"
