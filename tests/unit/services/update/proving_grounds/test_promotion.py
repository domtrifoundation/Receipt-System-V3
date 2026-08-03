"""`gate_promotion()` — §7's own "promotion-gate bypass test" hook: there must be no
path to promotion that skips this function or the health-check discipline it enforces."""

from __future__ import annotations

from services.update.proving_grounds.contracts import TestResult, utcnow
from services.update.proving_grounds.promotion import gate_promotion

from .conftest import run


def test_gate_promotion_allows_a_passing_ok_result(dependency_candidate):
    result = TestResult(candidate=dependency_candidate, passed=True, started_at=utcnow(), finished_at=utcnow())

    assert run(gate_promotion("stable", dependency_candidate, result)) is True


def test_gate_promotion_denies_a_genuine_failure(dependency_candidate):
    result = TestResult(candidate=dependency_candidate, passed=False, started_at=utcnow(), finished_at=utcnow())

    assert run(gate_promotion("stable", dependency_candidate, result)) is False


def test_gate_promotion_denies_a_result_that_never_actually_ran(dependency_candidate):
    """`passed=True` on a result whose test could not run at all (`ok=False`) must still
    be denied — the whole reason `ok` and `passed` are separate fields."""
    result = TestResult(
        candidate=dependency_candidate, passed=True, started_at=utcnow(), finished_at=utcnow(),
        error_code="CONTAINER_RUNNER_UNAVAILABLE", error_detail="docker unreachable",
    )

    assert run(gate_promotion("stable", dependency_candidate, result)) is False
