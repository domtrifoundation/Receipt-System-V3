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
    "models.title": "Inference Models",
    "models.provision": "Provision Selected",
    "models.set_device": "Set Device (restart to apply)",
    "models.device_select_prompt": "Execution provider...",
    "models.not_installable_tag": " — no prebuilt wheel, generation-only",
    "models.not_connected": "Not connected to a running Inference service.",
    "models.detail": "{name} — {status} ({device})",
    "models.status.not_downloaded": "{name} — not downloaded ({device})",
    "models.status.partial": "{name} — partially downloaded ({device})",
    "models.status.ready": "{name} — ready ({device})",
    "models.status.downloading": "{name} — downloading... ({device})",
    "models.status.failed": "{name} — last download failed ({device})",
    "models.status.already_ready": "{name} is already downloaded.",
    "models.status.pick_a_device_first": "Select a preset and a device first.",
    "models.provision_ok": "{name} downloaded successfully.",
    "models.provision_failed": "{name} download failed: {detail}",
    "models.device_set_ok": "{name} will use {device} on next Inference restart.",
    "models.device_set_failed": "Couldn't set device for {name}: {detail}",
    "models.provisioning.title": "Downloading {name}...",
    "models.provisioning.done": "Download complete.",
    "models.provisioning.failed": "Download failed: {detail}",
    "models.provisioning.file_progress": "{file}: {downloaded}/{total} bytes ({completed}/{files_total} files)",
    "monitor.not_connected": "Not connected to a running Supervisor.",
    "monitor.error": "Could not read fleet status: {detail}",
    "monitor.release": "Channel: {channel}\nRelease: {release_dir}\nActivated: {activated_at}",
    "monitor.services.title": "Services ({count})",
    "monitor.instances.title": "Running instances ({count})",
    "monitor.instances.none": "No multi-version instances currently tracked.",
    "monitor.runs.unavailable": "Runs: not available yet — Execution Core has no "
                                 "list-active-runs RPC (tracked in services/interface/CLAUDE.md).",
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
    "models.title": "Mga Inference Model",
    "models.provision": "I-download ang Napili",
    "models.set_device": "Itakda ang Device (mag-re-restart para umepekto)",
    "models.device_select_prompt": "Execution provider...",
    "models.not_installable_tag": " — walang handa nang wheel, generation-only",
    "models.not_connected": "Hindi konektado sa isang tumatakbong Inference service.",
    "models.detail": "{name} — {status} ({device})",
    "models.status.not_downloaded": "{name} — hindi pa na-download ({device})",
    "models.status.partial": "{name} — bahagyang na-download ({device})",
    "models.status.ready": "{name} — handa na ({device})",
    "models.status.downloading": "{name} — dina-download... ({device})",
    "models.status.failed": "{name} — nabigo ang huling pag-download ({device})",
    "models.status.already_ready": "Na-download na ang {name}.",
    "models.status.pick_a_device_first": "Pumili muna ng preset at device.",
    "models.provision_ok": "Matagumpay na na-download ang {name}.",
    "models.provision_failed": "Nabigo ang pag-download ng {name}: {detail}",
    "models.device_set_ok": "Gagamit ang {name} ng {device} sa susunod na Inference restart.",
    "models.device_set_failed": "Hindi maitakda ang device para sa {name}: {detail}",
    "models.provisioning.title": "Dina-download ang {name}...",
    "models.provisioning.done": "Tapos na ang pag-download.",
    "models.provisioning.failed": "Nabigo ang pag-download: {detail}",
    "models.provisioning.file_progress": "{file}: {downloaded}/{total} bytes ({completed}/{files_total} files)",
    "monitor.not_connected": "Hindi konektado sa isang tumatakbong Supervisor.",
    "monitor.error": "Hindi mabasa ang katayuan ng fleet: {detail}",
    "monitor.release": "Channel: {channel}\nRelease: {release_dir}\nNa-activate: {activated_at}",
    "monitor.services.title": "Mga Serbisyo ({count})",
    "monitor.instances.title": "Mga tumatakbong instance ({count})",
    "monitor.instances.none": "Walang multi-version instance na sinusubaybayan sa ngayon.",
    "monitor.runs.unavailable": "Mga run: hindi pa available — walang list-active-runs RPC "
                                 "ang Execution Core (naka-track sa services/interface/CLAUDE.md).",
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
