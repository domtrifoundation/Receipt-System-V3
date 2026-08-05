"""The N→N+1 chain, one step per version bump (§2, §3, §8).

Two rules are enforced here rather than left to review, because both are the kind of mistake
that looks harmless in a diff and is expensive in production:

* **A step spans exactly one bump.** §1: "N→N+2 is always N→N+1→N+2, chained, never a shortcut
  migration written to skip a step, since that would mean two different code paths could
  produce the same end state, a real correctness risk." A shortcut is rejected at registration,
  not discovered when the two paths disagree after someone edits one of them.
* **One step per bump.** Two registrations for the same bump would make which one runs depend
  on import order, and a migration whose behaviour depends on import order is not
  reproducible — the one property a migration chain has to have.

`check_chain` implements §8's chain-integrity hook as a real value rather than only a test
assertion: "a missing step should fail CI, not be discovered mid-migration on a live system."
Returning a report rather than a bool means the same check serves the test, a startup
self-check and an operator status view without three implementations of it.

**The registry is genuinely mutable internal state** — `steps/` modules register into it at
import time — so it holds a plain `dict` behind a lock rather than a `FrozenDict`
(`docs/PRINCIPLES.md` §2.1.1 draws that line at intent).
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .contracts import ChainIntegrityReport, MigrationStep, StructureKind
from .errors import DuplicateMigrationStep, MissingMigrationStep, MultiVersionStep

#: What a step's own migration function looks like. It takes the structure's id and returns
#: whether it did real work — `False` meaning "already applied", which is what makes §8's
#: idempotency hook expressible by the step itself rather than guessed at by the runner.
#:
#: The runner cannot know whether a given structure already carries a change; only the step
#: knows what to look for. Returning the answer is what keeps that knowledge in the one file
#: that has it.
StepFunction = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class RegisteredStep:
    """A `MigrationStep` paired with the callable `contracts.py` deliberately does not hold."""

    step: MigrationStep
    apply: StepFunction


class MigrationRegistry:
    """Every registered N→N+1 step, keyed by structure kind and source version."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._steps: dict[tuple[StructureKind, int], RegisteredStep] = {}

    def register(self, step: MigrationStep, apply: StepFunction) -> None:
        """Add one step. Rejects a shortcut or a duplicate rather than accepting either."""
        if not step.is_single_bump:
            raise MultiVersionStep(
                f"{step.kind.value} {step.from_version}->{step.to_version} spans more than one "
                "bump; chain it as consecutive steps instead"
            )
        key = (step.kind, step.from_version)
        with self._lock:
            if key in self._steps:
                raise DuplicateMigrationStep(
                    f"a step is already registered for {step.kind.value} "
                    f"{step.from_version}->{step.from_version + 1}"
                )
            self._steps[key] = RegisteredStep(step=step, apply=apply)

    def get_step(self, kind: StructureKind, from_version: int) -> RegisteredStep:
        """The step that bumps `from_version` to `from_version + 1`, or raise.

        Raising rather than returning `None` is deliberate: every caller of this would have to
        turn a `None` into a stop anyway, and one that forgot would silently skip the gap —
        which is exactly the half-migrated state this package's `errors.py` argues is worse
        than not migrating at all.
        """
        with self._lock:
            found = self._steps.get((kind, from_version))
        if found is None:
            raise MissingMigrationStep(
                f"no step registered for {kind.value} {from_version}->{from_version + 1}"
            )
        return found

    def has_step(self, kind: StructureKind, from_version: int) -> bool:
        with self._lock:
            return (kind, from_version) in self._steps

    def steps_for(self, kind: StructureKind) -> tuple[MigrationStep, ...]:
        with self._lock:
            found = [rs.step for rs in self._steps.values() if rs.step.kind is kind]
        return tuple(sorted(found, key=lambda s: s.from_version))

    def kinds(self) -> tuple[StructureKind, ...]:
        with self._lock:
            return tuple(sorted({key[0] for key in self._steps}, key=lambda k: k.value))

    def check_chain(self, kind: StructureKind, *, target_version: int) -> ChainIntegrityReport:
        """§8's chain-integrity hook: is the chain from version 1 to `target_version` unbroken?

        Starts at 1 rather than at the lowest registered step on purpose. A chain whose first
        step is 3→4 is not a chain with a high floor — it is a chain missing 1→2 and 2→3, and
        starting from the lowest *registered* version would define that gap out of existence.
        """
        steps = self.steps_for(kind)
        missing = tuple(
            version
            for version in range(1, target_version)
            if not self.has_step(kind, version)
        )
        multi = tuple(
            f"{s.kind.value} {s.from_version}->{s.to_version}"
            for s in steps
            if not s.is_single_bump
        )
        return ChainIntegrityReport(
            kind=kind,
            lowest_version=steps[0].from_version if steps else target_version,
            highest_version=steps[-1].to_version if steps else target_version,
            missing_bumps=missing,
            multi_version_steps=multi,
        )


def default_registry() -> MigrationRegistry:
    """The shipped registry, with every `steps/` module registered into it.

    Imported here rather than at module scope so constructing a bare `MigrationRegistry` in a
    test does not drag the real steps in with it — a test asserting a chain gap needs a
    registry that genuinely has one.
    """
    from . import steps

    registry = MigrationRegistry()
    steps.register_all(registry)
    return registry


__all__ = [
    "MigrationRegistry",
    "RegisteredStep",
    "StepFunction",
    "default_registry",
]
