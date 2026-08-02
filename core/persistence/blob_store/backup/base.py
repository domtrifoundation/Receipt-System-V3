"""`BackupTarget` — the Provider Registry for blob backup (§4.4).

`docs/PRINCIPLES.md` §1.2 names blob backup targets as one of the concrete examples of "more
than one provider enabled at once, not a single config value swapped one at a time." B2 and
Storj both run, genuinely simultaneously, and a write fans out to every enabled target
rather than failing over one at a time.

**The confirmation semantics are the parent deep-dive's own §12 resolution, implemented
rather than restated**: one confirmed target is already real durability, because the targets
are redundant by design — so `durably_backed_up` is one-of-N. `fully_synced` is all-of-N and
exists for operator visibility, never as the gate on the write path. Requiring both would
trade real write latency for redundancy the design does not need at that threshold.

Every target is a real `typing.Protocol`, never an `if provider == "b2"` branch, and every
target reports `is_reachable()` as a first-class state — the weekly spot-verification job
(Background Workers §6.4) and Archive Sync's own notify-then-pause behaviour both depend on
reachability being checkable rather than inferred from a failed upload.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ...contracts import utcnow


@dataclass(frozen=True)
class TargetOutcome:
    """One target's own result for one blob. Errors are data here too."""

    target_name: str
    ok: bool
    error_detail: str = ""


@dataclass(frozen=True)
class FanOutResult:
    """The aggregate across every enabled target.

    `durably_backed_up` is one-of-N; `fully_synced` is all-of-N. Two flags, never one — see
    the module docstring.
    """

    confirmed: tuple[str, ...]
    failed: tuple[str, ...]
    enabled_count: int

    @property
    def durably_backed_up(self) -> bool:
        return bool(self.confirmed)

    @property
    def fully_synced(self) -> bool:
        return self.enabled_count > 0 and len(self.confirmed) == self.enabled_count


@runtime_checkable
class BackupTarget(Protocol):
    """One remote replication target for the blob store."""

    name: str

    async def is_reachable(self) -> bool:
        """Whether the target can be talked to at all, checkable independently of a write."""
        ...

    async def upload(self, physical_hash: str, data: bytes) -> TargetOutcome:
        """Replicate one blob's *stored* bytes, addressed by `physical_hash`.

        Addressed by physical hash, not logical id, for the same reason the local store is:
        a backed-up file must be verifiable against its own name (`verify.py` §4).
        """
        ...

    async def fetch(self, physical_hash: str) -> bytes | None:
        """Retrieve a blob for a restore, or `None` if this target does not hold it."""
        ...


class BackupRegistry:
    """The live registry. A genuinely mutable internal registry, so a plain `dict`.

    `docs/PRINCIPLES.md` §2.1.1 draws this distinction explicitly: module-level *constants*
    are `FrozenDict`; a registry populated at startup and mutated by configuration is not a
    constant and the type should say so.
    """

    def __init__(self, targets: list[BackupTarget] | None = None) -> None:
        self._targets: dict[str, BackupTarget] = {}
        self._enabled: dict[str, bool] = {}
        for target in targets or []:
            self.register(target)

    def register(self, target: BackupTarget, *, enabled: bool = True) -> None:
        self._targets[target.name] = target
        self._enabled[target.name] = enabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name in self._enabled:
            self._enabled[name] = enabled

    def enabled_targets(self) -> tuple[BackupTarget, ...]:
        return tuple(t for n, t in self._targets.items() if self._enabled.get(n))

    def get(self, name: str) -> BackupTarget | None:
        return self._targets.get(name)

    async def fan_out(self, physical_hash: str, data: bytes) -> FanOutResult:
        """Upload to every enabled target in parallel, never sequentially.

        A sequential loop here would make each target's latency additive on the write path
        for no benefit — the same sequential-loop mistake this project already corrected in
        Geo/Address. A target that raises is recorded as failed rather than taking the fan
        out down with it (`docs/PRINCIPLES.md` §4.4): backup is not a security check, so it
        degrades rather than failing closed.
        """
        targets = self.enabled_targets()
        if not targets:
            return FanOutResult(confirmed=(), failed=(), enabled_count=0)
        outcomes = await asyncio.gather(
            *(t.upload(physical_hash, data) for t in targets), return_exceptions=True
        )
        confirmed: list[str] = []
        failed: list[str] = []
        for target, outcome in zip(targets, outcomes):
            if isinstance(outcome, BaseException):
                failed.append(target.name)
            elif outcome.ok:
                confirmed.append(outcome.target_name)
            else:
                failed.append(outcome.target_name)
        return FanOutResult(
            confirmed=tuple(confirmed), failed=tuple(failed), enabled_count=len(targets)
        )

    async def reachability(self) -> dict[str, bool]:
        """Checked in parallel for the same reason `fan_out` is."""
        targets = self.enabled_targets()
        results = await asyncio.gather(
            *(t.is_reachable() for t in targets), return_exceptions=True
        )
        return {
            t.name: (r is True) for t, r in zip(targets, results)
        }


class InMemoryTarget:
    """A real, working target that keeps blobs in memory.

    Not a mock: the spot-verification job, the failover test, and a self-hosted install with
    no remote credentials configured all need a target that genuinely round-trips without a
    network. `reachable` is settable so the failover behaviour can be exercised for real.
    """

    def __init__(self, name: str = "memory", *, reachable: bool = True) -> None:
        self.name = name
        self.reachable = reachable
        self._blobs: dict[str, bytes] = {}

    async def is_reachable(self) -> bool:
        return self.reachable

    async def upload(self, physical_hash: str, data: bytes) -> TargetOutcome:
        if not self.reachable:
            return TargetOutcome(self.name, ok=False, error_detail="target unreachable")
        self._blobs[physical_hash] = data
        return TargetOutcome(self.name, ok=True)

    async def fetch(self, physical_hash: str) -> bytes | None:
        if not self.reachable:
            return None
        return self._blobs.get(physical_hash)


__all__ = [
    "BackupRegistry",
    "BackupTarget",
    "FanOutResult",
    "InMemoryTarget",
    "TargetOutcome",
    "utcnow",
]
