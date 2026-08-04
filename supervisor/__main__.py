"""`python -m supervisor` — run from Supervisor's own top-level install (`install.py`),
never from inside a clone. Resolves the active release via `ChannelArbitrator` and hands
off to the TUI, which drives the real fleet boot itself.

**Boot ownership, corrected from an earlier wrong turn this same session.** This module
originally called `boot_many()` itself, headlessly, printing raw progress lines, and only
launched the TUI *after* the fleet was already up. That is backwards from
`v3-deepdive-14-interface-api.md`'s own "only once every service is confirmed healthy
does Interface API's loading screen hand off to the running TUI" — the loading screen
*belongs to the TUI*, and the operator should watch the real boot happen there (the BETA
banner, real per-service progress via `BootSequenceScreen`), not read console text before
the TUI even starts. Fixed: this module now only resolves the active clone and launches
`services.interface.tui.app` with `clone_dir`/`channel`/`install_root` — that process
builds the fleet registry and calls `boot_many()` itself, on screen, from the start.
`services.interface`'s own venv already has both `textual` and `grpc`
(`common/requirements.txt`'s own base), so it needs nothing from Supervisor's own
grpc-only venv to do this.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .arbitration import ChannelArbitrator

DEFAULT_CHANNEL = "local"


def _launch_tui(clone_dir: Path, channel: str, install_root: Path) -> int:
    """Runs the TUI from the active clone's own `services.interface` venv (it needs
    `textual`, which Supervisor's own grpc-only venv deliberately does not have — the
    same reasoning `services/setup/bootstrap.py`'s own `wizard_command()` already
    established for the first-run wizard). Foreground, inherited stdio — this is the
    actual program the operator is meant to be looking at.
    """
    # fleet.py (imported inside the TUI process, not here) needs services.setup.
    # venv_provisioning, which only exists inside a clone — this module only needs it
    # for resolving the venv interpreter itself, so the import stays local and minimal.
    if str(clone_dir) not in sys.path:
        sys.path.insert(0, str(clone_dir))
    from services.setup.venv_provisioning import VENVS_DIRNAME, venv_python

    interpreter = venv_python(clone_dir / VENVS_DIRNAME / "services.interface")
    if not interpreter.exists():
        print(f"services.interface's own venv is missing at {interpreter} — cannot start the TUI.", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone_dir)
    result = subprocess.run(
        [str(interpreter), "-m", "services.interface.tui.app", str(clone_dir), channel, str(install_root)],
        cwd=str(clone_dir), env=env,
    )
    return result.returncode


def main() -> int:
    install_root = Path(__file__).resolve().parent.parent
    arbitrator = ChannelArbitrator(install_root)
    active = arbitrator.get_active(DEFAULT_CHANNEL)
    if active is None:
        print(f"No active release recorded for channel {DEFAULT_CHANNEL!r} — run setup first.", file=sys.stderr)
        return 1

    return _launch_tui(active.release_dir, DEFAULT_CHANNEL, install_root)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
