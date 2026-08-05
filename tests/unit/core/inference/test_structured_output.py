"""`structured_output.py` — schema resolution and salvage parsing (deep-dive §5)."""

from __future__ import annotations

from common.frozen_dict import FrozenDict
from core.inference.contracts import GenerationRequest, ToolSpec
from core.inference.structured_output import resolve_schema, salvage_partial_json

from .conftest import text_message
from core.inference.contracts import MessageRole


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        run_id="r1", user_id="u1", preset="phi4-mini",
        messages=(text_message(MessageRole.USER, "hi"),),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


def test_resolve_schema_is_none_when_neither_tools_nor_response_schema():
    assert resolve_schema(_request()) is None


def test_resolve_schema_prefers_tools_over_response_schema():
    tools = (ToolSpec(name="t", description="", parameters_schema=FrozenDict({})),)
    schema = resolve_schema(_request(tools=tools, response_schema=FrozenDict({"type": "object"})))
    assert "allOf" in schema  # tool-call schema shape, not the plain response_schema


def test_resolve_schema_uses_response_schema_when_no_tools():
    schema = resolve_schema(_request(response_schema=FrozenDict({"type": "object", "properties": {}})))
    assert schema == {"type": "object", "properties": {}}


def test_salvage_partial_json_recovers_an_unterminated_string_and_object():
    assert salvage_partial_json('{"vendor": "Dunkin') == {"vendor": "Dunkin"}


def test_salvage_partial_json_recovers_a_nested_truncated_array():
    result = salvage_partial_json('{"vendor": "Dunkin", "items": [{"name": "donut"')
    assert result == {"vendor": "Dunkin", "items": [{"name": "donut"}]}


def test_salvage_partial_json_returns_none_for_unrecoverable_garbage():
    assert salvage_partial_json("") is None
    assert salvage_partial_json("not json at all") is None
