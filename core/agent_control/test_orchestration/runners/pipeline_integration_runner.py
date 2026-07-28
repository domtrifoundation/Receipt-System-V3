"""`PipelineIntegrationRunner` (`v3-deepdive-56-test-orchestration.md` §3.3).

Submits a real receipt through Ingestion, then polls Execution Core's own `GetRunStatus`
until the run reaches `WRITTEN` or a terminal failure, recording which stage failed (if any)
and Historian's narrative for what happened at each stage along the way.

The thing this gives an agent that a bare script would not: one structured result
summarizing an entire multi-service, multi-second pipeline run, instead of the agent having
to poll and cross-reference logs across five services itself.
"""

from __future__ import annotations

from ..contracts import TestResult, TestSpec, TestStatus
from .base import BaseRunner


class PipelineIntegrationRunner(BaseRunner):
    name = "pipeline_integration"
    unavailable_reason = (
        "requires Ingestion, Execution Core, and Historian (Phase 2) — there is no pipeline "
        "to submit a receipt through yet"
    )

    async def run(self, spec: TestSpec) -> TestResult:
        if not await self.is_available():
            return self._unavailable()
        if not spec.test_receipt_path:  # pragma: no cover - Phase 2
            return self._result(TestStatus.FAILED, "spec.test_receipt_path is required")
        raise NotImplementedError  # pragma: no cover - Phase 2
