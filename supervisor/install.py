"""Installs Supervisor's own package to the top-level install directory — the real,
previously-missing deployment step. `docs/PRINCIPLES.md` §1.6 and Supervisor's own
`CLAUDE.md` both state Supervisor lives permanently outside every release clone, but
nothing ever copied Supervisor's own source there — only its bookkeeping JSON files
(`active_releases.json`, `version_pins.json`) implicitly assumed a directory that nothing
created. This module is that missing step.

Idempotent by overwrite, matching `bootstrap.copy_launcher_scripts()`'s own reasoning —
Supervisor should track whichever clone most recently finalized, since a clone that fixed
a real bug in Supervisor's own code needs that fix to actually reach the top-level copy.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

__all__ = ["SUPERVISOR_VENV_DIRNAME", "install_supervisor", "supervisor_python"]

SUPERVISOR_VENV_DIRNAME = ".venv"


def _copy_package(source: Path, target: Path) -> bool:
    """Returns `False`, doing nothing, if `source` doesn't exist — a real, expected case
    for a minimal test-fixture clone (e.g. Update API's own `release_manager.py` tests,
    which clone a small local git remote with no real `supervisor/`/`common/` tree), not
    just a full real repo clone. Degrades rather than raising, matching this package's
    own `docs/PRINCIPLES.md` §4.4 posture — Supervisor's own top-level install is a real
    step but not one that should take down an otherwise-successful finalize over a
    fixture that was never meant to have it."""
    if not source.is_dir():
        return False
    for item in source.iterdir():
        if item.name in ("__pycache__",):
            continue
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    return True


def install_supervisor(clone_dir: Path, install_root: Path) -> Path | None:
    """Copies `supervisor/` from `clone_dir` to `<install_root>/supervisor/`, alongside
    the arbitration/pin JSON files that already live there. Also copies `common/` —
    Supervisor's own code imports it (`FrozenDict`, error codes) and it must be reachable
    from the top-level install, never from inside whichever clone happened to be active
    when Supervisor was last installed.

    Returns `None` (having copied nothing) if `clone_dir` has no real `supervisor/`
    directory at all — see `_copy_package`'s own docstring for why that's a real,
    expected case, not an error.
    """
    target = install_root / "supervisor"
    if not _copy_package(clone_dir / "supervisor", target):
        return None
    _copy_package(clone_dir / "common", install_root / "common")
    return target


def supervisor_python(install_root: Path) -> Path:
    venv_dir = install_root / "supervisor" / SUPERVISOR_VENV_DIRNAME
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def provision_supervisor_venv(clone_dir: Path, install_root: Path, *, python_bin: str | None = None) -> bool:
    """Supervisor only needs `grpc` (`common/requirements.txt`'s own base) — never a
    clone's full per-service dependency set. Its own venv, separate from every service's,
    matching `self_update/reexec.py`'s own assumption that Supervisor cannot use the
    normal per-clone update mechanism on itself."""
    interpreter = python_bin or sys.executable
    venv_dir = install_root / "supervisor" / SUPERVISOR_VENV_DIRNAME
    py = supervisor_python(install_root)
    if not py.exists():
        result = subprocess.run([interpreter, "-m", "venv", str(venv_dir)], capture_output=True, text=True)
        if result.returncode != 0:
            return False
    req = clone_dir / "common" / "requirements.txt"
    if req.is_file():
        result = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)], capture_output=True, text=True)
        return result.returncode == 0
    return True
