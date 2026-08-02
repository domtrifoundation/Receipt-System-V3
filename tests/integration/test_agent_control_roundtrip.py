"""The Phase 1 completion criterion for Agent Control (`docs/PHASE_1_KICKOFF.md` §1.5).

Issue a real token, call `find_setting` through a real MCP client and get a real result,
revoke the token, confirm the next call actually fails. Nothing here is mocked: a real gRPC
server on a real socket, driven through real newline-delimited JSON-RPC on stdio.

Also covers the three testing hooks `v3-deepdive-55-agent-control-api.md` §10 specifies —
the owner-role ceiling, independent rate-limit enforcement, and revocation taking effect
immediately rather than on a delay.
"""

from __future__ import annotations

import io
import json

import pytest

# grpc is a hard, real dependency for this specific test module — not a genuinely optional
# one — but `nox -s forward_compat` (noxfile.py) deliberately runs marker-selected tests in
# a minimal venv that doesn't install it (grpcio-tools has no prebuilt wheel yet for 3.15;
# see the noxfile's own docstring). A bare `import grpc` here would crash pytest's
# *collection* pass before marker filtering ever runs, since pytest must import every module
# under `testpaths` to discover what's in it. `importorskip` fails collection of this module
# alone, cleanly, when grpc is absent — every other test file collects and runs normally,
# and on a real dev environment (grpc installed) nothing here changes at all.
grpc = pytest.importorskip("grpc")

from common.frozen_dict import FrozenDict
from core.agent_control.contracts import AgentAction, AgentRateLimit, ToolCategory, utcnow
from core.agent_control.errors import RateLimited
from core.agent_control.generated import agent_control_pb2 as pb
from core.agent_control.generated import agent_control_pb2_grpc as pb_grpc
from core.agent_control.mcp.server import McpServer
from core.agent_control.rate_limit import RateLimiter
from core.agent_control.service import serve
from core.agent_control.store import AgentStore
from core.agent_control.token_lifecycle import TokenLifecycle


@pytest.fixture
def cluster(tmp_path):
    store = AgentStore(tmp_path / "agent_control.sqlite")
    server = serve("127.0.0.1:0", store=store)
    stub = pb_grpc.AgentControlServiceStub(grpc.insecure_channel(server.bound_address))
    try:
        yield stub, server.bound_address, store
    finally:
        server.stop(0).wait()
        store.close()


def mcp_call(mcp: McpServer, method: str, params: dict, rid: int = 1) -> dict:
    out = io.StringIO()
    payload = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    mcp.run(stdin=io.StringIO(payload + "\n"), stdout=out)
    return json.loads(out.getvalue().strip())


def issue(stub, role="staff", scopes=("read_only", "dev_observability")):
    return stub.IssueAgentToken(pb.IssueTokenRequest(
        issued_by="owner:test", issued_to_label="test agent",
        role=role, scopes=list(scopes),
    ))


def test_full_round_trip(cluster):
    stub, addr, _store = cluster

    issued = issue(stub)
    assert issued.plaintext_token and not issued.error_code
    mcp = McpServer(issued.plaintext_token, addr)

    assert mcp_call(mcp, "initialize", {})["result"]["protocolVersion"]

    names = [t["name"] for t in mcp_call(mcp, "tools/list", {})["result"]["tools"]]
    assert "find_setting" in names
    # Retired in the deep-dive's own correction — nothing actually backs them.
    assert "search_receipts" not in names
    assert "trigger_rescan" not in names

    called = mcp_call(mcp, "tools/call", {
        "name": "find_setting",
        "arguments": {"query": "stop sending diagnostics to the developers"},
    })
    assert called["result"]["isError"] is False
    top = json.loads(called["result"]["content"][0]["text"])["matches"][0]
    assert top["path"] == "settings.diagnostics.telemetrees_opt_in"
    assert top["target"] == "telemetrees.set_opt_in"

    revoked = stub.RevokeAgentToken(pb.RevokeTokenRequest(token_id=issued.token.token_id))
    assert revoked.revoked is True

    after = mcp_call(mcp, "tools/call", {"name": "find_setting", "arguments": {"query": "x"}})
    assert after["result"]["isError"] is True
    assert json.loads(after["result"]["content"][0]["text"])["error_code"] == "TokenRevoked"
    mcp.close()


