"""`ProvingGroundsServicer` — the real gRPC adapter over `test_runner.test_candidate()`,
plus the real in-memory test-history store `GetTestHistory` reads from."""

from __future__ import annotations

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from services.update.proving_grounds.generated import proving_grounds_pb2 as pb  # noqa: E402
from services.update.proving_grounds.service import ProvingGroundsServicer  # noqa: E402
from services.update.proving_grounds.test_runner import BenchDispatcherRegistry  # noqa: E402

from .conftest import AlwaysAvailableRunner, PassingDispatcher, run  # noqa: E402


def _servicer(affected_api: str = "ocr") -> ProvingGroundsServicer:
    registry = BenchDispatcherRegistry((PassingDispatcher(affected_api),))
    return ProvingGroundsServicer(dispatchers=registry, container_runner=AlwaysAvailableRunner())


def test_test_candidate_rpc_runs_a_real_dispatch():
    servicer = _servicer()

    response = run(servicer.TestCandidate(pb.TestCandidateRequest(
        kind="dependency_bump", name="rapidocr-onnxruntime", version="1.5.0", affected_api="ocr",
    )))

    assert response.error_code == ""
    assert response.result.passed is True
    assert "rapidocr-onnxruntime" in response.result.bench_summary


def test_test_candidate_rpc_rejects_an_unknown_kind():
    servicer = _servicer()

    response = run(servicer.TestCandidate(pb.TestCandidateRequest(
        kind="not_a_real_kind", name="x", version="1", affected_api="ocr",
    )))

    assert response.error_code == "UNKNOWN_CANDIDATE_KIND"


def test_get_test_history_rpc_records_a_real_call():
    servicer = _servicer()
    run(servicer.TestCandidate(pb.TestCandidateRequest(kind="dependency_bump", name="x", version="1", affected_api="ocr")))

    response = run(servicer.GetTestHistory(pb.HistoryRequest()))

    assert len(response.results) == 1
    assert response.results[0].affected_api == "ocr"


def test_get_test_history_rpc_filters_by_affected_api():
    servicer = _servicer()
    run(servicer.TestCandidate(pb.TestCandidateRequest(kind="dependency_bump", name="x", version="1", affected_api="ocr")))

    response = run(servicer.GetTestHistory(pb.HistoryRequest(affected_api="inference")))

    assert list(response.results) == []


def test_get_test_history_rpc_on_a_fresh_servicer_returns_empty():
    servicer = _servicer()

    response = run(servicer.GetTestHistory(pb.HistoryRequest()))

    assert list(response.results) == []
