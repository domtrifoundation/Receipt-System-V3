"""`BackgroundWorkersServicer` — the resolution of the design tension `CLAUDE.md`'s own
"Known gap" section named: the deep-dive specifies no wire contract, while
`docs/PROCESS_TOPOLOGY.md` establishes every Core API as its own gRPC-reachable process.
This surface is deliberately observability/control only (`ListJobs`/`GetJobHealth`/
`GetNextDue`, plus the one explicit staff action `EnableJob`) — see
`background_workers.proto`'s own module comment for the full reasoning."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.background_workers.contracts import (  # noqa: E402
    JobClass,
    JobHealth,
    JobOutcome,
    JobRegistration,
    NextDueEstimate,
    utcnow,
)
from core.background_workers.generated import background_workers_pb2 as pb  # noqa: E402
from core.background_workers.registry import JobRegistry  # noqa: E402
from core.background_workers.service import BackgroundWorkersServicer  # noqa: E402

OWNER_SESSION = "sess-owner"
CLIENT_SESSION = "sess-client"
SESSIONS = {OWNER_SESSION: ("owner-1", "owner"), CLIENT_SESSION: ("client-1", "client")}


def run(coro):
    return asyncio.run(coro)


def resolve_session(session_id: str):
    return SESSIONS.get(session_id)


def _registry_with_one_job() -> JobRegistry:
    registry = JobRegistry()
    registry.register(
        JobRegistration(
            job_id="expired_session_cleanup", owning_api="auth", job_class=JobClass.ASYNC_IO,
            interval_seconds=86400,
        ),
        handler=lambda: None,
    )
    return registry


def test_list_jobs_returns_the_real_registered_job():
    servicer = BackgroundWorkersServicer(_registry_with_one_job(), sessions=resolve_session)

    response = run(servicer.ListJobs(pb.ListJobsRequest()))

    assert len(response.jobs) == 1
    assert response.jobs[0].job_id == "expired_session_cleanup"
    assert response.jobs[0].job_class == "async_io"
    assert response.jobs[0].interval_seconds == 86400
    assert response.jobs[0].event_triggered is False


def test_get_job_health_returns_zeroed_health_for_a_never_run_job():
    servicer = BackgroundWorkersServicer(_registry_with_one_job(), sessions=resolve_session)

    response = run(servicer.GetJobHealth(pb.JobHealthRequest(job_id="expired_session_cleanup")))

    assert response.error_code == ""
    assert response.health.consecutive_failures == 0
    assert response.health.disabled_at == ""


def test_get_job_health_reports_unknown_job():
    servicer = BackgroundWorkersServicer(_registry_with_one_job(), sessions=resolve_session)

    response = run(servicer.GetJobHealth(pb.JobHealthRequest(job_id="no-such-job")))

    assert response.error_code == "UNKNOWN_JOB"


def test_enable_job_denies_a_client_role():
    registry = _registry_with_one_job()
    servicer = BackgroundWorkersServicer(registry, sessions=resolve_session)

    response = run(servicer.EnableJob(pb.EnableJobRequest(session_id=CLIENT_SESSION, job_id="expired_session_cleanup")))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_enable_job_denies_an_unresolvable_session():
    registry = _registry_with_one_job()
    servicer = BackgroundWorkersServicer(registry, sessions=resolve_session)

    response = run(servicer.EnableJob(pb.EnableJobRequest(session_id="not-a-real-session", job_id="expired_session_cleanup")))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_enable_job_clears_a_tripped_failure_guard_for_an_owner():
    registry = _registry_with_one_job()
    registry.record_health(JobHealth(
        job_id="expired_session_cleanup", consecutive_failures=5, total_runs=5, total_failures=5,
        last_run_at=utcnow(), last_outcome=JobOutcome.FAILED,
        disabled_at=utcnow(), disabled_reason="auto-disabled after 5 failures",
    ))
    servicer = BackgroundWorkersServicer(registry, sessions=resolve_session)

    response = run(servicer.EnableJob(pb.EnableJobRequest(session_id=OWNER_SESSION, job_id="expired_session_cleanup")))

    assert response.error_code == ""
    assert response.health.consecutive_failures == 0
    assert response.health.disabled_at == ""
    assert "owner-1" in response.health.disabled_reason


def test_enable_job_reports_unknown_job():
    servicer = BackgroundWorkersServicer(_registry_with_one_job(), sessions=resolve_session)

    response = run(servicer.EnableJob(pb.EnableJobRequest(session_id=OWNER_SESSION, job_id="no-such-job")))

    assert response.error_code == "UNKNOWN_JOB"


def test_get_next_due_returns_empty_when_no_source_is_configured():
    servicer = BackgroundWorkersServicer(_registry_with_one_job(), sessions=resolve_session)

    response = run(servicer.GetNextDue(pb.NextDueRequest()))

    assert list(response.estimates) == []


def test_get_next_due_returns_real_estimates_from_an_injected_source():
    estimate = NextDueEstimate(job_id="expired_session_cleanup", seconds_until_due=120.5, blocked_by_idle=True)
    servicer = BackgroundWorkersServicer(
        _registry_with_one_job(), sessions=resolve_session, next_due_source=lambda: (estimate,),
    )

    response = run(servicer.GetNextDue(pb.NextDueRequest()))

    assert len(response.estimates) == 1
    assert response.estimates[0].job_id == "expired_session_cleanup"
    assert response.estimates[0].seconds_until_due == pytest.approx(120.5)
    assert response.estimates[0].blocked_by_idle is True
