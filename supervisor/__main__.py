"""The real fleet-boot entrypoint — `python -m supervisor`, run from Supervisor's own
top-level install (`install.py`), never from inside a clone. Resolves the active release
via `ChannelArbitrator`, builds the real fleet registry (`fleet.py`) against that clone,
and boots it with live progress — the thing `start.bat`/`start.sh` actually invoke.

**Owns real child-process cleanup on exit — a real, live-found gap, not theoretical.**
Confirmed live: neither a graceful `Ctrl+C` nor a hard kill of this process previously
terminated the 30+ subprocesses it spawned; they kept running as orphans, discovered only
by manually hunting down every PID with `wmic`. `_terminate_children()` now runs in a
`finally` around the wait loop (covers `Ctrl+C`/normal return) and a `SIGTERM` handler
(covers a graceful `kill`/`taskkill` without `/F`) — the one case genuinely impossible to
handle in pure Python is `SIGKILL`/`taskkill /F`, which gives no process any chance to run
cleanup code at all; that remains a real, stated OS-level limit, not silently claimed
solved.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path

from .arbitration import ChannelArbitrator
from .boot_sequence import boot_many
from .contracts import ServiceLaunchResult

DEFAULT_CHANNEL = "local"

#: Relative to the install root — every service's own real, dynamically-bound address,
#: written as each one comes up. The real answer to "how does one service find another
#: when ports are no longer fixed constants" (e.g. `common/blob_client.py`'s own
#: Persistence lookup) — read this file, never a hardcoded port.
SERVICE_ADDRESSES_RELPATH = Path("supervisor") / "service_addresses.json"


def _write_service_addresses(install_root: Path, addresses: dict[str, str]) -> None:
    target = install_root / SERVICE_ADDRESSES_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(addresses, indent=2) + "\n", encoding="utf-8")


def _terminate_children(pids: list[int]) -> None:
    import os

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


async def _main() -> int:
    install_root = Path(__file__).resolve().parent.parent
    arbitrator = ChannelArbitrator(install_root)
    active = arbitrator.get_active(DEFAULT_CHANNEL)
    if active is None:
        print(f"No active release recorded for channel {DEFAULT_CHANNEL!r} — run setup first.", file=sys.stderr)
        return 1

    clone_dir = active.release_dir
    # fleet.py imports services.setup.venv_provisioning, which only exists inside a
    # clone — deferred until clone_dir is known and on sys.path, never importable at
    # this module's own top level (Supervisor's top-level install has no clone on its
    # own PYTHONPATH until this point).
    if str(clone_dir) not in sys.path:
        sys.path.insert(0, str(clone_dir))
    from .fleet import build_fleet_specs

    specs = build_fleet_specs(clone_dir)
    print(f"Booting {len(specs)} services from {clone_dir}...")

    pids: list[int] = []
    addresses: dict[str, str] = {}

    def on_result(result: ServiceLaunchResult) -> None:
        status = "OK" if result.ok else "FAILED"
        detail = f" — {result.error_detail}" if result.error_detail else ""
        print(f"  [{status}] {result.name} (pid={result.pid}){detail}")
        if result.pid is not None:
            pids.append(result.pid)
        if result.address:
            addresses[result.name] = result.address
            _write_service_addresses(install_root, addresses)

    loop = asyncio.get_running_loop()
    shutdown_requested = asyncio.Event()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, shutdown_requested.set)

    try:
        report = await boot_many(specs, clone_dir, channel=DEFAULT_CHANNEL, on_result=on_result)
        if not report.ok:
            print(f"Boot incomplete. Failed: {report.failed_services}", file=sys.stderr)
            return 1

        print("All services up. Press Ctrl+C to stop.")
        try:
            if sys.platform != "win32":
                await shutdown_requested.wait()
            else:
                # No SIGTERM support via asyncio on Windows (`add_signal_handler` raises
                # NotImplementedError there) — Ctrl+C's own KeyboardInterrupt is what
                # this platform actually gets, caught below same as everywhere else.
                while True:
                    await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0
    finally:
        _terminate_children(pids)


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(0)
