"""Agent rate limiting (`v3-deepdive-55-agent-control-api.md` §7).

Two independent bounds, deliberately — a general per-minute action cap, and a separate,
tighter per-hour cap on mutating actions specifically. The deep-dive's own testing hook
(§10) calls out that the mutating cap must trigger independently, not merely as the looser
of the two, which is why they are checked separately rather than folded into one counter.

Distinct from Gateway's own rate limiting, which is calibrated for human-driven browser
traffic. An agent in an automation loop produces a request pattern a person clicking
through a UI never would.
"""

from __future__ import annotations

from datetime import timedelta

from .contracts import AgentRateLimit, ToolCategory, utcnow
from .errors import RateLimited
from .store import AgentStore

#: Categories that count against the tighter mutating cap. `TEST_EXECUTION` is included
#: alongside `MUTATING_STAGED` because those tools kill processes and wipe test tenants —
#: real side effects, which is exactly why Tool Call API gave it its own category rather
#: than folding it into `DEV_OBSERVABILITY` (`v3-deepdive-07-tool-call-api.md` §4).
MUTATING_CATEGORIES: tuple[ToolCategory, ...] = (
    ToolCategory.MUTATING_STAGED,
    ToolCategory.TEST_EXECUTION,
)


class RateLimiter:
    def __init__(self, store: AgentStore, limits: AgentRateLimit | None = None) -> None:
        self._store = store
        self._limits = limits or AgentRateLimit()

    @property
    def limits(self) -> AgentRateLimit:
        return self._limits

    def check(self, token_id: str, category: ToolCategory) -> None:
        """Raises `RateLimited` if either bound is already met.

        Counts come from the append-only audit trail rather than a separate in-memory
        counter, so the limiter and the audit log can never disagree about what happened —
        and a restarted service does not silently reset an agent's budget.
        """
        now = utcnow()

        recent = self._store.count_actions_since(token_id, now - timedelta(minutes=1))
        if recent >= self._limits.max_actions_per_minute:
            raise RateLimited("actions", self._limits.max_actions_per_minute, "minute")

        if category in MUTATING_CATEGORIES:
            mutating = self._store.count_actions_since(
                token_id, now - timedelta(hours=1), MUTATING_CATEGORIES
            )
            if mutating >= self._limits.max_mutating_actions_per_hour:
                raise RateLimited(
                    "mutating actions", self._limits.max_mutating_actions_per_hour, "hour"
                )
