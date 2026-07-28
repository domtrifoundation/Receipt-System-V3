"""Test runners — a real Provider Registry (`docs/PRINCIPLES.md` §1.2)."""

from .base import BaseRunner, TestRunner
from .bench_suite_runner import BenchSuiteRunner, inspect_fixture_dir
from .crash_isolation_runner import CrashIsolationRunner
from .environment_reset_runner import (
    EnvironmentResetRunner,
    UnsafeResetTarget,
    assert_safe_target,
)
from .pipeline_integration_runner import PipelineIntegrationRunner

__all__ = [
    "BaseRunner", "TestRunner", "BenchSuiteRunner", "inspect_fixture_dir",
    "CrashIsolationRunner", "EnvironmentResetRunner", "UnsafeResetTarget",
    "assert_safe_target", "PipelineIntegrationRunner",
]
