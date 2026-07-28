"""The runner registry and result store (`v3-deepdive-56-test-orchestration.md` §4, §5).

Backs the three RPCs that surface through Agent Control's MCP tool set: `RunTest`,
`GetTestResult`, and `ListAvailableRunners` — the last existing specifically so an agent can
check `is_available()` before attempting a runner that cannot work in its environment.

**On result storage**: §9 logs "long-running test result storage/retention" as genuinely
open — a lightweight table of its own versus Persistence's general write path is not picked
there, and it is not picked here either. This keeps results in memory for the lifetime of
the service, which is enough for the polling model to work and deliberately does not
pre-empt that decision by creating a schema someone would then have to migrate away from.
"""

from __future__ import annotations

from .contracts import TestResult, TestRun, TestSpec, TestStatus
from .runners import (
    BenchSuiteRunner,
    CrashIsolationRunner,
    EnvironmentResetRunner,
    PipelineIntegrationRunner,
)

#: Tool names exposed through Agent Control, all `TEST_EXECUTION`-categorized (§5) — these
#: trigger real actions with real side effects, which is why Tool Call API gave them their
#: own category rather than folding them into `DEV_OBSERVABILITY`.
TEST_ORCHESTRATION_TOOLS = (
    "run_bench_suite", "run_crash_isolation_test",
    "run_pipeline_integration_test", "reset_test_environment",
    "get_test_run_result", "list_available_test_runners",
)


class TestOrchestrator:
    def __init__(self, declared_test_tenants: frozenset[str] = frozenset()) -> None:
        self._runners = {
            r.name: r
            for r in (
                BenchSuiteRunner(),
                CrashIsolationRunner(),
                PipelineIntegrationRunner(),
                EnvironmentResetRunner(declared_test_tenants),
            )
        }
        self._runs: dict[str, TestRun] = {}

    async def list_available_runners(self) -> list[dict]:
        out = []
        for name, runner in sorted(self._runners.items()):
            available = await runner.is_available()
            out.append({
                "runner": name,
                "available": available,
                "unavailable_reason": "" if available else runner.unavailable_reason,
            })
        return out

    async def run_test(self, spec: TestSpec) -> TestResult:
        runner = self._runners.get(spec.runner)
        if runner is None:
            from common.frozen_dict import FrozenDict
            from ..contracts import utcnow
            now = utcnow()
            return TestResult(
                run_id="", runner=spec.runner, status=TestStatus.FAILED,
                started_at=now, finished_at=now,
                detail=f"no such runner: {spec.runner!r}; "
                       f"available: {sorted(self._runners)}",
                findings=FrozenDict({}),
            )
        result = await runner.run(spec)
        self._runs[result.run_id] = TestRun(run_id=result.run_id, spec=spec, result=result)
        return result

    def get_test_result(self, run_id: str) -> TestResult | None:
        run = self._runs.get(run_id)
        return run.result if run else None
