"""Shared fixtures for Proving Grounds' unit tests."""

from __future__ import annotations

import asyncio

import pytest

from services.update.proving_grounds.contracts import CandidateKind, TestCandidate


def run(coro):
    return asyncio.run(coro)


class AlwaysAvailableRunner:
    """A real `ContainerRunner` implementation, not a mock — reports available and
    successfully runs anything asked of it, standing in for a real Docker daemon."""

    async def is_available(self) -> bool:
        return True

    async def run(self, image: str, command: list[str], *, workdir):
        return True, "ok"


class NeverAvailableRunner:
    async def is_available(self) -> bool:
        return False

    async def run(self, image: str, command: list[str], *, workdir):
        return False, "unavailable"


class PassingDispatcher:
    def __init__(self, affected_api: str = "ocr") -> None:
        self.affected_api = affected_api
        self.calls: list[TestCandidate] = []

    async def run_bench(self, candidate: TestCandidate, workdir):
        self.calls.append(candidate)
        return True, f"bench passed for {candidate.name} {candidate.version}"


class FailingDispatcher:
    affected_api = "ocr"

    async def run_bench(self, candidate: TestCandidate, workdir):
        return False, "bench failed: 2 of 40 cases regressed"


class RaisingDispatcher:
    affected_api = "inference"

    async def run_bench(self, candidate: TestCandidate, workdir):
        raise RuntimeError("dispatcher exploded")


@pytest.fixture
def dependency_candidate() -> TestCandidate:
    return TestCandidate(
        kind=CandidateKind.DEPENDENCY_BUMP, name="rapidocr-onnxruntime", version="1.5.0",
        affected_api="ocr",
    )
