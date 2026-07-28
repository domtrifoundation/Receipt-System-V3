"""`CrashIsolationRunner` (`v3-deepdive-56-test-orchestration.md` §3.2).

Deliberately SIGKILLs a named service's *worker* process — not the parent service process,
since worker-level isolation is exactly what is under test — then observes the parent's
health, whether a subsequent request triggers a clean reload rather than hanging, and
whether any other service was affected at all.

**The hard rule this runner exists under**: the target process is always one Supervisor
itself identified, never a `pkill` by name. A name match risks killing the wrong process on
a machine running several services, and this is the only component in the system that
deliberately signals another service's processes at all (`docs/PROCESS_TOPOLOGY.md` §7) —
that privilege comes with the narrower targeting rule, not despite it.
"""

from __future__ import annotations

from ..contracts import TestResult, TestSpec, TestStatus
from .base import BaseRunner


class CrashIsolationRunner(BaseRunner):
    name = "crash_isolation"
    unavailable_reason = (
        "requires Supervisor to identify the target worker process (supervisor/, Phase 2) "
        "and a running service cluster to observe — neither exists yet"
    )

    async def run(self, spec: TestSpec) -> TestResult:
        if not await self.is_available():
            return self._unavailable()

        if not spec.target_service:  # pragma: no cover - Phase 2
            return self._result(
                TestStatus.FAILED,
                "spec.target_service is required — this runner never selects a target itself",
            )
        raise NotImplementedError  # pragma: no cover - Phase 2
