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

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import dev_mode_strip, venv_provisioning
from .contracts import BootstrapReport, WebappBuilder
from supervisor.arbitration import ChannelArbitrator
from supervisor.install import install_supervisor, provision_supervisor_venv

DEFAULT_SUPERVISOR_CHANNEL = "local"

__all__ = [
    "INSTALL_CONFIG_RELPATH",
    "LAUNCHER_SCRIPT_NAMES",
    "TOP_LEVEL_SETUP_FILES",
    "cleanup_top_level_setup_files",
    "copy_launcher_scripts",
    "ensure_wizard_dependencies",
    "finalize_clone",
    "read_dev_mode",
    "read_run_on_startup",
    "run_first_run_wizard",
    "wizard_command",
    "write_install_config",
    "write_run_on_startup",
]

#: The launcher scripts every clone carries, copied to the install root once as a real §4/§1.6
#: step. Not a glob for the same reason `TOP_LEVEL_SETUP_FILES` below is not one: this writes to
#: the install root, a sibling of real user data.
LAUNCHER_SCRIPT_NAMES: frozenset[str] = frozenset({"start.bat", "start.sh"})

#: Relative to the install root. `config/` is already a shipped, gitignored-contents top-level
#: directory (`docs/PRINCIPLES.md` §1.6) — this file is genuinely shared, persistent state, the
#: same category as everything else that lives there.
INSTALL_CONFIG_RELPATH = Path("config") / "install.json"

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


def copy_launcher_scripts(clone_dir: Path, install_root: Path) -> tuple[str, ...]:
    """Copies `LAUNCHER_SCRIPT_NAMES` from the clone to the install root, per §4's "the
    top-level directory structure... is built as siblings to every release directory."

    Idempotent by overwrite: every update re-clones and re-finalizes, and the launcher at the
    install root should track whichever clone most recently finalized — an update that changed
    the launcher's own logic must actually reach the install root, not be silently skipped
    because a copy already exists there. A launcher script is not user data; overwriting it
    carries none of the risk that guards `dev_mode_strip.py`'s own containment logic.

    Missing individual scripts in the clone are skipped, not fatal — reported honestly via the
    returned tuple rather than raising, matching this package's error-as-data posture applied to
    a genuinely optional-per-script operation.
    """
    install_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in sorted(LAUNCHER_SCRIPT_NAMES):
        source = clone_dir / name
        if source.is_file():
            shutil.copy2(source, install_root / name)
            copied.append(name)
    return tuple(copied)


def read_dev_mode(install_root: Path) -> bool | None:
    """The persisted flag every later Update API clone reads (§4.1) — `None` when no install
    config exists yet, distinct from `False`, so a caller can tell "not yet installed" from "an
    installed, normal-mode instance."
    """
    target = install_root / INSTALL_CONFIG_RELPATH
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    value = data.get("dev_mode")
    return bool(value) if isinstance(value, bool) else None


def write_install_config(install_root: Path, dev_mode: bool) -> bool:
    """Writes `dev_mode` once. `docs/apis/v3-deepdive-11-setup-api.md` §4.1: "recorded once, at
    first-clone time... not something asked again on every subsequent update" — so an existing
    config is left alone rather than overwritten, and this returns `False` in that case (nothing
    written) rather than silently re-confirming a value that was never in question.
    """
    target = install_root / INSTALL_CONFIG_RELPATH
    if target.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"dev_mode": dev_mode}, indent=2) + "\n", encoding="utf-8")
    return True


def read_run_on_startup(install_root: Path) -> bool:
    """`run_on_startup` (§4.1's own "offered as a genuinely skippable step during
    first-run setup") is freely re-toggleable at any time, unlike `dev_mode` above —
    real, deliberate asymmetry, not an oversight: `dev_mode` is a first-clone-only
    structural choice ("not convertible on a live install"), while whether the cluster
    launches at machine boot is an ordinary operational preference an owner can change
    whenever they like. Defaults to `False` (not offered unless explicitly turned on)
    when nothing has been written yet.
    """
    target = install_root / INSTALL_CONFIG_RELPATH
    if not target.is_file():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    value = data.get("run_on_startup")
    return bool(value) if isinstance(value, bool) else False


