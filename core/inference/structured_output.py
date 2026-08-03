"""JSON-schema/regex constrained decoding — the pure-Python half (deep-dive §5).

`resolve_schema()` picks the one effective grammar for a request — `response_schema` and
`tools` are mutually exclusive in practice (deep-dive §3), and this is the one place that
choice is made, rather than every caller re-deriving it. `salvage_partial_json()` is the
deep-dive's own named last-resort utility (§5.2): a genuinely reduced-scope version of
V2's `_salvage_*_json` idea, kept as legitimate defense-in-depth even though constrained
decoding is now the primary strategy, not a fallback to lean on routinely.

No `onnxruntime_genai` import here at all — schema resolution and salvage parsing are
plain JSON/dict manipulation, safe to run in Inference API's own parent process before a
request ever crosses to a `PresetWorker`'s child process.
"""

from __future__ import annotations

import json

from .contracts import GenerationRequest
from .tool_calling import build_tool_call_schema

__all__ = ["resolve_schema", "salvage_partial_json"]


def resolve_schema(request: GenerationRequest) -> dict | None:
    """`None` means no constrained decoding at all — a plain free-text generation."""
    if request.tools:
        return build_tool_call_schema(request.tools)
    if request.response_schema is not None:
        return dict(request.response_schema)
    return None


def salvage_partial_json(text: str) -> dict | None:
    """Best-effort recovery of a truncated JSON object — closes unterminated strings and
    unbalanced brackets in the obvious way, then attempts a parse. Returns `None` if even
    that doesn't produce valid JSON; a caller falling back to this already knows the
    generation was truncated (`FinishReason.LENGTH`) and treats `None` the same as a fully
    failed generation, not a worse outcome than what it already had.
    """
    candidate = text.strip()
    if not candidate:
        return None

    # Close an unterminated string literal first — an odd number of unescaped quotes.
    if candidate.count('"') % 2 == 1:
        candidate += '"'

    opens = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in candidate:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in opens:
            stack.append(opens[ch])
        elif ch in opens.values() and stack and stack[-1] == ch:
            stack.pop()

    # A dangling key or trailing comma before the close is the other common truncation
    # shape — strip a trailing comma/colon before appending closers.
    candidate = candidate.rstrip().rstrip(",:")
    candidate += "".join(reversed(stack))

    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None
