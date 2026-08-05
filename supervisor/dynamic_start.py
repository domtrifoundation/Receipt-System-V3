"""On-demand multi-version launch — the real mechanism behind the webapp's own "start
whatever version(s) its users are actually asking for" requirement, verbatim from the
owning conversation: most services can run several concurrent version instances at once,
started dynamically based on real demand rather than every available version being
pre-booted at fleet-boot time. `interface_tui`/`inference` never reach this module at all
— those two go through `single_instance.py`'s own restart-in-place mechanism instead,
since only one instance of either can ever be running (`available_versions.py`'s own
`SINGLE_INSTANCE_SERVICES`).

Reuses `single_instance.py`'s own `find_release_dir_for_version()` to resolve which
release clone a requested version actually lives in — the identical "does a release clone
for this exact version exist" question, asked here for a different reason (starting a new
concurrent instance rather than replacing the sole one).
"""

from __future__ import annotations

from pathlib import Path

from .available_versions import is_single_instance
from .boot_sequence import DEFAULT_HEALTH_TIMEOUT_SECONDS, launch_one
from .contracts import ServiceLaunchResult, ServiceSpec
from .instance_registry import InstanceRegistry
from .single_instance import find_release_dir_for_version

__all__ = ["ensure_version_running"]


async def ensure_version_running(
    registry: InstanceRegistry, spec: ServiceSpec, version: str, releases_dir: Path,
    *, timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
) -> ServiceLaunchResult:
    """Returns the already-running instance for `(spec.name, version)` if the registry
    already tracks one healthy, otherwise resolves `version`'s own release clone and
    launches it for real, recording the result before returning it.

    `interface_tui`/`inference` are refused here — callers wanting a specific tagged
    version of either must go through `single_instance.restart_service_on_version()`
    instead, since concurrent multi-instance serving is structurally wrong for either
    (`available_versions.py`'s own enforcement is the set-membership half of this same
    rule; this is the launch-path half)."""
    if is_single_instance(spec.name):
        return ServiceLaunchResult(
            name=spec.name, ok=False,
            error_detail=f"{spec.name!r} is single-instance — use restart_service_on_version(), not ensure_version_running()",
        )

    existing = registry.get(spec.name, version)
    if existing is not None and existing.ok:
        return existing

    target_dir = find_release_dir_for_version(releases_dir, version)
    if target_dir is None:
        result = ServiceLaunchResult(
            name=spec.name, ok=False,
            error_detail=f"no release clone found for version {version!r} under {releases_dir}",
        )
        registry.record(spec.name, version, result)
        return result

    result = await launch_one(spec, target_dir, timeout_seconds=timeout_seconds)
    registry.record(spec.name, version, result)
    return result
