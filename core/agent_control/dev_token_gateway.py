"""Implements `services/setup/contracts.py`'s `AgentTokenSeedGateway` Protocol against the
real `TokenLifecycle` — the concrete answer to "how does an AI running `setup-dev`
unattended get MCP access with no human present to hand it a token."

Lives here, not in `services/setup/`, for the same reason every other wizard collaborator
is a `Protocol` Setup only calls through: Setup must stay importable and testable without
Agent Control installed (`docs/PRINCIPLES.md` §1.3). This module is the swappable
implementation, wired in by whichever caller actually runs `setup-dev` with Agent Control
available — not imported by `dev_fixtures.py` itself.
"""

from __future__ import annotations

from .store import AgentStore
from .token_lifecycle import TokenLifecycle

#: `DEV_OBSERVABILITY` plus the two read/staged categories already in `MCP_EXPOSED_TOOLS`
#: — an unattended dev-mode AI gets the same tool surface any `staff`-role agent would,
#: never elevated further. `TEST_EXECUTION` is deliberately excluded: that category kills
#: processes and wipes test tenants, real consequences an auto-issued token should not
#: carry without a human's own explicit, per-action confirmation.
DEV_TOKEN_SCOPES: tuple[str, ...] = ("read_only", "mutating_staged", "dev_observability")

#: Matches `token_lifecycle.py`'s own `issue_token`'s `role` ceiling — `staff`, never
#: `owner`. An unattended dev install still gets a real, bounded agent identity, not a
#: god-mode credential.
DEV_TOKEN_ROLE = "staff"


class AgentControlDevTokenGateway:
    """Implements `services.setup.contracts.AgentTokenSeedGateway` (structurally — see that
    Protocol's own docstring for why this is authorized despite being auto-issued)."""

    def __init__(self, store: AgentStore | None = None) -> None:
        self._lifecycle = TokenLifecycle(store or AgentStore())

    async def issue_dev_token(self, label: str) -> str:
        issued = self._lifecycle.issue_token(
            issued_by="setup-dev-bootstrap",
            issued_to_label=label,
            scopes=DEV_TOKEN_SCOPES,
            role=DEV_TOKEN_ROLE,
        )
        return issued.plaintext


__all__ = ["AgentControlDevTokenGateway", "DEV_TOKEN_ROLE", "DEV_TOKEN_SCOPES"]
