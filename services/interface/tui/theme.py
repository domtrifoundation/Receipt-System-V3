"""Theme config (`v3-deepdive-14-interface-api.md` §1: theming is cross-cutting, not a
sub-API — structured here rather than spun out into its own package)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeConfig:
    """One named color/style scheme for the TUI. Textual's own `App.theme` name is set
    from `textual_theme_name` — this wrapper exists so `settings.interface.theme` (a
    dotted config key) has a real dataclass to resolve against rather than a bare string.
    """

    name: str
    textual_theme_name: str


DEFAULT_THEME = ThemeConfig(name="default", textual_theme_name="textual-dark")

#: Every theme this build ships. `settings.interface.theme`'s own `choice` menu entry
#: resolves against this — adding a theme is adding an entry here, never new screen code.
THEMES: tuple[ThemeConfig, ...] = (
    DEFAULT_THEME,
    ThemeConfig(name="light", textual_theme_name="textual-light"),
    ThemeConfig(name="high-contrast", textual_theme_name="textual-ansi"),
)


def theme_by_name(name: str) -> ThemeConfig:
    for theme in THEMES:
        if theme.name == name:
            return theme
    return DEFAULT_THEME
