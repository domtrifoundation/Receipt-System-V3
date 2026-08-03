"""`ToolCallServicer` — the real assembly point building a `ToolRegistry` from every
`tools/*.py` module and wiring it, plus `dispatch.dispatch()`, to `tool_call.proto`'s wire
surface. `CLAUDE.md`'s own "Known gap" section named this by name: no wire contract
existed, and every module `tools/*.py` names was itself a 0-byte scaffold."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("grpc", reason="grpcio is not installed in this interpreter")
pytest.importorskip("google.protobuf", reason="protobuf is not installed here")

from core.auth.contracts import Role  # noqa: E402
from core.tool_call.generated import tool_call_pb2 as pb  # noqa: E402
from core.tool_call.service import ToolCallServicer, build_default_registry  # noqa: E402

from .conftest import resolver_for  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _pb_context(calling_api="inference_reconciliation", session_id="sess-1", user_id="user-1"):
    return pb.ToolCallContext(run_id="run-1", user_id=user_id, calling_api=calling_api, session_id=session_id)


def test_build_default_registry_registers_every_real_tool():
    """This was the actual gap: every module in `tools/*.py` was a 0-byte scaffold until
    this session, so nothing existed to register at all."""
    registry = build_default_registry()

    names = {spec.name for spec in registry.all_specs()}
    assert names == {
        "geocode_place", "lookup_vendor_canon", "remember_vendor",
        "persistence_query", "persistence_write_field",
    }


def test_list_tools_filters_by_calling_context_and_role(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.CLIENT))

    response = run(servicer.ListTools(pb.ListToolsRequest(context=_pb_context())))

    names = {t.name for t in response.tools}
    assert names == {"lookup_vendor_canon", "remember_vendor"}


def test_list_tools_shows_agent_control_the_dev_and_test_categories_too(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.STAFF))

    response = run(servicer.ListTools(pb.ListToolsRequest(
        context=_pb_context(calling_api="agent_control"),
    )))

    names = {t.name for t in response.tools}
    assert "get_run_status" in names
    assert "reset_test_environment" in names


def test_list_tools_denies_an_unresolvable_session(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(None))

    response = run(servicer.ListTools(pb.ListToolsRequest(context=_pb_context())))

    assert list(response.tools) == []


def test_list_tools_denies_an_unknown_calling_context(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.OWNER))

    response = run(servicer.ListTools(pb.ListToolsRequest(
        context=_pb_context(calling_api="not_a_real_caller"),
    )))

    assert list(response.tools) == []


def test_dispatch_tool_runs_a_real_registered_tool_and_returns_its_result(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.CLIENT))

    response = run(servicer.DispatchTool(pb.DispatchToolRequest(
        context=_pb_context(), tool_name="lookup_vendor_canon",
        arguments_json=json.dumps({"query": "Acme"}),
    )))

    assert response.error_code == ""
    result = json.loads(response.result_json)
    assert result["echoed"] == {"query": "Acme"}
    assert result["run_id"] == "run-1"


def test_dispatch_tool_denies_an_unregistered_tool(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.CLIENT))

    response = run(servicer.DispatchTool(pb.DispatchToolRequest(
        context=_pb_context(), tool_name="not_a_real_tool", arguments_json="{}",
    )))

    assert response.error_code == "UNREGISTERED_TOOL"


def test_dispatch_tool_denies_a_context_not_enabled_for_a_category(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.STAFF))

    response = run(servicer.DispatchTool(pb.DispatchToolRequest(
        context=_pb_context(), tool_name="get_run_status", arguments_json="{}",
    )))

    assert response.error_code == "CONTEXT_NOT_ENABLED"


def test_dispatch_tool_denies_a_client_role_for_dev_observability(registry):
    servicer = ToolCallServicer(registry, resolver=resolver_for(Role.CLIENT))

    response = run(servicer.DispatchTool(pb.DispatchToolRequest(
        context=_pb_context(calling_api="agent_control"), tool_name="get_run_status",
        arguments_json="{}",
    )))

    assert response.error_code == "PERMISSION_DENIED"


def test_dispatch_tool_reports_invalid_arguments_json():
    servicer = ToolCallServicer(resolver=resolver_for(Role.CLIENT))

    response = run(servicer.DispatchTool(pb.DispatchToolRequest(
        context=_pb_context(), tool_name="lookup_vendor_canon", arguments_json="not json",
    )))

    assert response.error_code == "INVALID_ARGUMENTS"
