"""`EnvironmentResetRunner` (`v3-deepdive-56-test-orchestration.md` §3.4).

Wipes a specifically-designated test tenant back to a known clean state. Never touches
anything outside that tenant, and is never usable against a real production tenant — a hard,
checked guard, not a documented expectation.

`assert_safe_target` below is that guard, written now even though the reset itself is Phase 2
work. It is the part worth having early: the destructive half is useless without it, and a
guard added after the fact is a guard that was absent for however long the gap lasted.
"""

from __future__ import annotations

from ..contracts import TestResult, TestSpec, TestStatus
from .base import BaseRunner

TEST_TENANT_PREFIX = "test_"


class UnsafeResetTarget(Exception):
    """Raised when a reset is aimed at anything not provably a test tenant."""


def assert_safe_target(tenant_id: str, declared_test_tenants: frozenset[str]) -> None:
    """Fail closed (`docs/PRINCIPLES.md` §4.2): anything not provably a test tenant is
    treated as production. An empty tenant id is refused rather than interpreted as
    'all' or 'default' — the most destructive possible reading of a missing value."""
    if not tenant_id:
        raise UnsafeResetTarget("no tenant_id given; refusing to guess a reset target")
    if tenant_id not in declared_test_tenants:
        raise UnsafeResetTarget(
            f"{tenant_id!r} is not in the declared test-tenant allowlist; refusing"
        )
    if not tenant_id.startswith(TEST_TENANT_PREFIX):
        raise UnsafeResetTarget(
            f"{tenant_id!r} is allowlisted but lacks the {TEST_TENANT_PREFIX!r} prefix — "
            "both checks must agree before anything is wiped"
        )


class EnvironmentResetRunner(BaseRunner):
    name = "environment_reset"
    unavailable_reason = (
        "requires Persistence's per-tenant databases (core/persistence/, Phase 2) — there "
        "is no tenant state to reset yet"
    )

    def __init__(self, declared_test_tenants: frozenset[str] = frozenset()) -> None:
        self._allowed = declared_test_tenants

    async def run(self, spec: TestSpec) -> TestResult:
        try:
            assert_safe_target(spec.tenant_id, self._allowed)
        except UnsafeResetTarget as e:
            # Checked before availability on purpose: an unsafe target is a finding worth
            # reporting even in an environment where the reset could not have run anyway.
            return self._result(TestStatus.FAILED, str(e))
        if not await self.is_available():
            return self._unavailable()
        raise NotImplementedError  # pragma: no cover - Phase 2
