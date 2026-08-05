"""`python -m supervisor` — run from Supervisor's own top-level install (`install.py`),
never from inside a clone. Starts Supervisor's own real gRPC service (`service.py`) —
including `StreamBootProgress`, the RPC that actually calls `boot_many()` — then launches
the TUI as a genuinely detachable *display* client of it.

**Boot ownership, corrected twice this session and now actually right.** Attempt one
(headless): this module called `boot_many()` itself and printed raw progress, launching
the TUI only after. Attempt two: moved `boot_many()` into the TUI process so the operator
would see real progress instead of console text — but that put Supervisor's own job in
the wrong process; `v3-deepdive-14-interface-api.md` §1 is explicit that Interface API is
a genuinely detachable *display* client, never the thing doing the starting. This is the
actual design: Supervisor's own `SupervisorServicer.StreamBootProgress` calls
`boot_many()` and streams real per-service results over gRPC; the TUI's
`BootSequenceScreen` is a thin client that only renders what arrives.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .arbitration import ChannelArbitrator

DEFAULT_CHANNEL = "local"


def _launch_tui(clone_dir: Path, supervisor_address: str, channel: str) -> int:
    """Runs the TUI from the active clone's own `services.interface` venv (it needs
    `textual`, which Supervisor's own grpc-only venv deliberately does not have — the
    same reasoning `services/setup/bootstrap.py`'s own `wizard_command()` already
    established for the first-run wizard). Foreground, inherited stdio — this is the
    actual program the operator is meant to be looking at.
    """
    import os

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
        [str(interpreter), "-m", "services.interface.tui.app", "--supervisor", supervisor_address, "--channel", channel],
        cwd=str(clone_dir), env=env,
    )
    return result.returncode


async def _main() -> int:
    import asyncio
    import os
    import signal

    install_root = Path(__file__).resolve().parent.parent
    arbitrator = ChannelArbitrator(install_root)
    active = arbitrator.get_active(DEFAULT_CHANNEL)
    if active is None:
        print(f"No active release recorded for channel {DEFAULT_CHANNEL!r} — run setup first.", file=sys.stderr)
        return 1

    clone_dir = active.release_dir
    if str(clone_dir) not in sys.path:
        sys.path.insert(0, str(clone_dir))

    from .service import serve

    server = await serve(install_root=install_root, specs={})
    print(f"Supervisor's own gRPC service is up at {server.bound_address}.")

    try:
        tui_exit_code = await asyncio.to_thread(_launch_tui, clone_dir, server.bound_address, DEFAULT_CHANNEL)
        # The TUI closing is the operator closing the program — the fleet shuts down
        # with it rather than lingering headless. A detachable-client re-attach flow
        # (start the TUI again against an already-running fleet, without this shutdown)
        # is real, named future work, not silently assumed solved by this pass.
        return tui_exit_code
    finally:
        for pid in server.servicer.spawned_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        await server.stop(grace=2.0)


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(0)
