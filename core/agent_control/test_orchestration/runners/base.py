"""The `TestRunner` protocol — a real Provider Registry (`v3-deepdive-56-test-orchestration.md` §3).

Same pattern as every other pluggable capability in this project (`docs/PRINCIPLES.md`
§1.2): runners register, more than one can exist, and a caller asks which are actually
usable rather than assuming.

`is_available()` is load-bearing rather than decorative. A crash-isolation test is not
meaningful against a sandboxed session, and a bench run is not meaningful without the bench
fixtures — an agent should be able to ask before attempting one that cannot work, and get
`UNAVAILABLE` rather than a failure it would misread as a bug.
"""

from __future__ import annotations

import secrets
from typing import Protocol, runtime_checkable

from ..contracts import TestResult, TestSpec, TestStatus
from ...contracts import utcnow


@runtime_checkable
class TestRunner(Protocol):
    name: str

    async def run(self, spec: TestSpec) -> TestResult: ...

    async def is_available(self) -> bool: ...


class BaseRunner:
    """Shared result plumbing. Not a required base class — the Protocol is the contract."""

    name: str = "base"
    #: Why this runner cannot run yet, when it cannot. Phase 2 clears these as the services
    #: each runner drives are actually implemented.
    unavailable_reason: str = ""

    @staticmethod
    def new_run_id() -> str:
        return secrets.token_hex(8)

    def _result(
        self,
        status: TestStatus,
        detail: str = "",
        findings: dict | None = None,
        warnings: tuple[str, ...] = (),
        run_id: str | None = None,
    ) -> TestResult:
        from common.frozen_dict import FrozenDict

        now = utcnow()
        return TestResult(
            run_id=run_id or self.new_run_id(),
            runner=self.name,
            status=status,
            started_at=now,
            finished_at=now,
            detail=detail,
            findings=FrozenDict(findings or {}),
            warnings=warnings,
        )

    def _unavailable(self) -> TestResult:
        return self._result(TestStatus.UNAVAILABLE, self.unavailable_reason)

    async def is_available(self) -> bool:
        return not self.unavailable_reason

    async def run(self, spec: TestSpec) -> TestResult:  # pragma: no cover - overridden
        if not await self.is_available():
            return self._unavailable()
        raise NotImplementedError
