"""`TelemetreesServicer` — the real assembly point wiring `TrackedDependencyRegistry` and
the real `docs/CHANGELOG.md` file to `telemetrees.proto`'s wire surface. The deep-dive's
own §6 sketches this exact two-RPC contract; no `.proto` or servicer existed for it."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.telemetrees.dependencies_warden.registry import TrackedDependencyRegistry  # noqa: E402
from core.telemetrees.generated import telemetrees_pb2 as pb  # noqa: E402
from core.telemetrees.service import TelemetreesServicer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_get_tracked_dependencies_returns_the_real_inventory():
    servicer = TelemetreesServicer()

    response = run(servicer.GetTrackedDependencies(pb.TrackedDepsRequest()))

    assert response.error_code == ""
    assert len(response.dependencies) > 0
    names = {d.name for d in response.dependencies}
    assert "authlib" in names


def test_get_tracked_dependencies_filters_by_fact_kind():
    servicer = TelemetreesServicer()

    response = run(servicer.GetTrackedDependencies(pb.TrackedDepsRequest(fact_kind="free_threading_support")))

    assert response.error_code == ""
    assert len(response.dependencies) > 0
    assert all("free_threading_support" in d.fact_kinds for d in response.dependencies)


def test_get_tracked_dependencies_rejects_an_unknown_fact_kind():
    servicer = TelemetreesServicer()

    response = run(servicer.GetTrackedDependencies(pb.TrackedDepsRequest(fact_kind="not_a_real_kind")))

    assert response.error_code == "UNKNOWN_FACT_KIND"
    assert list(response.dependencies) == []


def test_get_changelog_reads_a_real_file(tmp_path):
    changelog_dir = tmp_path / "docs"
    changelog_dir.mkdir()
    (changelog_dir / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n### Added\n- test entry\n", encoding="utf-8")
    servicer = TelemetreesServicer(repo_root=tmp_path)

    response = run(servicer.GetChangelog(pb.ChangelogRequest()))

    assert response.error_code == ""
    assert "test entry" in response.markdown


def test_get_changelog_on_a_repo_with_no_changelog_yet_returns_empty_not_an_error(tmp_path):
    servicer = TelemetreesServicer(repo_root=tmp_path)

    response = run(servicer.GetChangelog(pb.ChangelogRequest()))

    assert response.error_code == ""
    assert response.markdown == ""


def test_get_tracked_dependencies_reflects_a_custom_registry():
    from core.telemetrees.dependencies_warden.contracts import TrackedDependency, TrackedFactKind

    registry = TrackedDependencyRegistry(seed={})
    registry.register(TrackedDependency(
        name="example-pkg", fact_kinds=(TrackedFactKind.RELEASE_VERSION,), notes="test-only entry",
    ))
    servicer = TelemetreesServicer(registry)

    response = run(servicer.GetTrackedDependencies(pb.TrackedDepsRequest()))

    assert [d.name for d in response.dependencies] == ["example-pkg"]


# --- GetOptIn / SetOptIn -----------------------------------------------------------------------


def test_get_opt_in_reports_unknown_with_no_install_root():
    servicer = TelemetreesServicer()

    response = run(servicer.GetOptIn(pb.OptInConfigRequest()))

    assert response.known is False


def test_get_opt_in_defaults_to_false(tmp_path):
    servicer = TelemetreesServicer(install_root=tmp_path)

    response = run(servicer.GetOptIn(pb.OptInConfigRequest()))

    assert response.known is True
    assert response.opt_in is False


def test_set_opt_in_persists_for_real(tmp_path):
    servicer = TelemetreesServicer(install_root=tmp_path)

    set_response = run(servicer.SetOptIn(pb.SetOptInRequest(opt_in=True)))
    get_response = run(servicer.GetOptIn(pb.OptInConfigRequest()))

    assert set_response.opt_in is True
    assert get_response.opt_in is True


def test_set_opt_in_honors_an_explicit_install_root_override(tmp_path):
    servicer = TelemetreesServicer()  # no constructor install_root at all

    run(servicer.SetOptIn(pb.SetOptInRequest(install_root=str(tmp_path), opt_in=True)))
    response = run(servicer.GetOptIn(pb.OptInConfigRequest(install_root=str(tmp_path))))

    assert response.opt_in is True
