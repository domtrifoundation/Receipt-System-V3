"""The finalize routine — §4/§7.4's own "restated precisely" sequence, made real.

Runs *inside* a fresh clone, after the ZIP-to-`git clone` handoff the top-level `setup.bat`/
`setup.sh` script performs before any Python code in this clone is even reachable (§4's own
statement of that boundary — "a real consequence of the Keymaster license-key timing," a small
amount of logic the bootstrap script itself must carry). This module owns everything after that
handoff: idempotent, safely re-runnable, four steps in order.

**Shared with Update API's `release_manager.py`**, exactly like `dev_mode_strip.py` and
`venv_provisioning.py` before it (`docs/PRINCIPLES.md` §1.5) — Setup finalizes the first clone,
Update finalizes every subsequent one, one implementation so the two cannot drift.
"""

from __future__ import annotations

from pathlib import Path

from . import dev_mode_strip, venv_provisioning
from .contracts import BootstrapReport, WebappBuilder

__all__ = [
    "TOP_LEVEL_SETUP_FILES",
    "cleanup_top_level_setup_files",
    "finalize_clone",
]

#: §4's own list, exact: "setup.bat/setup.sh/setup-dev.bat/setup-dev.sh/.ps1 files." A narrow,
#: exact-name allowlist rather than a glob — this function deletes files from the TOP-LEVEL
#: install directory, a sibling of every release clone and the home of real user data
#: (`docs/PRINCIPLES.md` §1.6); a glob here is exactly the kind of thing that quietly grows to
#: match something it should not.
TOP_LEVEL_SETUP_FILES: frozenset[str] = frozenset(
    {
        "setup.bat",
        "setup.sh",
        "setup-dev.bat",
        "setup-dev.sh",
        "setup.ps1",
        "setup-dev.ps1",
    }
)


def cleanup_top_level_setup_files(install_root: Path) -> tuple[str, ...]:
    """§4's own rule: "setup files are cleaned out of the top level once their job is done, not
    left there permanently" — because a single top-level install routinely hosts several
    release-directory clones at once (every channel a user is on), so anything left at the top
    level is shared clutter multiplying with every *install*, worse than clutter multiplying
    with every clone.

    Idempotent: files already absent (the common case on a second finalize, or on any clone
    after the very first) are simply not in the returned tuple — never an error.
    """
    removed: list[str] = []
    for name in sorted(TOP_LEVEL_SETUP_FILES):
        target = install_root / name
        if target.is_file():
            target.unlink()
            removed.append(name)
    return tuple(removed)


async def finalize_clone(
    clone_dir: Path,
    *,
    dev_mode: bool,
    webapp_builder: WebappBuilder | None = None,
    python_bin: str | None = None,
) -> BootstrapReport:
    """§7.4's sequence, in order: strip, provision venvs, build the webapp, clean the top level.

    `webapp_builder` is optional — `services/gateway/` (the seam's real implementation) is
    0-byte scaffolding as of this module's own build. A `None` builder degrades that one step to
    "not built" rather than failing the whole finalize (`docs/PRINCIPLES.md` §4.4); the rest of
    the sequence still completes and is still reportable.

    `BootstrapReport.ok` is the gate Supervisor's Boot Sequence needs before trusting this
    clone — mirrors `ProvisionReport.fully_provisioned`'s own fail-closed posture, deliberately:
    a half-finalized clone is not a degraded clone, it is one Boot Sequence must never launch
    from.
    """
    strip_report = dev_mode_strip.strip_development_content(clone_dir, dev_mode)

    provision_report = venv_provisioning.provision_clone(clone_dir, python_bin=python_bin)

    webapp_built = False
    if webapp_builder is not None:
        await webapp_builder.build(clone_dir)
        webapp_built = True

    # <install-root>/releases/<version>_<hash>/ — two levels up, not one
    # (docs/VENV_AND_IMPORTS.md §2's own layout). `clone_dir.parent` alone is `releases/`, a
    # directory that legitimately holds several channels' clones at once, never the real
    # top-level install root config/data/models are siblings of.
    install_root = clone_dir.parent.parent
    cleaned = cleanup_top_level_setup_files(install_root)

    return BootstrapReport(
        strip=strip_report,
        venv_provision=provision_report,
        webapp_built=webapp_built,
        top_level_files_cleaned=cleaned,
    )
