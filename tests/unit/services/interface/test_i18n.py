"""`t()` — real key resolution, formatting, and graceful fallback."""

from __future__ import annotations

from services.interface.tui.i18n import DEFAULT_LOCALE, TRANSLATIONS, t


def test_default_locale_resolves_a_known_key():
    assert t("menu.settings") == "Settings"


def test_tagalog_locale_resolves_a_different_string():
    assert t("menu.settings", "tl-PH") == "Mga Setting"


def test_format_kwargs_are_applied():
    text = t("boot.stage.healthy", DEFAULT_LOCALE, service="ocr")
    assert text == "ocr is healthy"


def test_unknown_key_falls_back_to_the_bare_key_rather_than_raising():
    assert t("this.key.does.not.exist") == "this.key.does.not.exist"


def test_unknown_locale_falls_back_to_default_locale():
    assert t("menu.settings", "fr-FR") == "Settings"


def test_every_shipped_locale_has_the_same_key_set():
    """A locale missing a key silently degrades to English per-key (acceptable), but a
    locale that's missing a large chunk of the key set is a real content gap worth CI
    catching rather than discovering one string at a time in the TUI."""
    key_sets = {locale: set(table.keys()) for locale, table in TRANSLATIONS.items()}
    assert len(key_sets) >= 2
    reference = key_sets[DEFAULT_LOCALE]
    for locale, keys in key_sets.items():
        assert keys == reference, f"{locale} has a different key set than {DEFAULT_LOCALE}"
