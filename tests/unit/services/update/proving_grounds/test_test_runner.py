"""`test_candidate()` — the real orchestration: isolation check, dispatcher resolution,
download, bench dispatch, exception conversion."""

from __future__ import annotations

from services.update.proving_grounds.test_runner import BenchDispatcherRegistry, DockerContainerRunner
from services.update.proving_grounds.test_runner import test_candidate as run_test_candidate

from .conftest import (
    AlwaysAvailableRunner,
    FailingDispatcher,
    NeverAvailableRunner,
    PassingDispatcher,
    RaisingDispatcher,
    run,
)


def test_candidate_reports_container_runner_unavailable(dependency_candidate):
    registry = BenchDispatcherRegistry((PassingDispatcher(),))

    result = run(run_test_candidate(dependency_candidate, dispatchers=registry, container_runner=NeverAvailableRunner()))

    assert result.ok is False
    assert result.error_code == "CONTAINER_RUNNER_UNAVAILABLE"


def test_candidate_reports_no_bench_dispatcher(dependency_candidate):
    empty_registry = BenchDispatcherRegistry()

    result = run(run_test_candidate(dependency_candidate, dispatchers=empty_registry, container_runner=AlwaysAvailableRunner()))

    assert result.ok is False
    assert result.error_code == "NO_BENCH_DISPATCHER"


def test_candidate_dispatches_to_the_real_registered_dispatcher(dependency_candidate):
    dispatcher = PassingDispatcher()
    registry = BenchDispatcherRegistry((dispatcher,))

    result = run(run_test_candidate(dependency_candidate, dispatchers=registry, container_runner=AlwaysAvailableRunner()))

    assert result.ok is True
    assert result.passed is True
    assert "rapidocr-onnxruntime" in result.bench_summary
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0] is dependency_candidate


def test_candidate_reports_a_genuine_bench_failure_as_passed_false_ok_true():
    from services.update.proving_grounds.contracts import CandidateKind, TestCandidate

    candidate = TestCandidate(kind=CandidateKind.DEPENDENCY_BUMP, name="x", version="1", affected_api="ocr")
    registry = BenchDispatcherRegistry((FailingDispatcher(),))

    result = run(run_test_candidate(candidate, dispatchers=registry, container_runner=AlwaysAvailableRunner()))

    assert result.ok is True
    assert result.passed is False
    assert "regressed" in result.bench_summary


def test_candidate_converts_a_dispatcher_exception_to_data():
    from services.update.proving_grounds.contracts import CandidateKind, TestCandidate

    candidate = TestCandidate(kind=CandidateKind.DEPENDENCY_BUMP, name="x", version="1", affected_api="inference")
    registry = BenchDispatcherRegistry((RaisingDispatcher(),))

    result = run(run_test_candidate(candidate, dispatchers=registry, container_runner=AlwaysAvailableRunner()))

    assert result.ok is False
    assert result.error_code == "BENCH_DISPATCH_RAISED"
    assert "dispatcher exploded" in result.error_detail


def test_docker_container_runner_is_unavailable_for_a_nonexistent_binary():
    runner = DockerContainerRunner(docker_bin="definitely-not-a-real-binary-xyz-123")

    assert run(runner.is_available()) is False


def test_bench_dispatcher_registry_get_and_known_apis():
    registry = BenchDispatcherRegistry((PassingDispatcher("ocr"), PassingDispatcher("inference")))

    assert registry.get("ocr") is not None
    assert registry.get("not_registered") is None
    assert registry.known_apis() == ("inference", "ocr")
