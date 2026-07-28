"""Tool Call's frozen contracts (§5, `docs/PRINCIPLES.md` §2.1, §2.1.1).

§5 of this API's own deep-dive is where the project-wide `FrozenDict` policy was first stated,
and it names the exact bug: `tool_result.result["x"] = "y"` silently succeeding on a
`@dataclass(frozen=True)` with a plain `dict` field. `ToolSpec` and `ToolResult` cross the
Inference API boundary and may be cached, so this is the package the policy was written for.

The `forward_compat`-marked tests are the ones that need to run under every interpreter in the
support matrix: on 3.15 the builtin `frozendict` is not a `dict` subclass, so `isinstance(x,
dict)` silently returns False. In this package that would land on `dispatch`'s own argument
and return-payload checks — which is why they test `collections.abc.Mapping`.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from common.frozen_dict import FrozenDict
from core.tool_call.contracts import (
    CALLING_API_ALLOWED_CATEGORIES,
    CATEGORY_ALLOWED_ROLES,
    ToolCategory,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from core.tool_call.errors import ERROR_CODES, ERROR_SUMMARIES


@pytest.mark.forward_compat
def test_contract_dict_fields_are_mappings_not_dict_subclasses():
    """The check every consumer must make is `Mapping`, never `dict`.

    `dispatch` validates both the arguments it receives and the payload a handler returns with
    `isinstance(..., Mapping)`. Had either been written against `dict`, a `FrozenDict` on 3.15
    would take the wrong branch — arguments would be rejected as invalid and every legitimate
    handler return would be reported as a malformed payload.
    """
    tool_spec = ToolSpec(
        name="lookup_vendor_canon",
        description="",
        parameters_schema=FrozenDict({"type": "object"}),
        category=ToolCategory.READ_ONLY,
    )
    result = ToolResult(tool_name="lookup_vendor_canon", result=FrozenDict({"vendor": "x"}))

    assert isinstance(tool_spec.parameters_schema, Mapping)
    assert isinstance(result.result, Mapping)


@pytest.mark.forward_compat
def test_a_tool_result_payload_cannot_be_mutated_in_place():
    """§5's named bug, asserted directly."""
    result = ToolResult(tool_name="t", result=FrozenDict({"x": 1}))

    with pytest.raises(Exception):
        result.result["x"] = 2  # type: ignore[index]


@pytest.mark.forward_compat
def test_module_level_lookup_tables_are_frozen():
    """§2.1.1: a constant table nothing should ever write is a `FrozenDict`.

    These two tables *are* the safety model — which roles reach which categories, and which
    calling context may draw from which. A table mutable at runtime would make the gate's
    answer depend on whatever ran before it.
    """
    for table in (CATEGORY_ALLOWED_ROLES, CALLING_API_ALLOWED_CATEGORIES, ERROR_CODES, ERROR_SUMMARIES):
        assert isinstance(table, Mapping)

    with pytest.raises(Exception):
        CATEGORY_ALLOWED_ROLES[ToolCategory.READ_ONLY] = frozenset()  # type: ignore[index]


def test_tool_context_carries_no_role_field():
    """§5: a caller-supplied role is exactly what this contract exists to make impossible.

    Permission resolution happens server-side from the session. A `role` field here would be a
    caller-asserted role, and the gate would be checking the caller's own claim about itself.
    """
    fields = set(ToolContext.__dataclass_fields__)

    assert "role" not in fields
    assert fields == {"run_id", "user_id", "calling_api", "session_id"}


def test_ok_is_derived_from_the_error_code_not_stored_separately():
    """A stored `ok` flag could be set inconsistently with `error_code`; a property cannot."""
    assert ToolResult(tool_name="t").ok
    assert not ToolResult(tool_name="t", error="boom", error_code="TOOL_RAISED").ok


def test_every_error_code_has_an_operator_summary():
    """A client that only has the code still needs something to show a person."""
    for code in ERROR_CODES.values():
        assert ERROR_SUMMARIES.get(code)


def test_tool_spec_is_frozen():
    tool_spec = ToolSpec(
        name="t", description="", parameters_schema=FrozenDict({}), category=ToolCategory.READ_ONLY
    )

    with pytest.raises(Exception):
        tool_spec.category = ToolCategory.TEST_EXECUTION  # type: ignore[misc]
