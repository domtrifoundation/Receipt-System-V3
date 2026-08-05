"""§3.3's rollback: "If a newly-cutover release fails its own post-cutover health
checks, Supervisor reverts `ActiveRelease` for that channel back to the prior release
directory (still on disk — garbage collection always keeps at least one prior, Update
deep-dive §3) and re-launches services from it. This is a genuine advantage of 'clone
into a new directory, never mutate in place' — the old release is never gone, just no
longer pointed at."
"""

from __future__ import annotations

from pathlib import Path

from .arbitration import ChannelArbitrator
from .boot_sequence import DEFAULT_HEALTH_TIMEOUT_SECONDS, boot_many
from .contracts import RollbackResult, ServiceSpec, utcnow
from .errors import NoPriorRelease, UnknownChannel, code_for

__all__ = ["rollback_channel"]


async def rollback_channel(
    channel: str, specs: tuple[ServiceSpec, ...], arbitrator: ChannelArbitrator,
    *, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
) -> RollbackResult:
    """Reverts `channel` to its own prior release directory and re-launches every
    service from it. Never raises — an unknown channel or one with no prior release are
    both a `RollbackResult(ok=False, ...)` (`docs/PRINCIPLES.md` §4.1).
    """
    try:
        arbitrator.require_active(channel)
    except UnknownChannel as exc:
        return RollbackResult(channel=channel, reverted_to=None, error_code=code_for(exc), error_detail=str(exc))

    prior = arbitrator.prior_release(channel)
    if prior is None:
        exc = NoPriorRelease(channel)
        return RollbackResult(channel=channel, reverted_to=None, error_code=code_for(exc), error_detail=str(exc))

    if not prior.is_dir():
        exc = NoPriorRelease(f"{channel}: prior release directory {prior} no longer exists on disk")
        return RollbackResult(channel=channel, reverted_to=None, error_code=code_for(exc), error_detail=str(exc))

    boot = await boot_many(specs, prior, channel=channel, timeout_seconds=timeout_seconds)
    if not boot.ok:
        return RollbackResult(
            channel=channel, reverted_to=prior, boot=boot,
            error_code="ROLLBACK_BOOT_FAILED",
            error_detail=f"reverted config to {prior} but services failed to boot: {boot.failed_services}",
        )

    # Only record the reversion once the prior release's own services are confirmed
    # healthy — recording it first and failing to boot would leave `ActiveRelease`
    # pointing at a release nothing is actually running from.
    arbitrator.set_active(channel, prior)
    return RollbackResult(channel=channel, reverted_to=prior, boot=boot)
