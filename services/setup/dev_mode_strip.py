"""`strip_development_content()` — removing development-only content from a release clone.

Shared plumbing with two callers (`docs/PRINCIPLES.md` §1.5, and `v3-deepdive-11-setup-api.md`
§4.1's own statement of it): Setup API's finalize routine strips the *first* clone, and Update
API's `release_manager.py` strips every subsequent one, since every update is a fresh clone
rather than a pull. One implementation, because two copies drift — which is the same reasoning
`venv_provisioning.py` sits here under for the same two callers.

**This module owns the classification lists, and `.github/scripts/check_stripped_content_list.py`
imports them from here — the reverse of what that script's own comment used to claim.** That
comment said Setup's `dev_mode_strip.py` imports the constants from the CI script "so there is
exactly one place this list is actually defined." The goal was right; the direction could not
work, for two independent reasons:

1. `.github/` is itself in `DEV_ONLY_STRIP_LIST`. This function would have been importing its
   own strip list out of the directory it is about to delete. Setup is idempotent and safely
   re-runnable by design (`v3-deepdive-11-setup-api.md` §4), and every Update API clone strips
   again — so on the second run the import target is simply gone.
2. `.github/scripts/` is not an importable package and is not on any service's path.

`services/` ships (it is in `SHIPPED_ALLOWLIST`), so defining the lists here keeps them
reachable at exactly the moment they are needed, and CI still validates against the one real
definition rather than a copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .contracts import StripReport
from .errors import StripError, StripErrorCode

__all__ = [
    "DEV_ONLY_STRIP_LIST",
    "NESTED_STRIP_FILENAMES",
    "SHIPPED_ALLOWLIST",
    "strip_development_content",
]

# Present in a normal end-user install. Anything genuinely new and user-facing (a new top-level
# data directory, a new launcher script) gets added here explicitly, in the same PR that adds it.
SHIPPED_ALLOWLIST = frozenset(
    {
        "core",
        "services",
        "webapp",
        "config",
        "data",
        "models",
        "start.bat",
        "start.sh",
        "LICENSE",
        "README.md",
        ".gitignore",
        # --- classified in Phase 1, when the real tree first existed -------------
        "supervisor",  # Supervisor is *deployed* outside every release clone
        #                (docs/PROCESS_TOPOLOGY.md §1), but its source still ships inside the
        #                clone the installer pulls — that is where the top-level copy is placed
        #                from. Stripping it would leave nothing to launch with.
        "common",  # runtime code imported by every service (common/frozen_dict.py is the one
        #            centralized FrozenDict shim, docs/PRINCIPLES.md §2.1; common/requirements.txt
        #            is the shared runtime base every service venv installs first).
        "assets",  # codename ASCII art, rendered at runtime by the Boot Sequence screen and the
        #            persistent TUI header, retained for every codename indefinitely
        #            (docs/MAINTENANCE.md §1) — a running instance genuinely needs its banner.
        "requirements.txt",  # the aggregate/dev-convenience set. Production venvs are NOT built
        #                      from it — per-service venvs compose common/requirements.txt plus
        #                      each service's own (docs/VENV_AND_IMPORTS.md §4), and those ship
        #                      inside core/ and services/ above. Still shipped, because a running
        #                      instance is a clone and a re-provision runs from one.
    }
)

# Stripped by strip_development_content() in normal mode.
DEV_ONLY_STRIP_LIST = frozenset(
    {
        "CONTRIBUTING.md",
        "docs",
        "tests",
        ".github",  # covers PULL_REQUEST_TEMPLATE/, workflows/, scripts/, instructions/ — the
        #             entire tree, not enumerated file-by-file, so a NEW file added anywhere
        #             under .github/ is automatically covered without a list update.
        "pyproject.toml",  # dev/build tooling config, not runtime code
        "requirements-dev.txt",
        # --- classified in Phase 1, when the real tree first existed -------------
        "pytest.ini",  # test-runner config; meaningless without tests/, already dev-only.
        "CLAUDE.md",  # development guidance for LLM-assisted sessions. Nothing in a running
        #              end-user instance reads it. Worth being explicit about *why* this is
        #              dev-only despite being load-bearing: docs/CLAUDE_MD_GUIDE.md §2.1 makes
        #              these the artifact that survives the deep-dive corpus being removed —
        #              important to development, irrelevant at runtime, different questions.
        # --- classified in Phase 1.5, when multi-version validation was set up ---------
        "noxfile.py",  # drives `nox -s forward_compat` — a dev-time test-runner invocation,
        #                same category as pytest.ini, never invoked by the shipped program.
    }
)

#: Stripped wherever they appear, not just at the top level.
#:
#: `check_stripped_content_list.py` flagged this as a real gap its own top-level check could not
#: see: 52 `CLAUDE.md` files live nested under `core/`, `services/`, `webapp/` and `supervisor/`,
#: all of which ship. A top-level entry name cannot express "strip this filename wherever it
#: appears," so without this rule every end-user install would carry 52 development-only files it
#: will never read. That note named this module as the place to close the gap; this is it.
NESTED_STRIP_FILENAMES = frozenset({"CLAUDE.md"})


def strip_development_content(clone_dir: Path, dev_mode: bool) -> StripReport:
    """Remove development-only content from `clone_dir`, unless this is a developer install.

    `dev_mode=True` strips nothing at all and reports an empty result — a contributor working in
    the clone needs the full docs corpus, test tree and CI scaffolding. The flag is recorded once
    at first clone as persistent top-level config and read by every later clone, so a
    developer-mode install stays developer-mode across updates without re-asking
    (`v3-deepdive-11-setup-api.md` §4.1).

    Idempotent: an already-stripped clone reports everything as `skipped_absent` and succeeds,
    rather than failing on the second pass. This matters concretely because Update API strips
    every fresh clone and Setup is explicitly re-runnable.

    Errors are data — a single unremovable entry does not abort the rest.
    """
    if dev_mode:
        return StripReport(removed=(), skipped_absent=())

    root = clone_dir.resolve()
    removed: list[str] = []
    absent: list[str] = []
    errors: list[StripError] = []

    for entry in sorted(DEV_ONLY_STRIP_LIST):
        target = (root / entry).resolve()

        # The top-level installation directory — config, user data, model weights — is a
        # *sibling* of every release clone (docs/PRINCIPLES.md §1.6), so an escape here is the
        # difference between deleting docs/ and deleting a user's receipts. Refuse, never guess.
        if root not in target.parents:
            errors.append(
                StripError(
                    code=StripErrorCode.PATH_ESCAPES_CLONE,
                    entry=entry,
                    detail=f"{target} is not inside {root}",
                )
            )
            continue

        if not target.exists():
            absent.append(entry)
            continue

        error = _remove(target, entry)
        if error is not None:
            errors.append(error)
        else:
            removed.append(entry)

    nested_removed, nested_errors = _strip_nested(root)
    removed.extend(nested_removed)
    errors.extend(nested_errors)

    return StripReport(
        removed=tuple(sorted(removed)),
        skipped_absent=tuple(sorted(absent)),
        errors=tuple(errors),
    )


def _strip_nested(root: Path) -> tuple[list[str], list[StripError]]:
    """Remove `NESTED_STRIP_FILENAMES` anywhere beneath the clone root.

    Runs after the top-level pass deliberately: `docs/` and `tests/` are already gone by then, so
    this walks a meaningfully smaller tree and cannot trip over a file inside a directory the
    previous pass is about to delete.
    """
    removed: list[str] = []
    errors: list[StripError] = []

    for filename in sorted(NESTED_STRIP_FILENAMES):
        for path in sorted(root.rglob(filename)):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            error = _remove(path, rel)
            if error is not None:
                errors.append(error)
            else:
                removed.append(rel)

    return removed, errors


def _remove(target: Path, entry: str) -> StripError | None:
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return StripError(
            code=StripErrorCode.REMOVAL_FAILED, entry=entry, detail=f"{type(exc).__name__}: {exc}"
        )
    return None
