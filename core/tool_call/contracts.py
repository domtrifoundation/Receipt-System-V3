"""Tool Call API data contracts (`v3-deepdive-07-tool-call-api.md` §4, §5).

Types only, no logic beyond pure accessors (`docs/PRINCIPLES.md` §1.1) — this is the single
module other packages import from. Nothing outside `core/tool_call/` should ever need to
import `registry`, `dispatch`, or `tools/*`.

Every type here is `@dataclass(frozen=True)` and every dict-typed field is a `FrozenDict`
(§2.1): a frozen dataclass holding a plain `dict` is only shallowly immutable, and both
`ToolSpec.parameters_schema` and `ToolResult.result` cross the Inference API boundary and are
plausibly cached there. `CATEGORY_ALLOWED_ROLES` and `CALLING_API_ALLOWED_CATEGORIES` are
module-level lookup tables and are therefore `FrozenDict` too (§2.1.1).

**`isinstance` against any dict-typed field here must test `collections.abc.Mapping`, never
`dict`.** The Python 3.15 builtin `frozendict` is not a `dict` subclass, so `isinstance(x,
dict)` silently returns False and the wrong branch is taken.

**Why `ToolCategory` is a closed, locally-declared enum and not an Architect-registered
taxonomy** (`docs/PRINCIPLES.md` §3.4): §3.4 reaches *typed, learned, or schema* data — the
category taxonomy Matching classifies receipts into, the flag types Review/Flagging raises,
the reference-identifier types a receipt may carry. `ToolCategory` is none of those. It is a
small, closed, structural safety classification this API's own dispatch logic is written
against (`registry.py`'s permission gate has an `if` for each of exactly four values), the
same shape as Audit API's own `ActionType` — and Audit's own `CLAUDE.md` states the identical
conclusion in the identical words: "this API's own closed vocabulary of things that happened,
not an extensible typed thing." Nobody registers a fifth `ToolCategory` at runtime the way a
vendor registers a new taxonomy category; adding one is a breaking change to this API's own
permission model, reviewed and shipped here, exactly like adding a member to `ActionType` is
reviewed and shipped in Audit. What *is* Architect's domain, and is deliberately never
reinvented here, is the vendor category taxonomy `vendor_tools.py` reads — this package
consumes `architect.contracts.DefinitionKind.TAXONOMY_CATEGORY` definitions as a caller, never
declares a parallel one of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from common.frozen_dict import FrozenDict
from core.auth.contracts import Role


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolCategory(str, Enum):
    """The complete, closed set of tool safety categories (deep-dive §4).

    `READ_ONLY` and `MUTATING_STAGED` are self-applying in every calling context that offers
    them at all — safety comes from *which* tools are offered, never from a confirmation step
    that has no live user on the other end of it during automated processing (§4). `MUTATING_
    STAGED` writes only ever land in an existing downstream review/audit gate (Architect's
    moderation queue, Persistence's Historian-backed write path); a genuinely direct, ungated
    mutation is never a category this API exposes to any calling context (§4, `MUTATING_
    DIRECT` deliberately does not exist as a member).

    `DEV_OBSERVABILITY` and `TEST_EXECUTION` are kept distinct on purpose, not folded into one
    "for dev use" bucket: the former can never cause harm because it only reads; the latter
    kills processes and wipes test tenants (§4).
    """

    READ_ONLY = "read_only"
    MUTATING_STAGED = "mutating_staged"
    DEV_OBSERVABILITY = "dev_observability"
    TEST_EXECUTION = "test_execution"


#: Which roles a resolved caller must hold for a category to even be considered (§4.2's fail-
#: closed permission gate operates on top of this). `CLIENT` gets `READ_ONLY` and `MUTATING_
#: STAGED` because those are exactly the categories the automated reconciliation loop uses
#: while processing *that client's own* receipt — the ordinary, expected caller shape for
#: this API, not a privilege escalation. `DEV_OBSERVABILITY` and `TEST_EXECUTION` exist to
#: serve Agent Control's own MCP server and headless CLI (deep-dive §4), a staff/owner
#: debugging surface a client-role caller has no legitimate reason to reach through this API.
#: `FrozenDict` per §2.1.1 — a lookup table nothing should ever write, read concurrently.
CATEGORY_ALLOWED_ROLES: FrozenDict = FrozenDict(
    {
        ToolCategory.READ_ONLY: frozenset({Role.CLIENT, Role.STAFF, Role.OWNER}),
        ToolCategory.MUTATING_STAGED: frozenset({Role.CLIENT, Role.STAFF, Role.OWNER}),
        ToolCategory.DEV_OBSERVABILITY: frozenset({Role.STAFF, Role.OWNER}),
        ToolCategory.TEST_EXECUTION: frozenset({Role.STAFF, Role.OWNER}),
    }
)

#: Which categories a given calling context is even allowed to draw tools from (deep-dive
#: §3.4's "don't offer an always-failing tool" pattern's sibling: don't offer a tool this
#: context has no business calling at all). An unrecognised `calling_api` maps to the empty
#: set via `.get(..., frozenset())` at every call site — an unknown calling context is denied
#: every category, never granted the union of all of them (`docs/PRINCIPLES.md` §4.2).
#:
#: `"inference_reconciliation"` is the deep-dive's own named example (§5): the agentic tool-
#: calling loop processing one receipt, offered exactly the categories §3-4 describe for it.
#: `"agent_control"` is Agent Control API's own MCP server and headless CLI (its own `CLAUDE.
#: md`), the intended consumer of `DEV_OBSERVABILITY`/`TEST_EXECUTION`.
CALLING_API_ALLOWED_CATEGORIES: FrozenDict = FrozenDict(
    {
        "inference_reconciliation": frozenset(
            {ToolCategory.READ_ONLY, ToolCategory.MUTATING_STAGED}
        ),
        "agent_control": frozenset(
            {
                ToolCategory.READ_ONLY,
                ToolCategory.MUTATING_STAGED,
                ToolCategory.DEV_OBSERVABILITY,
                ToolCategory.TEST_EXECUTION,
            }
        ),
    }
)


@dataclass(frozen=True)
class ToolSpec:
    """One tool's static shape — what Inference API's tool-calling orchestrator builds its
    constrained-decoding grammar from (deep-dive §5, and `v3-deepdive-02-inference-api.md`
    §5). Carries no handler and no availability check: those are logic, and `contracts.py`
    holds types and no logic (`docs/PRINCIPLES.md` §1.1) — `registry.py`'s `RegisteredTool`
    is where a `ToolSpec` is paired with the callable that actually runs it.
    """

    name: str
    description: str
    parameters_schema: FrozenDict
    category: ToolCategory


@dataclass(frozen=True)
class ToolContext:
    """Who is calling, and through what surface (deep-dive §5).

    `session_id` is an addition beyond the deep-dive's own sketch (`run_id`, `user_id`,
    `calling_api`), documented here and in this package's `CLAUDE.md`: permission resolution
    must happen server-side from the caller's session via Auth & Tenancy, never from a
    caller-asserted role (this task's own non-negotiable rule, consistent with `docs/
    PRINCIPLES.md` §4.2) — and a session is the one thing Auth can actually resolve a `Role`
    from (`core/auth/contracts.py`'s `Session.role`). Deliberately absent: any `role` field on
    this type itself. A caller-supplied role would be exactly the caller-asserted role this
    contract exists to make impossible to smuggle in.
    """

    run_id: str
    user_id: str
    calling_api: str
    session_id: str = ""


@dataclass(frozen=True)
class ToolResult:
    """One tool invocation's outcome. Errors are data here, never raised (§4.1) — this
    matches V2's own `dispatch()` convention (`{"error": ...}`), which the deep-dive names as
    still correct (§5).

    Two error fields, not one, extending the deep-dive's own literal sketch (`error: str |
    None`) the same way Logs' and Audit's own result contracts pair a stable wire code with a
    human-readable detail: `error_code` is what a caller branches on (`errors.ERROR_CODES`),
    `error` is what a human reads. `ok` is a caller-friendly derived property rather than an
    additional field a constructor could set inconsistently with `error_code`.
    """

    tool_name: str
    result: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error: str | None = None
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code


@dataclass(frozen=True)
class ToolAuditRecord:
    """One attempted privileged tool invocation, recorded whether it succeeded or not.

    **Not `core.audit.contracts.AuditEvent`, and that is a deliberate, flagged gap rather
    than an oversight.** `AuditEvent.action_type` is `core.audit.contracts.ActionType`, a
    closed enum with no member representing "an agent invoked a mutating tool" — and this
    package may not edit `core/audit/` to add one (out of this task's own write boundary).
    This contract is the seam a future integration converts into a real `AuditEvent` once
    Audit gains a suitable `ActionType` member (or an existing one is deliberately reused with
    a documented rationale) — a decision for that PR's own review, not one this package makes
    unilaterally by guessing at a mapping. See this package's `CLAUDE.md` for the full note.

    `arguments` is a `FrozenDict` for the same reason `ToolResult.result` is: this value is
    retained by `dispatch.AuditRecorder` implementations and must not be mutable in place
    after the fact — the exact failure mode an audit trail cannot afford (`docs/PRINCIPLES.md`
    §2.1, and Audit's own `AuditEvent.details` docstring makes the identical point).
    """

    run_id: str
    user_id: str
    calling_api: str
    tool_name: str
    category: ToolCategory
    arguments: FrozenDict
    outcome: str
    at: datetime = field(default_factory=utcnow)
    detail: str = ""


@dataclass(frozen=True)
class ToolCallMetrics:
    """An immutable snapshot of the counters `metrics.py`'s collector keeps."""

    invocations_total: int = 0
    invocations_ok: int = 0
    denied_unregistered: int = 0
    denied_context: int = 0
    denied_permission: int = 0
    denied_unavailable: int = 0
    denied_invalid_arguments: int = 0
    timed_out: int = 0
    handler_raised: int = 0
    audit_records_written: int = 0


__all__ = [
    "CALLING_API_ALLOWED_CATEGORIES",
    "CATEGORY_ALLOWED_ROLES",
    "ToolAuditRecord",
    "ToolCallMetrics",
    "ToolCategory",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "utcnow",
]
