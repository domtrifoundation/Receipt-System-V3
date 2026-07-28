"""Interface API contracts (`v3-deepdive-14-interface-api.md` §3).

**Phase 1 scope note, so this file's presence is not mistaken for Interface being built.**
Phase 1 scaffolds every API and implements only Agent Control. `MenuItemSpec` is here — and
only `MenuItemSpec` — because Agent Control's `find_setting` tool genuinely resolves against
declarative menu data, and a tool returning a fabricated answer would not be a working
implementation. This is a contract type plus the declarative data beside it, not screen or
business logic; the TUI, `MenuScreen`, theming, and i18n all remain Phase 2's work.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MenuItemSpec:
    """One entry in the declarative menu tree (`docs/PRINCIPLES.md` §1.4).

    Any screen that is fundamentally "a list of labeled actions" is expressed as this data
    and rendered through one generic `MenuScreen` — never a bespoke screen class. Adding a
    simple menu item is an edit to data, never new screen code.
    """

    path: str
    """The current dotted path, e.g. `settings.general.tenancy_mode`."""

    label: str
    tooltip: str

    target: str
    """Dotted API-call reference, e.g. `auth.revoke_session`. A menu-data integrity check
    fails CI if this does not resolve to a registered RPC — a stale entry pointing at a
    renamed call should not be discovered by a user clicking a dead button."""

    kind: str
    """`action` | `bool` | `number` | `text` | `choice` | `submenu`."""

    docs_ref: str | None = None

    former_paths: tuple[str, ...] = field(default_factory=tuple)
    """Prior dotted path(s) this setting lived at before a reorganization moved it.

    Appended to rather than replaced, so a saved deep-link, a stale doc reference, or plain
    muscle memory still resolves to the setting's new home instead of silently failing.
    Never pruned automatically — the same "don't silently drop old references" instinct
    behind Reimport's own three-way diff.
    """