def test_owner_role_ceiling_has_no_code_path(cluster):
    """§10: no path exists for an agent token to act with owner-level permissions,
    regardless of the issuing user's own role."""
    stub, _, _ = cluster
    for role in ("owner", "OWNER", "root", "admin"):
        assert issue(stub, role=role).error_code == "OWNER_ROLE_FORBIDDEN"


def test_revocation_takes_effect_immediately(cluster):
    """§10: a revoked token's next action fails cleanly, not on some delay."""
    stub, _, _ = cluster
    issued = issue(stub)
    req = pb.AgentActionRequest(
        token=issued.plaintext_token, tool_name="find_setting",
        arguments_json='{"query": "diagnostics"}',
    )
    assert stub.ExecuteAgentAction(req).ok is True
    stub.RevokeAgentToken(pb.RevokeTokenRequest(token_id=issued.token.token_id))
    reply = stub.ExecuteAgentAction(req)
    assert reply.ok is False
    assert reply.error_code == "TokenRevoked"


def test_mutating_cap_triggers_independently_of_the_general_cap(tmp_path):
    """§10: the tighter mutating cap fires on its own, not merely as the looser of two."""
    store = AgentStore(tmp_path / "rl.sqlite")
    token = TokenLifecycle(store).issue_token(
        issued_by="owner:test", issued_to_label="rl", scopes=("*",)
    ).token
    # General cap set high enough that it cannot be the thing that fires.
    limiter = RateLimiter(store, AgentRateLimit(
        max_actions_per_minute=10_000, max_mutating_actions_per_hour=2
    ))

    for _ in range(2):
        store.append_audit(AgentAction(
            token_id=token.token_id, tool_name="propose_setting_change",
            category=ToolCategory.MUTATING_STAGED, arguments=FrozenDict({}),
            at=utcnow(), outcome="ok",
        ))

    limiter.check(token.token_id, ToolCategory.READ_ONLY)  # unaffected
    with pytest.raises(RateLimited) as excinfo:
        limiter.check(token.token_id, ToolCategory.MUTATING_STAGED)
    assert "mutating" in str(excinfo.value)
    store.close()


def test_every_attempt_is_audited_including_refusals(cluster):
    """§6: every action through either surface is audit-logged, no exceptions."""
    stub, _, store = cluster
    issued = issue(stub, scopes=("read_only",))

    stub.ExecuteAgentAction(pb.AgentActionRequest(
        token=issued.plaintext_token, tool_name="find_setting",
        arguments_json='{"query": "codec"}'))
    stub.ExecuteAgentAction(pb.AgentActionRequest(
        token=issued.plaintext_token, tool_name="propose_setting_change",
        arguments_json='{"key": "a", "value": "b"}'))

    outcomes = [a.outcome for a in store.read_audit(token_id=issued.token.token_id)]
    assert "ok" in outcomes
    assert "scope_denied" in outcomes
    # Append-only structurally (docs/PRINCIPLES.md §2.3), not by convention.
    assert not hasattr(store, "update_audit")
    assert not hasattr(store, "delete_audit")


def test_unavailable_core_is_reported_not_fabricated(cluster):
    """A tool whose owning service does not exist yet must say so, never invent data."""
    stub, _, _ = cluster
    issued = issue(stub)
    reply = stub.ExecuteAgentAction(pb.AgentActionRequest(
        token=issued.plaintext_token, tool_name="get_system_health", arguments_json="{}"))
    assert reply.ok is False
    assert "core unavailable" in reply.error_detail
