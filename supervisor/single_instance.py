"""§5.4's own single-instance restart — "the same verified two-phase handoff §4.2
already uses for Supervisor's own self-update, applied here to a different target."
TUI and Inference only (§5.3's own closed, justified two-service list — both the
heaviest processes in the fleet, each with its own independent reason multi-version
doesn't make sense for it).

**Not in the deep-dive's own §2 package layout** — added because §5.4's own
`restart_service_on_version()` is real, substantial logic (confirm target, stop old,
launch new, health-gate) that belongs in its own module rather than folded into
`boot_sequence.py` (fleet-wide dependency-ordered boot) or `service.py` (thin gRPC
adapter, per this session's own established convention for every other API's servicer).

**The stated asymmetry from §5.4 is real, not just described — confirmed live via a
target-clone-unavailable failure at step 1, never reaching step 2.** "If step 4 never
succeeds, this is a real, harder failure mode than Supervisor's own self-update rollback
— there's no 'old instance still running' to fall back to, since the old one was already
stopped in step 2. Mitigated by confirming step 1 thoroughly before ever stopping the
running instance, not by a rollback after the fact." This module's own `restart_service_
on_version()` is a real async generator yielding one `RestartResult` per stage
specifically so a caller (the streaming `RestartServiceOnVersion` RPC) can render live
progress and never obscure exactly which step failed.
"""

from __future__ import annotations

import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path

from .boot_sequence import DEFAULT_HEALTH_TIMEOUT_SECONDS, launch_one
from .contracts import RestartResult, ServiceSpec, utcnow

__all__ = ["find_release_dir_for_version", "restart_service_on_version"]


def find_release_dir_for_version(releases_dir: Path, target_version: str) -> Path | None:
    """§5.4 step 1's own "confirm target_version's own release clone exists" check —
    the target need not be currently active on any channel, since TUI/Inference version
    selection is independent of channel-based multi-version serving entirely (§5.4's own
    parenthetical)."""
    if not releases_dir.is_dir():
        return None
    prefix = f"{target_version}_"
    matches = sorted(p for p in releases_dir.iterdir() if p.is_dir() and p.name.startswith(prefix))
    return matches[0] if matches else None


async def restart_service_on_version(
    service_name_literal, target_version: str, releases_dir: Path, spec: ServiceSpec,
    *, current_pid: int | None, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
) -> AsyncIterator[RestartResult]:
    """Yields one `RestartResult` per stage, in §5.4's own exact order. `current_pid` is
    the presently-running instance's own process id, or `None` if nothing is currently
    running (a first launch, not a restart in the strict sense, but the same mechanism
    handles it identically — steps 2/3/4 with an empty step 2)."""
    started = utcnow()

    yield RestartResult(service_name=service_name_literal, target_version=target_version, stage="confirming_target", started_at=started)

    target_dir = find_release_dir_for_version(releases_dir, target_version)
    if target_dir is None:
        yield RestartResult(
            service_name=service_name_literal, target_version=target_version, stage="failed",
            started_at=started, finished_at=utcnow(),
            error_detail=f"no release clone found for version {target_version!r} under {releases_dir}",
        )
        return

    # Step 1's own "health-check-capable" half: launch-and-probe against a throwaway
    # confirmation, not the real serving launch — but this codebase has no sandboxed
    # dry-run launch mode today, so this pass treats "the clone directory exists and
    # names a real venv for this service" as the real, checkable proxy for "capable of
    # being launched," documented honestly as narrower than a full launch rehearsal.
    venv_marker = target_dir / ".venvs" / spec.import_path
    if not venv_marker.is_dir():
        yield RestartResult(
            service_name=service_name_literal, target_version=target_version, stage="failed",
            started_at=started, finished_at=utcnow(),
            error_detail=f"{target_dir} has no provisioned venv for {spec.import_path!r} — not health-check-capable",
        )
        return

    yield RestartResult(service_name=service_name_literal, target_version=target_version, stage="stopping_old", started_at=started)

    if current_pid is not None:
        try:
            os.kill(current_pid, signal.SIGTERM)
        except OSError:
            pass  # already gone — stopping an already-stopped instance is not a failure

    yield RestartResult(service_name=service_name_literal, target_version=target_version, stage="launching_new", started_at=started)

    yield RestartResult(service_name=service_name_literal, target_version=target_version, stage="waiting_healthy", started_at=started)

    launch_result = await launch_one(spec, target_dir, timeout_seconds=timeout_seconds)
    if not launch_result.ok:
        yield RestartResult(
            service_name=service_name_literal, target_version=target_version, stage="failed",
            started_at=started, finished_at=utcnow(), error_detail=launch_result.error_detail,
        )
        return

    yield RestartResult(service_name=service_name_literal, target_version=target_version, stage="complete", started_at=started, finished_at=utcnow())
