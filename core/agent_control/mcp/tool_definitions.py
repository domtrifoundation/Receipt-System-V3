"""The curated MCP tool set (`v3-deepdive-55-agent-control-api.md` §4).

Every name here is a real, verified wrapper around an RPC some other API already owns —
none is invented. The deep-dive is explicit about this having been checked rather than
assumed: `search_receipts` and `trigger_rescan` appeared in an earlier draft and stay
retired, because nothing backing them actually exists.

Categories are reused from Tool Call API's own enum rather than redefined
(`v3-deepdive-07-tool-call-api.md` §4). `DEV_OBSERVABILITY` and `TEST_EXECUTION` are kept
distinct on purpose: the former can never cause harm because it only reads, the latter kills
processes and wipes test tenants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..contracts import ToolCategory


@dataclass(frozen=True)
class ToolDef:
    name: str
    category: ToolCategory
    description: str
    parameters: dict[str, Any]
    handler: str
    """Attribute name on the `CoreBackend` this tool delegates to."""


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_STR = {"type": "string"}
_INT = {"type": "integer"}

MCP_EXPOSED_TOOLS: tuple[ToolDef, ...] = (
    # --- READ_ONLY — reused directly from Tool Call's existing inventory ----
    ToolDef(
        name="find_setting",
        category=ToolCategory.READ_ONLY,
        description=(
            "Resolve a natural-language description of a setting to its real dotted config "
            "key, without needing the exact key memorized. Checks former paths too, so a "
            "stale reference to a relocated setting still resolves."
        ),
        parameters=_schema(
            {"query": _STR, "limit": _INT}, ["query"],
        ),
        handler="find_setting",
    ),
    ToolDef(
        name="persistence_query",
        category=ToolCategory.READ_ONLY,
        description="Structured/full-text search over receipt records via Search/Query API.",
        parameters=_schema({"vendor": _STR, "after": _STR, "before": _STR, "limit": _INT}),
        handler="persistence_query",
    ),
    # --- MUTATING_STAGED ---------------------------------------------------
    ToolDef(
        name="propose_setting_change",
        category=ToolCategory.MUTATING_STAGED,
        description=(
            "Stage a proposed settings change into a review queue for asynchronous staff "
            "approval. Never applies the change directly."
        ),
        parameters=_schema({"key": _STR, "value": _STR}, ["key", "value"]),
        handler="propose_setting_change",
    ),
    # --- DEV_OBSERVABILITY — new in this API (§4.1) ------------------------
    ToolDef(
        name="get_run_status",
        category=ToolCategory.DEV_OBSERVABILITY,
        description="Live status of one pipeline run, via Execution Core's GetRunStatus.",
        parameters=_schema({"run_id": _STR}, ["run_id"]),
        handler="get_run_status",
    ),
    ToolDef(
        name="get_system_health",
        category=ToolCategory.DEV_OBSERVABILITY,
        description="Health API's live diagnostic layer plus capability-drift findings.",
        parameters=_schema({}),
        handler="get_system_health",
    ),
    ToolDef(
        name="get_historian_narrative",
        category=ToolCategory.DEV_OBSERVABILITY,
        description=(
            "What actually happened to one receipt, stage by stage, from Historian's "
            "narrative track — without manually cross-referencing raw logs across services."
        ),
        parameters=_schema({"receipt_id": _STR}, ["receipt_id"]),
        handler="get_historian_narrative",
    ),
    ToolDef(
        name="tail_logs",
        category=ToolCategory.DEV_OBSERVABILITY,
        description="Recent operational log entries for one service, via Logs API.",
        parameters=_schema({"service": _STR, "level": _STR, "limit": _INT}, ["service"]),
        handler="tail_logs",
    ),
    ToolDef(
        name="check_dependency_status",
        category=ToolCategory.DEV_OBSERVABILITY,
        description=(
            "Whether this environment's dependency versions match what is expected — worth "
            "checking before chasing a bug that is actually an out-of-date local install."
        ),
        parameters=_schema({}),
        handler="check_dependency_status",
    ),
)

TOOLS_BY_NAME: dict[str, ToolDef] = {t.name: t for t in MCP_EXPOSED_TOOLS}


def enabled_tools(scopes: tuple[str, ...]) -> tuple[ToolDef, ...]:
    """Filter by the token's own scopes.

    V2's `tools_for(cfg)` excluded a tool whose underlying capability was not configured, on
    the reasoning that offering a tool that can only fail wastes the model's turns — kept as
    a technique (`v3-deepdive-07-tool-call-api.md` §3.4). Live-availability filtering is the
    second half of that and belongs with the backend, not here.
    """
    if "*" in scopes:
        return MCP_EXPOSED_TOOLS
    return tuple(t for t in MCP_EXPOSED_TOOLS if t.category.value in scopes)