def write_run_on_startup(install_root: Path, run_on_startup: bool) -> None:
    """Always overwrites — the real read-modify-write counterpart to `read_run_on_startup`,
    sharing `INSTALL_CONFIG_RELPATH` with `dev_mode` but never touching that key, so a
    `run_on_startup` toggle can never accidentally reset `dev_mode` or vice versa."""
    target = install_root / INSTALL_CONFIG_RELPATH
    data: dict = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["run_on_startup"] = run_on_startup
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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
    launchers_copied = copy_launcher_scripts(clone_dir, install_root)
    config_written = write_install_config(install_root, dev_mode)
    cleaned = cleanup_top_level_setup_files(install_root)

    # Supervisor's own top-level installation — the real, previously-missing deployment
    # step. Only proceeds if venv provisioning actually succeeded; installing Supervisor
    # against a clone that isn't eligible for Boot Sequence would just point the top-level
    # launcher at something broken.
    if provision_report.fully_provisioned:
        installed = install_supervisor(clone_dir, install_root)
        if installed is not None:
            provision_supervisor_venv(clone_dir, install_root, python_bin=python_bin)
            ChannelArbitrator(install_root).set_active(DEFAULT_SUPERVISOR_CHANNEL, clone_dir)

    return BootstrapReport(
        strip=strip_report,
        venv_provision=provision_report,
        webapp_built=webapp_built,
        top_level_files_cleaned=cleaned,
        launcher_scripts_copied=launchers_copied,
        install_config_written=config_written,
    )


def wizard_command(clone_dir: Path, install_root: Path) -> list[str]:
    """The real command used to launch the interactive first-run wizard — a pure function
    so the exact invocation is unit-testable without spawning a real interactive
    subprocess (`services/interface/tui/wizard_entrypoint.py`'s own module docstring
    explains why this runs from `services.interface`'s own provisioned venv rather than
    the bare interpreter this module itself runs under).
    """
    interpreter = venv_provisioning.venv_python(
        clone_dir / venv_provisioning.VENVS_DIRNAME / "services.interface"
    )
    launcher_name = "start.bat" if os.name == "nt" else "start.sh"
    launcher_path = install_root / launcher_name
    return [
        str(interpreter), "-m", "services.interface.tui.wizard_entrypoint",
        str(launcher_path), str(install_root),
    ]


def _interface_venv_interpreter(clone_dir: Path) -> Path:
    return venv_provisioning.venv_python(
        clone_dir / venv_provisioning.VENVS_DIRNAME / "services.interface"
    )


def ensure_wizard_dependencies(clone_dir: Path) -> tuple[bool, str]:
    """Verifies the interface venv's own interpreter can actually `import textual` before
    handing control to it — `venv_provisioning.provision_service`'s own success report
    (`error=None`) is a real, honest signal at the moment it's produced, but is not
    re-verified here as a guarantee: a real-world install can still end up with a venv
    that reports clean and doesn't actually have the package importable (a partial
    install from a transient network blip, antivirus interference with concurrent venv
    creation on Windows, or any number of other environment-specific causes this module
    cannot diagnose in the general case). One bounded repair attempt — re-running the
    same `pip install -r requirements.txt` this venv was already supposed to get — before
    giving up cleanly. Never leaves the operator looking at a raw Python traceback for
    this specific, recoverable case.
    """
    interpreter = _interface_venv_interpreter(clone_dir)
    if not interpreter.exists():
        return False, f"{interpreter} does not exist — services.interface's venv was never created."

    check = subprocess.run([str(interpreter), "-c", "import textual"], capture_output=True, text=True)
    if check.returncode == 0:
        return True, ""

    req = clone_dir / "services" / "interface" / "requirements.txt"
    if not req.is_file():
        return False, f"{req} is missing from this clone — cannot repair."

    repair = subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(req)], capture_output=True, text=True)
    if repair.returncode != 0:
        detail = (repair.stderr or repair.stdout or "no output captured").strip()
        return False, f"repair install failed: {detail}"

    recheck = subprocess.run([str(interpreter), "-c", "import textual"], capture_output=True, text=True)
    if recheck.returncode == 0:
        return True, ""
    detail = (check.stderr or check.stdout or "no output captured").strip()
    return False, f"textual still not importable after a repair install attempt: {detail}"


