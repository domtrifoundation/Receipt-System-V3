"""The real fleet-boot entrypoint — `python -m supervisor`, run from Supervisor's own
top-level install (`install.py`), never from inside a clone. Resolves the active release
via `ChannelArbitrator`, builds the real fleet registry (`fleet.py`) against that clone,
and boots it with live progress — the thing `start.bat`/`start.sh` actually invoke.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .arbitration import ChannelArbitrator
from .boot_sequence import boot_many
from .contracts import ServiceLaunchResult
from .fleet import build_fleet_specs

DEFAULT_CHANNEL = "local"


async def _main() -> int:
    install_root = Path(__file__).resolve().parent.parent
    arbitrator = ChannelArbitrator(install_root)
    active = arbitrator.get_active(DEFAULT_CHANNEL)
    if active is None:
        print(f"No active release recorded for channel {DEFAULT_CHANNEL!r} — run setup first.", file=sys.stderr)
        return 1

    clone_dir = active.release_dir
    specs = build_fleet_specs(clone_dir)
    print(f"Booting {len(specs)} services from {clone_dir}...")

    def on_result(result: ServiceLaunchResult) -> None:
        status = "OK" if result.ok else "FAILED"
        detail = f" — {result.error_detail}" if result.error_detail else ""
        print(f"  [{status}] {result.name} @ {result.address}{detail}")

    report = await boot_many(specs, clone_dir, channel=DEFAULT_CHANNEL, on_result=on_result)
    if not report.ok:
        print(f"Boot incomplete. Failed: {report.failed_services}", file=sys.stderr)
        return 1

    print("All services up. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_main()))
