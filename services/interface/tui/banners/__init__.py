"""Version-codename ASCII banners (`v3-plan-02-architecture.md`'s own "Version codename
ASCII banners" note; `v3-deepdive-14-interface-api.md` §5).

One plain-text file per `MM`, keyed to the major segment alone so every `x03.xx.xx`
release reuses the same Zircon art without regeneration — old codename files are retained
indefinitely, never pruned, since an LTSC channel can genuinely still be running an older
major version's own banner concurrently with newer channels elsewhere in the fleet.

Shown two ways: large, alongside the Boot Sequence screen's own progress indicator
(`custom_screens/boot_sequence.py`), and small/header-style, persistent atop the TUI's
main menu navigation (`app.py`'s root `MenuScreen`).
"""

from __future__ import annotations

from pathlib import Path

from common.version import PROGRAM_VERSION, codename, major_segment

_BANNERS_DIR = Path(__file__).parent


def ascii_banner(version: str = PROGRAM_VERSION) -> str:
    """The full ASCII-art banner for `version`'s own `MM`, or a plain text fallback if no
    `.txt` asset exists yet for it — a missing banner file degrades to readable text, it
    never blanks the screen (`docs/PRINCIPLES.md` §4.4)."""
    name = codename(version)
    if name is None:
        return ""
    path = _BANNERS_DIR / f"{name.lower()}.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").rstrip("\n")
    return name.upper()


def header_line(version: str = PROGRAM_VERSION) -> str:
    """The compact, header-style form for the persistent top-of-menu banner — just the
    codename plus the running version, never the full ASCII art (too tall for a header
    that has to stay out of the way of actual navigation)."""
    name = codename(version)
    if name is None:
        return version
    return f"{name.upper()} — {version}"


__all__ = ["ascii_banner", "header_line", "major_segment"]
