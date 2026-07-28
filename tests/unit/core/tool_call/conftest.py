"""Shared fixtures for Tool Call's unit tests.

The permission resolver is injected everywhere, and every test that expects a call to succeed
has to say which role it is resolving to. That is not ceremony: the default resolver denies
everything (`registry.deny_all_permissions`), so a test that forgot to wire one in fails
closed exactly as production would — which means the fail-closed guarantee is exercised by the
test suite's own default rather than only by the tests that name it.

Handlers here are real callables that get run through `dispatch`'s executor, not mocks. The
guarantees under test are about what happens when a handler raises, hangs, or returns the
wrong shape, and a mock that returns whatever the test told it to would not exercise any of it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role
from core.tool_call.contracts import ToolCategory, ToolContext, ToolSpec
from core.tool_call.registry import ToolRegistry

EMPTY_SCHEMA = FrozenDict({"type": "object", "properties": FrozenDict({})})


def spec(name: str, category: ToolCategory = ToolCategory.READ_ONLY) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"test tool {name}",
        parameters_schema=EMPTY_SCHEMA,
        category=category,
    )


def echo_handler(arguments: FrozenDict, context: ToolContext) -> Mapping[str, object]:
    """Returns what it was given, plus proof of which context ran it."""
    return {"echoed": dict(arguments), "run_id": context.run_id}


def exploding_handler(arguments: FrozenDict, context: ToolContext) -> Mapping[str, object]:
    raise RuntimeError("the underlying API was unreachable")


def hanging_handler(arguments: FrozenDict, context: ToolContext) -> Mapping[str, object]:
    time.sleep(5)
    return {}


def wrong_shape_handler(arguments: FrozenDict, context: ToolContext):
    """A handler that returns something that is not a mapping at all.

    Real, not contrived: a wrapper around another API that returns that API's own result
    object instead of unpacking it is the ordinary way this happens.
    """
    return "not a mapping"


def resolver_for(role: Role | None):
    """A permission resolver that always resolves to `role`.

    Stands in for Auth's real `ValidateSession` call. `None` models both "no session" and
    "Auth said this session is invalid", which the gate must treat identically.
    """

    def _resolve(context: ToolContext) -> Role | None:
        return role

    return _resolve


def exploding_resolver(context: ToolContext) -> Role | None:
    """Auth unreachable. Must be a denial, never an allow."""
    raise ConnectionError("auth service unreachable")


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(spec("lookup_vendor_canon"), echo_handler)
    registry.register(spec("remember_vendor", ToolCategory.MUTATING_STAGED), echo_handler)
    registry.register(spec("get_run_status", ToolCategory.DEV_OBSERVABILITY), echo_handler)
    registry.register(spec("reset_test_environment", ToolCategory.TEST_EXECUTION), echo_handler)
    return registry


@pytest.fixture
def reconciliation_context() -> ToolContext:
    """The automated processing loop — the deep-dive's own named calling context (§5)."""
    return ToolContext(
        run_id="run-1",
        user_id="user-1",
        calling_api="inference_reconciliation",
        session_id="sess-1",
    )


@pytest.fixture
def agent_context() -> ToolContext:
    """Agent Control's MCP server and headless CLI — the dev/debug surface (§4)."""
    return ToolContext(
        run_id="run-1", user_id="staff-1", calling_api="agent_control", session_id="sess-2"
    )
