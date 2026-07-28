"""Test Orchestration contracts (`v3-deepdive-56-test-orchestration.md` §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.frozen_dict import FrozenDict

from ..contracts import utcnow


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    """The runner cannot meaningfully execute here — a crash-isolation test against a
    sandboxed session, say. Deliberately distinct from FAILED: "this environment cannot
    run this test" is not the same finding as "this test ran and the system misbehaved,"
    and collapsing them would let a genuinely unrunnable test read as a pass or a bug."""


@dataclass(frozen=True)
class TestSpec:
    runner: str
    target_service: str = ""
    test_receipt_path: str = ""
    fixture_dir: str = ""
    tenant_id: str = ""
    options: FrozenDict = field(default_factory=lambda: FrozenDict({}))


@dataclass(frozen=True)
class TestResult:
    run_id: str
    runner: str
    status: TestStatus
    started_at: datetime
    finished_at: datetime | None = None
    detail: str = ""
    findings: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    warnings: tuple[str, ...] = ()
    """Non-fatal signals a human reviewing the result should see — §6's synthetic-fixture
    flag lands here rather than failing the run, because that heuristic is not reliable
    enough to be a hard gate and a false positive must not block real work."""


@dataclass(frozen=True)
class TestRun:
    run_id: str
    spec: TestSpec
    result: TestResult | None = None
    created_at: datetime = field(default_factory=utcnow)
