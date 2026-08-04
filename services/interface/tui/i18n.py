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
    "fleet.title": "Fleet & Updates",
    "fleet.input_placeholder": "comma-separated versions, or one version for restart",
    "fleet.apply": "Apply",
    "fleet.not_connected": "Not connected to a running Supervisor.",
    "fleet.single_instance_tag": "(single-instance)",
    "fleet.multi_instance_tag": "(multi-version)",
    "fleet.detail.single_instance": "{service} — single-instance. Currently running: {current}. Enter a target version and Apply to restart.",
    "fleet.detail.multi_instance": "{service} — available: {available}. Running: {running}.",
    "fleet.detail.none_running": "none",
    "fleet.detail.none_available": "none",
    "fleet.status.empty_version": "Enter a target version first.",
    "fleet.status.saved": "Saved available versions for {service}.",
    "fleet.status.restart_ok": "{service} restarted on {version}.",
    "fleet.status.restart_failed": "{service} restart failed: {detail}",
    "restart.title": "Restarting {service} to {version}...",
    "restart.stage.confirming_target": "Confirming target version...",
    "restart.stage.stopping_old": "Stopping current instance...",
    "restart.stage.launching_new": "Launching new instance...",
    "restart.stage.waiting_healthy": "Waiting for health check...",
    "restart.stage.complete": "Restart complete.",
    "restart.stage.failed": "Restart failed: {detail}",
    "find_setting.title": "Find a Setting",
    "find_setting.placeholder": "Type to search settings...",
    "find_setting.no_matches": "No settings match {query!r}.",
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
    "fleet.title": "Fleet at Mga Update",
    "fleet.input_placeholder": "mga bersyon na pinaghihiwalay ng kuwit, o iisang bersyon para sa restart",
    "fleet.apply": "I-apply",
    "fleet.not_connected": "Hindi konektado sa isang tumatakbong Supervisor.",
    "fleet.single_instance_tag": "(single-instance)",
    "fleet.multi_instance_tag": "(multi-version)",
    "fleet.detail.single_instance": "{service} — single-instance. Kasalukuyang tumatakbo: {current}. Maglagay ng target na bersyon at pindutin ang Apply para mag-restart.",
    "fleet.detail.multi_instance": "{service} — available: {available}. Tumatakbo: {running}.",
    "fleet.detail.none_running": "wala",
    "fleet.detail.none_available": "wala",
    "fleet.status.empty_version": "Maglagay muna ng target na bersyon.",
    "fleet.status.saved": "Na-save ang mga available na bersyon para sa {service}.",
    "fleet.status.restart_ok": "Na-restart ang {service} papuntang {version}.",
    "fleet.status.restart_failed": "Nabigo ang restart ng {service}: {detail}",
    "restart.title": "Nire-restart ang {service} papuntang {version}...",
    "restart.stage.confirming_target": "Kinukumpirma ang target na bersyon...",
    "restart.stage.stopping_old": "Hinihinto ang kasalukuyang instance...",
    "restart.stage.launching_new": "Sinisimulan ang bagong instance...",
    "restart.stage.waiting_healthy": "Hinihintay ang health check...",
    "restart.stage.complete": "Tapos na ang restart.",
    "restart.stage.failed": "Nabigo ang restart: {detail}",
    "find_setting.title": "Maghanap ng Setting",
    "find_setting.placeholder": "Mag-type para maghanap ng setting...",
    "find_setting.no_matches": "Walang tumugmang setting para sa {query!r}.",
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
