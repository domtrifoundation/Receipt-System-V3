"""Per-instance version/commit tracking, riding the heartbeat (`v3-deepdive-34-watchdog.md` §5).

Under A/B hot-swap across channels (Update API's own multi-channel model) two instances of one
service genuinely run at once on different commits. Knowing which is which is what makes a
channel-specific issue diagnosable at all — "the beta instances are the ones failing" is a
different investigation from "the service is failing".

**This rides the heartbeat specifically, not every business response** (§5). Version tagging is
cheap wherever it is done, but cheap is not a reason to pay for it on the hot path when the
heartbeat already carries it. `docs/PROCESS_TOPOLOGY.md` §7 states the same rule from the
topology side.

This module holds no clock and no state of its own — it reads the kick registry. A second
store of "which version is instance X on" would be a second thing to keep in sync with the
heartbeats that are already the source of that fact.
"""

from __future__ import annotations

from collections import defaultdict

from .kicks import KickRegistry


class VersionTracker:
    """Which version/commit each currently-known service instance is running (§5)."""

    def __init__(self, registry: KickRegistry) -> None:
        self._registry = registry

    def version_for(self, service: str, instance_id: str) -> str:
        """That instance's reported commit, or the empty string if it has never kicked.

        Empty rather than a placeholder like `"unknown"`: a caller rendering this needs to
        distinguish "not reported" from a commit that happens to be named that, and an empty
        string is the one value no real commit hash can collide with.
        """
        beat = self._registry.last_kick(service, instance_id)
        return beat.version_commit if beat else ""

    def instances_by_version(self, service: str) -> dict[str, tuple[str, ...]]:
        """Instance ids grouped by the commit they report, for one service.

        A plain `dict` on purpose: this is a freshly computed answer handed to a caller, not a
        constant and not shared mutable state, so `docs/PRINCIPLES.md` §2.1.1 does not reach it
        — that section draws the line at intent, and the intent here is "a result you own".
        """
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for beat in self._registry.all_kicks():
            if beat.service == service:
                grouped[beat.version_commit].append(beat.instance_id)
        return {commit: tuple(sorted(ids)) for commit, ids in grouped.items()}

    def fleet_versions(self) -> dict[str, tuple[str, ...]]:
        """Every service mapped to the distinct commits its instances report.

        More than one commit for a service is the normal, expected state mid-hot-swap — it is
        information for the fleet screen, never a conflict to resolve here. Health reports; it
        does not decide (parent deep-dive §1).
        """
        grouped: defaultdict[str, set[str]] = defaultdict(set)
        for beat in self._registry.all_kicks():
            grouped[beat.service].add(beat.version_commit)
        return {service: tuple(sorted(commits)) for service, commits in grouped.items()}


__all__ = ["VersionTracker"]
