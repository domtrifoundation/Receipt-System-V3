"""Shared fixtures for Migration's unit tests.

`CountingStep` is a real step function rather than a mock, and it carries the one thing a real
step must get right: it *returns* whether it did work. §8's idempotency hook rests entirely on
that being honest — the runner cannot determine it, since only a step knows what change to look
for — so a fake that recorded calls without answering that question would leave the whole
guarantee untested.

The registries built here are deliberately bare rather than seeded from `default_registry()`. A
test asserting a chain gap needs a registry that genuinely has one, and dragging the shipped
steps in would make that impossible to arrange.
"""

from __future__ import annotations

import asyncio

import pytest

from core.migration.contracts import MigrationStep, StructureKind
from core.migration.registry import MigrationRegistry
from core.migration.runner import MigrationRunner

SCHEMA = StructureKind.DATABASE_SCHEMA


def run(coro):
    """Drive one coroutine to completion; a fresh loop per call.

    `asyncio.run` rather than `pytest-asyncio`, matching every other package's conftest here.
    """
    return asyncio.run(coro)


def step_for(from_version: int, kind: StructureKind = SCHEMA) -> MigrationStep:
    """A single-bump step's metadata, described the way a real one would be."""
    return MigrationStep(
        kind=kind,
        from_version=from_version,
        to_version=from_version + 1,
        description=f"test step {from_version}->{from_version + 1}",
    )


class CountingStep:
    """A real step function that records its calls and reports whether it did work.

    `did_work` is mutable after construction so a test can simulate the case that actually
    matters: the same step returning `True` on a first run and `False` on a re-run, which is
    what a real step does once it finds its change already present.
    """

    def __init__(self, *, did_work: bool = True) -> None:
        self.calls = 0
        self.did_work = did_work

    async def __call__(self, structure_id: str) -> bool:
        self.calls += 1
        return self.did_work


@pytest.fixture
def runner_with():
    """Build a runner over a registry of `{from_version: step_function}`."""

    def _build(steps: dict[int, CountingStep], kind: StructureKind = SCHEMA) -> MigrationRunner:
        registry = MigrationRegistry()
        for from_version, function in steps.items():
            registry.register(step_for(from_version, kind), function)
        return MigrationRunner(registry)

    return _build
