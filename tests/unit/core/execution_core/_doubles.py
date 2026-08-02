"""Shared test doubles and helpers for Execution Core's suite.

Separated from the tests themselves so that the six test modules mirror the six source modules
they exercise (`docs/PRINCIPLES.md` §1.1's file-size discipline applied to tests), rather than
each carrying its own copy of the same five fakes — five copies of a fake is five chances for
one of them to drift from the `Protocol` it stands in for.

`test_doubles_conform.py` asserts each of these actually satisfies the Protocol in
`contracts.py` it stands in for. That check earns its place: a fake whose signature has drifted
makes a whole suite pass against an interface no production caller uses, which is the most
expensive kind of green suite because it looks exactly like coverage.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core.execution_core.contracts import (
    ReceiptStage,
    Run,
    RunState,
    STAGE_SEQUENCE,
    StageCheckpoint,
    TERMINAL_STAGE,
)


def run(coro):
    """Drive one coroutine to completion.

    `pytest-asyncio` is deliberately not a dependency of this project, so every async test in
    this repo goes through a helper like this one rather than a plugin.
    """
    return asyncio.run(coro)


class FakeCheckpointStore:
    """An in-memory `CheckpointStore`. Records writes so a test can assert what became durable.

    `fail_writes_for` exists so the checkpoint-write-failure asymmetry can be tested against a
    real failure rather than a mocked-out one — §6's guarantee is about what happens when
    Persistence is genuinely unavailable.
    """

    def __init__(self, *, fail_writes_for: set[ReceiptStage] | None = None) -> None:
        self._by_key: dict[tuple[str, ReceiptStage], StageCheckpoint] = {}
        self._by_hash: dict[str, StageCheckpoint] = {}
        self.writes: list[StageCheckpoint] = []
        self._fail_writes_for = fail_writes_for or set()

    async def get_checkpoint(self, receipt_id, stage):
        return self._by_key.get((receipt_id, stage))

    async def write_checkpoint(self, checkpoint):
        if checkpoint.stage in self._fail_writes_for:
            raise RuntimeError("simulated persistence outage")
        self._by_key[(checkpoint.receipt_id, checkpoint.stage)] = checkpoint
        self.writes.append(checkpoint)
        if checkpoint.stage is TERMINAL_STAGE and checkpoint.content_hash:
            self._by_hash[checkpoint.content_hash] = checkpoint

    async def find_written_by_content_hash(self, content_hash):
        return self._by_hash.get(content_hash)


class FakeAttemptCounter:
    """An in-memory `AttemptCounter`, including §7's escalation latch."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, ReceiptStage], int] = {}
        self.escalated: set[tuple[str, ReceiptStage]] = set()

    async def get_attempt_count(self, receipt_id, stage):
        return self.counts.get((receipt_id, stage), 0)

    async def increment_attempt_count(self, receipt_id, stage):
        key = (receipt_id, stage)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def already_escalated(self, receipt_id, stage):
        return (receipt_id, stage) in self.escalated

    async def mark_escalated(self, receipt_id, stage):
        self.escalated.add((receipt_id, stage))


class RecordingFlagger:
    """A `ReviewFlagger` that remembers every flag, so duplicates are visible.

    Keeping a list rather than a count is what lets §7's latching test assert "exactly one"
    rather than "at least one" — the difference between the bug being fixed and being present.
    """

    def __init__(self) -> None:
        self.flags: list[tuple[str, str, object]] = []

    async def create_flag(self, receipt_id, flag_type, details=None):
        self.flags.append((receipt_id, flag_type, details))


class RecordingNarrator:
    """A `HistorianNarrator` that records emissions, or raises if asked to."""

    def __init__(self, *, raises: bool = False) -> None:
        self.emissions: list[tuple[str, str, ReceiptStage]] = []
        self._raises = raises

    async def emit_narrative(self, run_id, receipt_id, stage, result):
        if self._raises:
            raise RuntimeError("historian unreachable")
        self.emissions.append((run_id, receipt_id, stage))


class RecordingKicker:
    """A `WatchdogKicker` that counts kicks, or raises if asked to."""

    def __init__(self, *, raises: bool = False) -> None:
        self.kicks: list[tuple[str, str]] = []
        self._raises = raises

    def kick(self, service, instance_id, version_commit=""):
        if self._raises:
            raise RuntimeError("watchdog unreachable")
        self.kicks.append((service, instance_id))
        return None


class ManualClock:
    """A clock a test moves by hand.

    §5.2's ceiling defaults to 120 seconds. A test that proved the ceiling by sleeping would
    take two minutes and would still only prove it approximately; moving the clock proves it
    exactly and instantly.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def make_run(state: RunState = RunState.OPEN, run_id: str = "run-1") -> Run:
    return Run(
        run_id=run_id,
        user_id="user-1",
        state=state,
        opened_at=datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc),
    )


def stages_for(recorder: list[ReceiptStage], *, fail: ReceiptStage | None = None):
    """A full set of stage callables that record the order they were invoked in.

    Recording the order rather than just the count is what makes §1's sequence assertion
    possible — Matching consuming OCR's text and Inference consuming Matching's vendor context
    means a reordering is a real defect, not a cosmetic one.
    """

    def make(stage: ReceiptStage):
        async def _call():
            recorder.append(stage)
            if stage is fail:
                raise RuntimeError(f"{stage.value} blew up")
            return f"{stage.value}-output"

        return _call

    return {stage: make(stage) for stage in STAGE_SEQUENCE}


__all__ = [
    "FakeAttemptCounter",
    "FakeCheckpointStore",
    "ManualClock",
    "RecordingFlagger",
    "RecordingKicker",
    "RecordingNarrator",
    "make_run",
    "run",
    "stages_for",
]
