"""`AgentControlDevTokenGateway` — real `TokenLifecycle`/`AgentStore` (in-memory sqlite),
never a fake, since this module's whole point is being the genuine implementation
`services/setup/dev_fixtures.py`'s `AgentTokenSeedGateway` Protocol calls through."""

from __future__ import annotations

import asyncio

from core.agent_control.dev_token_gateway import (
    DEV_TOKEN_ROLE,
    DEV_TOKEN_SCOPES,
    AgentControlDevTokenGateway,
)
from core.agent_control.store import AgentStore


def run(coro):
    return asyncio.run(coro)


def _gateway() -> tuple[AgentControlDevTokenGateway, AgentStore]:
    store = AgentStore(":memory:")
    return AgentControlDevTokenGateway(store), store


def test_issue_dev_token_returns_a_real_plaintext_token():
    gateway, _ = _gateway()

    plaintext = run(gateway.issue_dev_token("setup-dev unattended AI operator"))

    assert plaintext.startswith("rsb_agent_")


def test_issued_token_is_recorded_as_setup_dev_bootstrap_and_staff_role():
    gateway, store = _gateway()
    run(gateway.issue_dev_token("setup-dev unattended AI operator"))

    tokens = store.list_tokens()

    assert len(tokens) == 1
    assert tokens[0].issued_by == "setup-dev-bootstrap"
    assert tokens[0].role == DEV_TOKEN_ROLE
    assert tokens[0].scopes == DEV_TOKEN_SCOPES


def test_dev_token_never_carries_owner_role():
    """§3.1's own hard ceiling, confirmed at this seam specifically — an unattended
    auto-issue path is exactly where a ceiling like this earns its keep."""
    assert "owner" != DEV_TOKEN_ROLE
    assert DEV_TOKEN_ROLE in ("client", "staff")


def test_dev_token_excludes_test_execution_scope():
    assert "test_execution" not in DEV_TOKEN_SCOPES
