"""`MigrationServicer` — the real assembly point wiring `runner.MigrationRunner` to
`migration.proto`'s wire surface. `CLAUDE.md`'s own "Known gap" section named this by
name: a two-RPC surface specified in the deep-dive with no `.proto` compiled at all."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.migration.generated import migration_pb2 as pb  # noqa: E402
from core.migration.registry import MigrationRegistry  # noqa: E402
from core.migration.runner import MigrationRunner  # noqa: E402
from core.migration.service import MigrationServicer  # noqa: E402

from .conftest import CountingStep, SCHEMA, step_for  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_get_current_version_returns_this_builds_own_target():
    servicer = MigrationServicer()

    response = run(servicer.GetCurrentVersion(pb.VersionRequest(kind="database_schema")))

    assert response.error_code == ""
    assert response.current_version == 1


def test_get_current_version_rejects_an_unknown_kind_string():
    servicer = MigrationServicer()

    response = run(servicer.GetCurrentVersion(pb.VersionRequest(kind="not_a_real_kind")))

    assert response.error_code == "UNKNOWN_STRUCTURE_KIND"


def test_run_migration_walks_a_chain_of_real_steps():
    registry = MigrationRegistry()
    step_0 = CountingStep()
    step_1 = CountingStep()
    registry.register(step_for(0), step_0)
    registry.register(step_for(1), step_1)
    servicer = MigrationServicer(registry)

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="user-1-db", kind="database_schema", current_version=0, target_version=2,
    )))

    assert response.error_code == ""
    assert response.reached_version == 2
    assert response.target_version == 2
    assert len(response.steps) == 2
    assert [s.outcome for s in response.steps] == ["applied", "applied"]


def test_run_migration_reports_already_applied_on_a_re_run():
    registry = MigrationRegistry()
    step = CountingStep(did_work=False)
    registry.register(step_for(0), step)
    servicer = MigrationServicer(registry)

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="user-1-db", kind="database_schema", current_version=0, target_version=1,
    )))

    assert response.steps[0].outcome == "already_applied"


def test_run_migration_stops_at_a_real_chain_gap():
    registry = MigrationRegistry()  # deliberately empty — no 0->1 step registered
    servicer = MigrationServicer(registry)

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="user-1-db", kind="database_schema", current_version=0, target_version=1,
    )))

    assert response.error_code == "MISSING_MIGRATION_STEP"
    assert response.reached_version == 0


def test_run_migration_a_structure_already_at_target_is_a_trivial_complete_walk():
    servicer = MigrationServicer(MigrationRegistry())

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="user-1-db", kind="database_schema", current_version=1, target_version=1,
    )))

    assert response.error_code == ""
    assert response.reached_version == 1
    assert len(response.steps) == 0


def test_run_migration_rejects_an_unknown_kind_string():
    servicer = MigrationServicer(MigrationRegistry())

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="s1", kind="not_a_real_kind", current_version=0,
    )))

    assert response.error_code == "UNKNOWN_STRUCTURE_KIND"


def test_run_migration_target_version_zero_defers_to_this_builds_default():
    registry = MigrationRegistry()
    servicer = MigrationServicer(registry)

    response = run(servicer.RunMigration(pb.MigrationRequest(
        structure_id="user-1-db", kind="database_schema", current_version=1, target_version=0,
    )))

    assert response.target_version == 1
