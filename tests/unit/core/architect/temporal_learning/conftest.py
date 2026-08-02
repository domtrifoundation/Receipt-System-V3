"""Shared wiring for the temporal_learning tests.

One helper builds the whole pipeline — entity manager, queue, layering service — because
every test in this folder needs all three and the interesting assertions are about how
they refuse each other, not about how they are constructed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.architect.temporal_learning.entities import EntityManager
from core.architect.temporal_learning.layering import LayeringService
from core.architect.temporal_learning.moderation_queue import (
    ModerationQueue,
    PrescreenRegistry,
)


@dataclass
class Pipeline:
    entities: EntityManager
    queue: ModerationQueue
    layering: LayeringService


@pytest.fixture
def pipeline() -> Pipeline:
    entities = EntityManager()
    queue = ModerationQueue(entities)
    return Pipeline(entities=entities, queue=queue, layering=LayeringService(entities, queue))


class UnavailablePrescreen:
    """Stands in for an instance with no Inference capacity at all."""

    name = "unavailable"

    async def prescreen(self, contribution):
        from core.architect.temporal_learning.moderation_queue import PrescreenVerdict

        return PrescreenVerdict(self.name, False, "unavailable", "no capacity", available=False)


@pytest.fixture
def pipeline_without_prescreen() -> Pipeline:
    entities = EntityManager()
    queue = ModerationQueue(entities, prescreen=PrescreenRegistry((UnavailablePrescreen(),)))
    return Pipeline(entities=entities, queue=queue, layering=LayeringService(entities, queue))