def run_first_run_wizard(clone_dir: Path, install_root: Path) -> bool:
    """Runs the real interactive wizard, inheriting this process's own stdio so it's
    genuinely interactive in the same terminal the operator is already looking at —
    never captured/piped, since a wizard the operator can't see or answer isn't a wizard.

    Returns whether it completed successfully. Never raises for a non-zero wizard exit —
    an operator who quits out of setup partway through is a real, reportable outcome
    (`docs/PRINCIPLES.md` §4.1's errors-as-data posture), not a crash in this module.
    Checks `ensure_wizard_dependencies` first and reports a clear, actionable message
    instead of a raw traceback if the interface venv genuinely can't run it.
    """
    ok, detail = ensure_wizard_dependencies(clone_dir)
    if not ok:
        print(f"Skipping the wizard — its own dependencies aren't available: {detail}")
        print("The install itself is unaffected; re-run the wizard later with:")
        print(f"  {_interface_venv_interpreter(clone_dir)} -m services.interface.tui.wizard_entrypoint <launcher> <install_root>")
        return False

    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone_dir)
    result = subprocess.run(wizard_command(clone_dir, install_root), cwd=str(clone_dir), env=env)
    return result.returncode == 0


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import asyncio
    import sys

    def _parse_args() -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description="Run Setup API's finalize routine against a freshly cloned release "
            "directory — the step the top-level setup.bat/setup.sh script hands off to once "
            "the first git clone completes."
        )
        parser.add_argument("clone_dir", type=Path)
        parser.add_argument(
            "--dev-mode",
            action="store_true",
            help="setup-dev's own bare-bones path — strips nothing (§4.1).",
        )
        return parser.parse_args()

    async def _main() -> int:
        args = _parse_args()
        report = await finalize_clone(args.clone_dir.resolve(), dev_mode=args.dev_mode)

        print(f"strip: {'ok' if report.strip.ok else 'FAILED'} "
              f"({len(report.strip.removed)} removed, {len(report.strip.errors)} errors)")
        print(f"venvs: {'ok' if report.venv_provision.fully_provisioned else 'FAILED'} "
              f"({len(report.venv_provision.outcomes)} services, "
              f"{len(report.venv_provision.failed)} failed)")
        for failed in report.venv_provision.failed:
            print(f"  - {failed.import_path}: {failed.error.detail}")
        print(f"launcher scripts copied: {', '.join(report.launcher_scripts_copied) or '(none)'}")
        print(f"install config written: {report.install_config_written}")

        if not report.ok:
            print("finalize FAILED — this clone is not eligible for Boot Sequence.", file=sys.stderr)
            return 1
        print("finalize complete.")

        if not args.dev_mode:
            # Normal mode is the immersive, interactive first-run experience (§4.1) — the
            # wizard genuinely runs here, not skipped. Dev mode stays deliberately silent
            # per that same section; no call happens at all on that path.
            install_root = args.clone_dir.resolve().parent.parent
            print("\nStarting the first-run setup wizard...\n")
            wizard_ok = run_first_run_wizard(args.clone_dir.resolve(), install_root)
            if not wizard_ok:
                print(
                    "Wizard did not complete (quit early or failed) — you can re-run it "
                    "later; this does not affect the install itself.",
                    file=sys.stderr,
                )

        return 0

    sys.exit(asyncio.run(_main()))
