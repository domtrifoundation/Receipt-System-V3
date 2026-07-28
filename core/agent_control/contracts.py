"""Agent Control data contracts (`v3-deepdive-55-agent-control-api.md` §3, §7).

Every type crossing this API's boundary is `@dataclass(frozen=True)` and every dict-typed
field is a `FrozenDict` (`docs/PRINCIPLES.md` §2.1) — a frozen dataclass holding a plain dict
is only shallowly immutable, and this API hands result payloads across a process boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from common.frozen_dict import FrozenDict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolCategory(str, Enum):
    """Mirrors Tool Call API's own category enum (`v3-deepdive-07-tool-call-api.md` §4).

    Declared here as the value this API *consumes*, not as a second parallel taxonomy — when
    Tool Call API exists, this is replaced by an import from its `contracts.py`. The split
    between the last two is deliberate: `DEV_OBSERVABILITY` tools can never cause harm
    because they only read; `TEST_EXECUTION` tools kill processes and wipe test tenants.
    """

    READ_ONLY = "read_only"
    MUTATING_STAGED = "mutating_staged"
    DEV_OBSERVABILITY = "dev_observability"
    TEST_EXECUTION = "test_execution"


#: The role ceiling. `owner` is deliberately absent and must stay absent (§3.1) — the owner
#: role carries irreversible, instance-defining authority that should never be reachable by
#: something that is not a human making that specific decision in the moment.
AgentRole = Literal["client", "staff"]


@dataclass(frozen=True)
class AgentToken:
    """A scoped, revocable agent identity. Never a shared credential, never self-issued."""

    token_id: str
    issued_by: str
    issued_to_label: str
    scopes: tuple[str, ...]
    role: AgentRole
    issued_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if self.revoked_at is not None and self.revoked_at <= now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True


@dataclass(frozen=True)
class AgentSession:
    """A resolved, authenticated agent identity for one action."""

    token: AgentToken
    started_at: datetime


@dataclass(frozen=True)
class AgentAction:
    """One attempted action, recorded whether it succeeded or not (§6 — no exceptions)."""

    token_id: str
    tool_name: str
    category: ToolCategory
    arguments: FrozenDict
    at: datetime
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class AgentRateLimit:
    """Deliberately tighter than a human session's own bounds (§7).

    An agent in a genuine automation loop generates request volume a human clicking through
    a UI never would. The mutating cap is separate and tighter on purpose — the riskier
    category gets its own bound rather than sharing the general one.
    """

    max_actions_per_minute: int = 30
    max_mutating_actions_per_hour: int = 20


@dataclass(frozen=True)
class ToolResult:
    """Errors are data at this boundary, never raised (`docs/PRINCIPLES.md` §4.1)."""

    ok: bool
    payload: FrozenDict = field(default_factory=lambda: FrozenDict({}))
    error: str = ""

    @staticmethod
    def success(**payload: Any) -> "ToolResult":
        return ToolResult(ok=True, payload=FrozenDict(payload))

    @staticmethod
    def failure(error: str) -> "ToolResult":
        return ToolResult(ok=False, error=error)


@dataclass(frozen=True)
class IssuedToken:
    """Returned once, at issue time. `plaintext` is not recoverable afterwards.

    The store keeps only a SHA-256 hash, so a leaked token database does not leak usable
    tokens — the same reasoning behind not storing recoverable secrets anywhere else.
    """

    token: AgentToken
    plaintext: str
