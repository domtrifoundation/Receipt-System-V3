"""`TaskSchedulerServicer` — the real assembly point wiring `TaskSchedulerService`
(itself new this session) to `task_scheduler.proto`'s wire surface. `CLAUDE.md`'s own
"Known gap" section named this by name: a five-RPC surface specified with no `.proto`
compiled at all."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.task_scheduler.generated import task_scheduler_pb2 as pb  # noqa: E402
from core.task_scheduler.grpc_servicer import TaskSchedulerServicer  # noqa: E402
from core.task_scheduler.service import TaskSchedulerService  # noqa: E402

WEEKLY_SUNDAY_2AM = "0 2 * * 0"

OWNER_SESSION = "sess-owner"
STAFF_SESSION = "sess-staff"
CLIENT_SESSION = "sess-client"

SESSIONS = {
    OWNER_SESSION: ("owner-1", "owner"),
    STAFF_SESSION: ("staff-1", "staff"),
    CLIENT_SESSION: ("client-1", "client"),
}


def run(coro):
    return asyncio.run(coro)


def resolve_session(session_id: str):
    return SESSIONS.get(session_id)


@pytest.fixture
def servicer(registry, tmp_path):
    service = TaskSchedulerService(actions=registry, top_level=tmp_path)
    yield TaskSchedulerServicer(service, sessions=resolve_session)
    service.close()


def test_create_scheduled_task_rpc_creates_a_real_row(servicer):
    response = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="full_rescan", action_params={"since": "30d"},
        cron_expression=WEEKLY_SUNDAY_2AM, enabled=True,
    )))

    assert response.error_code == ""
    assert response.task.action == "full_rescan"
    assert dict(response.task.action_params) == {"since": "30d"}
    assert response.task.enabled is True


def test_create_scheduled_task_rpc_denies_a_client_role(servicer):
    response = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=CLIENT_SESSION, action="full_rescan", cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_create_scheduled_task_rpc_denies_an_unresolvable_session(servicer):
    response = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id="not-a-real-session", action="full_rescan", cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    assert response.error_code == "ROLE_FORBIDDEN"


def test_create_scheduled_task_rpc_rejects_an_unregistered_action(servicer):
    response = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="not_on_the_allowlist", cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    assert response.error_code == "UNKNOWN_SCHEDULABLE_ACTION"
    assert not response.HasField("task")


def test_create_scheduled_task_rpc_rejects_a_malformed_cron_expression(servicer):
    response = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="full_rescan", cron_expression="not a cron",
    )))

    assert response.error_code == "INVALID_CRON_EXPRESSION"


def test_update_scheduled_task_rpc_changes_only_the_requested_field(servicer):
    created = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="full_rescan", action_params={"since": "30d"},
        cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    response = run(servicer.UpdateScheduledTask(pb.UpdateTaskRequest(
        session_id=OWNER_SESSION, task_id=created.task.task_id, cron_expression="0 3 * * 0",
    )))

    assert response.error_code == ""
    assert response.task.cron_expression == "0 3 * * 0"
    assert dict(response.task.action_params) == {"since": "30d"}


def test_update_scheduled_task_rpc_reports_task_not_found(servicer):
    response = run(servicer.UpdateScheduledTask(pb.UpdateTaskRequest(
        session_id=OWNER_SESSION, task_id="does-not-exist", cron_expression="0 3 * * 0",
    )))

    assert response.error_code == "TASK_NOT_FOUND"


def test_delete_scheduled_task_rpc_removes_a_real_row(servicer):
    created = run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="full_rescan", cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    deleted = run(servicer.DeleteScheduledTask(pb.DeleteTaskRequest(
        session_id=OWNER_SESSION, task_id=created.task.task_id,
    )))
    listed = run(servicer.ListScheduledTasks(pb.ListTasksRequest(session_id=OWNER_SESSION)))

    assert deleted.ok is True
    assert list(listed.tasks) == []


def test_list_scheduled_tasks_rpc_is_scoped_per_user(servicer):
    run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=OWNER_SESSION, action="full_rescan", cron_expression=WEEKLY_SUNDAY_2AM,
    )))
    run(servicer.CreateScheduledTask(pb.CreateTaskRequest(
        session_id=STAFF_SESSION, action="full_rescan", cron_expression=WEEKLY_SUNDAY_2AM,
    )))

    owner_list = run(servicer.ListScheduledTasks(pb.ListTasksRequest(session_id=OWNER_SESSION)))
    staff_list = run(servicer.ListScheduledTasks(pb.ListTasksRequest(session_id=STAFF_SESSION)))

    assert len(owner_list.tasks) == 1
    assert owner_list.tasks[0].created_by == "owner-1"
    assert len(staff_list.tasks) == 1
    assert staff_list.tasks[0].created_by == "staff-1"


def test_list_schedulable_actions_rpc_returns_the_real_allowlist(servicer):
    response = run(servicer.ListSchedulableActions(pb.ListActionsRequest()))

    assert {a.name for a in response.actions} == {"full_rescan", "generate_slsp_export"}


def test_list_schedulable_actions_rpc_needs_no_session():
    """A public read — the allowlist carries no per-user data (unlike every other RPC in
    this surface)."""
    service = TaskSchedulerService()
    servicer = TaskSchedulerServicer(service, sessions=lambda _sid: None)

    response = run(servicer.ListSchedulableActions(pb.ListActionsRequest()))

    assert response.error_code == ""
