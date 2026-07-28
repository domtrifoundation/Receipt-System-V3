"""Agent Control error taxonomy.

These are surfaced as `ToolResult.error` strings at the API boundary rather than raised
across it (`docs/PRINCIPLES.md` §4.1). They exist as real types because the *internal*
call path still benefits from distinguishing them — an expired token and a rate-limited
request are different problems with different operator responses.

The one place raising is correct is token authentication itself, matching Auth & Tenancy's
own stated exception (§4.1): a caller silently ignoring an auth failure is worse than one
ignoring a business-logic error.
"""

from __future__ import annotations


class AgentControlError(Exception):
    """Base for everything this API raises internally."""


class TokenAuthError(AgentControlError):
    """Base for authentication failures. Deliberately raised, not returned — see module docstring."""


class UnknownToken(TokenAuthError):
    """No token matches the presented secret."""


class TokenRevoked(TokenAuthError):
    """The token existed and has been revoked. Takes effect immediately, never on a delay."""


class TokenExpired(TokenAuthError):
    """The token existed and has passed its own expiry."""


class OwnerRoleForbidden(AgentControlError):
    """An attempt to issue an agent token carrying `owner`.

    This is a hard structural ceiling (§3.1), not a policy check that a future caller could
    pass a flag to bypass. An owner who wants an owner-level action performed does it
    themselves, informed by the agent's recommendation.
    """


class ScopeDenied(AgentControlError):
    """The token is valid but its scopes do not cover the requested tool."""


class RateLimited(AgentControlError):
    """A configured bound was hit (§7)."""

    def __init__(self, which: str, limit: int, window: str) -> None:
        super().__init__(f"rate limit exceeded: {which} (max {limit} per {window})")
        self.which = which
        self.limit = limit
        self.window = window


class UnknownTool(AgentControlError):
    """The requested tool is not in the exposed set."""


class CoreUnavailable(AgentControlError):
    """The Core API this tool wraps is not reachable.

    Not a bug and not a stub: Agent Control is a genuine third client of the same gRPC core
    the TUI and Gateway talk to, so when that cluster is not running there is genuinely
    nothing to call. Surfaced honestly rather than answered with fabricated data.
    """
