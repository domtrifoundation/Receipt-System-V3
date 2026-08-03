"""`tool_calling.py` — pure Python schema construction and parsing, no `og` involved."""

from __future__ import annotations

from common.frozen_dict import FrozenDict
from core.inference.contracts import ToolSpec
from core.inference.tool_calling import build_tool_call_schema, parse_tool_call


def test_build_tool_call_schema_is_a_discriminated_union_over_tool_names():
    tools = (
        ToolSpec(name="lookup_vendor", description="", parameters_schema=FrozenDict({"type": "object"})),
        ToolSpec(name="record_total", description="", parameters_schema=FrozenDict({"type": "object"})),
    )
    schema = build_tool_call_schema(tools)
    assert schema["properties"]["tool"]["enum"] == ["lookup_vendor", "record_total"]
    assert len(schema["allOf"]) == 2


def test_parse_tool_call_extracts_name_and_arguments():
    result = parse_tool_call('{"tool": "lookup_vendor", "arguments": {"name": "Dunkin"}}')
    assert result == ("lookup_vendor", {"name": "Dunkin"})


def test_parse_tool_call_returns_none_for_malformed_json():
    assert parse_tool_call("not json") is None


def test_parse_tool_call_returns_none_for_wrong_shape():
    assert parse_tool_call('{"unrelated": true}') is None
    assert parse_tool_call('{"tool": "x", "arguments": "not a dict"}') is None
