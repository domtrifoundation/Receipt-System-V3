"""Localization (`v3-deepdive-14-interface-api.md` §6). English and Tagalog ship at
launch; the mechanism is built for genuinely open-ended future languages — adding a
locale is adding a `FrozenDict` entry to `TRANSLATIONS` below, never a code change to any
screen. Every user-facing string in a screen or menu-data entry routes through `t()`,
never a raw hardcoded string (`docs/PRINCIPLES.md` §1.4, applied to text specifically).

Content-scope note, not a mechanism gap: this file seeds the key set the TUI shell
(boot screen, main menu, settings, credits) actually renders today. Filling in every
future screen's strings, and the Tagalog-specific judgment calls §6.2 flags (VAT/TIN/
Official Receipt left in English-business-context form vs. translated), is real ongoing
content work as each screen is built — not something the mechanism itself is missing.
"""

from __future__ import annotations

from common.frozen_dict import FrozenDict

DEFAULT_LOCALE = "en-PH"

_EN = {
    "app.title": "DOMTRI / Resibo",
    "boot.title": "Starting the service cluster...",
    "boot.skip_animation": "Skip animation",
    "boot.stage.launching": "Launching {service}...",
    "boot.stage.healthy": "{service} is healthy",
    "boot.stage.failed": "{service} failed to start: {detail}",
    "boot.complete": "All services are up.",
    "menu.back": "Back",
    "menu.quit": "Quit",
    "menu.settings": "Settings",
    "menu.fleet": "Fleet & Updates",
    "menu.credits": "Credits",
    "menu.find_setting": "Find a setting...",
    "credits.title": "Credits & Open-Source Notices",
    "credits.scroll_hint": "Scroll for the full third-party license list.",
}

_TL = {
    "app.title": "DOMTRI / Resibo",
    "boot.title": "Sinisimulan ang service cluster...",
    "boot.skip_animation": "Laktawan ang animation",
    "boot.stage.launching": "Sinisimulan ang {service}...",
    "boot.stage.healthy": "Maayos na ang {service}",
    "boot.stage.failed": "Nabigo ang {service}: {detail}",
    "boot.complete": "Handa na ang lahat ng serbisyo.",
    "menu.back": "Bumalik",
    "menu.quit": "Lumabas",
    "menu.settings": "Mga Setting",
    "menu.fleet": "Fleet & Mga Update",
    "menu.credits": "Mga Credit",
    "menu.find_setting": "Maghanap ng setting...",
    "credits.title": "Mga Credit at Open-Source Notice",
    "credits.scroll_hint": "Mag-scroll para sa buong listahan ng third-party license.",
}

#: One `FrozenDict` per shipped locale (`docs/PRINCIPLES.md` §2.1.1 — module-level
#: constant lookup tables are `FrozenDict` too). Keyed by BCP-47-ish locale tag.
TRANSLATIONS = FrozenDict(
    {
        "en-PH": FrozenDict(_EN),
        "tl-PH": FrozenDict(_TL),
    }
)


def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs: object) -> str:
    """Resolve `key` in `locale`, falling back to `DEFAULT_LOCALE` then to the bare key.

    Never raises on a missing key — a screen showing `"menu.qutt"` (a typo) is a bug worth
    seeing on screen and fixing, not a crash that takes the whole TUI down with it
    (`docs/PRINCIPLES.md` §4.2's fail-closed rule is for security checks; a missing
    translation string is squarely the "degrade gracefully everywhere else" half).
    """
    table = TRANSLATIONS.get(locale, TRANSLATIONS[DEFAULT_LOCALE])
    text = table.get(key) or TRANSLATIONS[DEFAULT_LOCALE].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


__all__ = ["DEFAULT_LOCALE", "TRANSLATIONS", "t"]
