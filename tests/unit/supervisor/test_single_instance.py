"""`restart_service_on_version()` — §5.4's own real staged pipeline, and the stated
asymmetry §7's own testing hook names: a step-1 failure never reaches step 2."""

from __future__ import annotations

from pathlib import Path

from supervisor.contracts import ServiceSpec
from supervisor.single_instance import find_release_dir_for_version, restart_service_on_version

from .conftest import free_port, run


async def _collect(gen):
    return [item async for item in gen]


def test_find_release_dir_for_version_matches_the_prefix(tmp_path: Path):
    releases_dir = tmp_path / "releases"
    (releases_dir / "x03.01.05_abc123").mkdir(parents=True)

    found = find_release_dir_for_version(releases_dir, "x03.01.05")

    assert found == releases_dir / "x03.01.05_abc123"


def test_find_release_dir_for_version_returns_none_when_absent(tmp_path: Path):
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()

    assert find_release_dir_for_version(releases_dir, "x99.99.99") is None


def test_restart_fails_at_confirming_target_when_no_release_exists(tmp_path: Path):
    spec = ServiceSpec(name="inference", import_path="core.inference", serve_module="x", address=f"127.0.0.1:{free_port()}")

    results = run(_collect(restart_service_on_version(
        "inference", "x99.99.99", tmp_path / "releases", spec, current_pid=None,
    )))

    assert [r.stage for r in results] == ["confirming_target", "failed"]
    assert "no release clone found" in results[-1].error_detail


def test_restart_fails_at_confirming_target_when_venv_is_not_provisioned(tmp_path: Path):
    releases_dir = tmp_path / "releases"
    (releases_dir / "x03.01.05_abc123").mkdir(parents=True)
    spec = ServiceSpec(name="inference", import_path="core.inference", serve_module="x", address=f"127.0.0.1:{free_port()}")

    results = run(_collect(restart_service_on_version(
        "inference", "x03.01.05", releases_dir, spec, current_pid=None,
    )))

    assert [r.stage for r in results] == ["confirming_target", "failed"]
    assert "not health-check-capable" in results[-1].error_detail


def test_restart_proceeds_through_every_stage_once_target_is_confirmed(tmp_path: Path):
    """The step-1-passes case: every later stage is genuinely attempted, even though
    this fake release has no real service code — proves the pipeline itself advances
    correctly rather than short-circuiting."""
    releases_dir = tmp_path / "releases"
    release_dir = releases_dir / "x03.01.05_abc123"
    (release_dir / ".venvs" / "core.inference").mkdir(parents=True)
    spec = ServiceSpec(
        name="inference", import_path="core.inference", serve_module="core.does_not_exist.service",
        address=f"127.0.0.1:{free_port()}",
    )

    results = run(_collect(restart_service_on_version(
        "inference", "x03.01.05", releases_dir, spec, current_pid=None, timeout_seconds=3.0,
    )))

    stages = [r.stage for r in results]
    assert stages == ["confirming_target", "stopping_old", "launching_new", "waiting_healthy", "failed"]


def test_restart_stopping_old_tolerates_an_already_dead_pid(tmp_path: Path):
    """Stopping a pid that no longer exists must not itself be treated as a failure —
    §5.4's own "stopping_old" step against a process that already exited."""
    releases_dir = tmp_path / "releases"
    release_dir = releases_dir / "x03.01.05_abc123"
    (release_dir / ".venvs" / "core.inference").mkdir(parents=True)
    spec = ServiceSpec(
        name="inference", import_path="core.inference", serve_module="core.does_not_exist.service",
        address=f"127.0.0.1:{free_port()}",
    )

    results = run(_collect(restart_service_on_version(
        "inference", "x03.01.05", releases_dir, spec, current_pid=999999, timeout_seconds=3.0,
    )))

    assert "stopping_old" in [r.stage for r in results]
