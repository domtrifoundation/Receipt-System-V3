"""The one source of truth for the program version (`docs/MAINTENANCE.md` §1).

Before this file existed, `x00.00.03` lived only in git commit-message subjects. That is
not sufficient for what the architecture already assumes: Health API's heartbeat carries
the running version so Watchdog can report which version each service instance is on
(`docs/PROCESS_TOPOLOGY.md` §7, `v3-deepdive-20-health-api.md`), and Interface API's
codename banner is keyed off `MM` (`v3-plan-02-architecture.md`). Both need a real value
the running program can read, not a string in a commit log.

This module is deliberately the same shape as `common/frozen_dict.py`: one small file in
`common/` for something genuinely cross-cutting, imported by anything that needs it, so
there is exactly one place to change.

## The scheme

`x<MM>.<mm>.<pp> [code-repo commit hash]`

- `MM` — product generation. V1=01, V2=02, V3=03, each with a codename.
- `mm` — increments per merged PR.
- `pp` — increments per commit within the current PR. Two digits, which is what the
  99-commit-per-PR cap exists to keep true (`docs/PRINCIPLES.md` §3.1).

Pre-release work starts at `x00.00.00` and ticks `pp` per commit from there. `x03.00.00`
(Zircon) is a deliberate jump taken once the program is genuinely feature-complete and
validated — never reached by ordinary incrementing.

## Ticking this

**Every commit ticks `PROGRAM_VERSION`'s `pp`** — including a process-only commit that
changes nothing but a typo. A commit that changes a given API's own behavior additionally
ticks that API's own `aXX.XX.XX` line in its own `CLAUDE.md`, in the same commit. A commit
touching several APIs ticks this constant once and each touched API's own line once each.
`CONTRIBUTING.md` states this as the standing repo practice; this docstring is the
mechanism half of it.

## Why the commit hash is not a constant here

`mm.pp` are sequential counters, not content-addressable, so the scheme pins the exact
build with a commit hash. That hash cannot be a constant in a file the commit itself
contains — the value would have to be known before the commit that carries it exists.
It is resolved at runtime instead, from the release directory Update API already names
`<version>_<commit-hash>` (`docs/MAINTENANCE.md` §2). A dev checkout is not inside a
release directory, so it degrades to `None` rather than failing — the same graceful
degradation posture as everything else (`docs/PRINCIPLES.md` §4.4).
"""

from __future__ import annotations

from pathlib import Path

#: The running program version. Ticked on every commit — see the module docstring.
PROGRAM_VERSION = "x00.00.70"

#: Codename for the current `MM`, keyed to `MM` alone so every `x03.xx.xx` release reuses
#: one banner asset without regeneration (`v3-plan-02-architecture.md`). `"00"` is a real,
#: deliberate placeholder — not a future major generation's own name — for the pre-Zircon
#: development period specifically, so the TUI's banner has something honest to show
#: (`"BETA"`) instead of rendering nothing while this is the only thing anyone's running.
#: Retired the moment `x03.00.00` actually ships; `"03"` onward are the real generations.
MAJOR_CODENAMES = {
    "00": "Beta",
    "03": "Zircon",
    "04": "Yttrium",
    "05": "Xenotime",
    "06": "Wulfenite",
}


def major_segment(version: str = PROGRAM_VERSION) -> str:
    """Return the `MM` segment of a program version string (`"x03.01.02"` -> `"03"`)."""
    return version.removeprefix("x").split(".", 1)[0]


def codename(version: str = PROGRAM_VERSION) -> str | None:
    """Return the codename for a version's `MM`, or `None` if that `MM` has none yet.

    Every `MM` this project currently ships or pre-ships has one — `"00"` maps to the
    real, deliberate `"Beta"` placeholder above. `None` stays the return type for any
    future `MM` not yet added to `MAJOR_CODENAMES`, not for pre-release specifically.
    """
    return MAJOR_CODENAMES.get(major_segment(version))


def resolve_commit_hash(module_path: Path | None = None) -> str | None:
    """Best-effort resolution of the commit hash this code was cloned at.

    Update API clones every release into a directory named `<version>_<commit-hash>`
    (`docs/MAINTENANCE.md` §2), so the hash is already recorded in the filesystem path a
    running service was launched from — no git subprocess, no build-time injection step,
    and nothing that can disagree with what Supervisor actually launched.

    Returns `None` for a dev checkout, which is not inside a release directory. Callers
    must treat that as "unknown," never as an error: `docs/MAINTENANCE.md` §5 is explicit
    that a plain `git clone` is a legitimate developer state.
    """
    here = (module_path or Path(__file__)).resolve()
    prefix = f"{PROGRAM_VERSION}_"
    for parent in here.parents:
        if parent.name.startswith(prefix):
            candidate = parent.name[len(prefix) :]
            if candidate:
                return candidate
    return None


def full_version(module_path: Path | None = None) -> str:
    """The version in the scheme's own display form, commit hash included when known.

    `"x03.00.00 [a1b2c3d]"` inside a release directory; bare `"x03.00.00"` in a dev
    checkout. This is what Health API's heartbeat reports and what the TUI displays.
    """
    commit = resolve_commit_hash(module_path)
    return f"{PROGRAM_VERSION} [{commit}]" if commit else PROGRAM_VERSION


__all__ = [
    "PROGRAM_VERSION",
    "MAJOR_CODENAMES",
    "codename",
    "full_version",
    "major_segment",
    "resolve_commit_hash",
]
