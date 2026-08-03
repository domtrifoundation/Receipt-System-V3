"""Turns a Tool Call API manifest (`tuple[ToolSpec, ...]`) into a constrained-decoding
grammar shape (deep-dive §5.1 step 1) — "which one of these N tool schemas, or none."

Pure Python, no `onnxruntime_genai` import at all: this is plain JSON Schema construction,
safe to run in Inference API's own parent service process (the schema crosses to a
`PresetWorker`'s child process as plain picklable data — a `dict` — the same way
`core/preprocessing/generation.py`'s own worker jobs carry only plain data across that
process boundary).
"""

from __future__ import annotations

from .contracts import ToolSpec

__all__ = ["build_tool_call_schema", "parse_tool_call"]


def build_tool_call_schema(tools: tuple[ToolSpec, ...]) -> dict:
    """A JSON Schema whose valid instances are exactly `{"tool": "<name>", "arguments":
    {...}}` for one of the given tools — a discriminated union keyed on `tool`, each
    branch's `arguments` shape taken directly from that `ToolSpec`'s own
    `parameters_schema` (owned by Tool Call API; this module only consumes it, deep-dive
    §3's own stated boundary)."""
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": [t.name for t in tools]},
            "arguments": {},
        },
        "required": ["tool", "arguments"],
        "allOf": [
            {
                "if": {"properties": {"tool": {"const": tool.name}}},
                "then": {"properties": {"arguments": dict(tool.parameters_schema)}},
            }
            for tool in tools
        ],
    }


def parse_tool_call(raw_json_text: str) -> tuple[str, dict] | None:
    """Parses a backend's raw constrained-decoding output (guaranteed schema-valid JSON
    under normal completion, deep-dive §5.1 point 4) back into `(tool_name, arguments)`.
    Returns `None` on anything that doesn't parse as the expected shape — `generation.py`'s
    own worker loop is what decides whether that means `schema_valid=False` or a retry."""
    import json

    try:
        parsed = json.loads(raw_json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    tool_name = parsed.get("tool")
    arguments = parsed.get("arguments")
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        return None
    return (tool_name, arguments)
