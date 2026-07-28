# V3 Deep Dive: Agent Control API

**Companion files:** `v3-deepdive-05-auth-tenancy-api.md` (agent tokens are a real extension of Auth's own identity model, not a parallel security system), `v3-deepdive-07-tool-call-api.md` (this API reuses Tool Call's existing categorized-tool infrastructure and `MUTATING_STAGED` pattern rather than inventing a second one), `v3-deepdive-08-audit-event-log-api.md` (every agent action is a privileged, audit-logged event), `v3-deepdive-14-interface-api.md` and `v3-deepdive-44-webapp.md` (both front ends this API is a genuine third alternative to, not a bypass of).

**Status:** New Core API. Named "Agent Control API" — considered "AIConsole" and "Dev.Console.api" as alternatives; settled on plain, descriptive naming consistent with the rest of this corpus (Gateway, Tool Call, Webapp Assistant) rather than a stylized name.

---

## 1. Scope & boundary

Agent Control owns programmatic access to a running instance for AI agents and automation — Claude Code specifically, but designed generally rather than Claude-Code-specific. It provides two related but distinct surfaces: an MCP server, and a headless/scriptable interface that doesn't require either the TUI or webapp to be rendered. It does not:
- **own a second, parallel permission model.** Every agent action is bound by the exact same role-based enforcement a human session would be — Auth's own roles, Tool Call's own `MUTATING_STAGED`/`READ_ONLY` categorization. An agent is never more capable than the human who authorized it.
- **bypass the TUI or webapp's own capabilities** — it's a genuine third interface onto the same underlying gRPC core both of them already talk to, not a backdoor around either. Anything an agent can do through this API, a human could also do through the TUI or webapp; this API just makes it scriptable.
- **grant itself access** — an agent token is always explicitly issued by a human owner/staff member through the normal settings surface (§3 below), never self-provisioned.

---

## 2. Package layout

```
core/agent_control/
  __init__.py
  contracts.py             # AgentToken, AgentSession, AgentAction, error types
  mcp/
    __init__.py
    server.py                  # the actual MCP server implementation
    tool_definitions.py          # the curated MCP tool set, reusing Tool Call's existing categories
  headless/
    __init__.py
    cli.py                        # scriptable, non-interactive command interface
  token_lifecycle.py               # issue/scope/revoke — see §3
  rate_limit.py                      # real, configurable bounds distinct from a human session's own
  errors.py
```

---

## 3. Agent tokens — a real, scoped, revocable identity, not a shared credential

```python
@dataclass(frozen=True)
class AgentToken:
    token_id: str
    issued_by: str                # the owner/staff user_id who created it — always a real human
    issued_to_label: str            # a human-readable name for what this token is for ("Claude Code — local dev session")
    scopes: tuple[str, ...]           # which categories of action this token can take, e.g. "read_only", "settings_propose"
    role: Literal["client", "staff"]    # the effective role this token acts as — never "owner", see §3.1
    expires_at: datetime | None
    revoked_at: datetime | None
```
**An agent token is always issued deliberately, by a real human, through the normal settings surface** — the same two-entry-point pattern (Setup wizard offer + persistent settings entry) already established for run-on-startup and SMS setup. Never a bare API key an agent can generate for itself.

### 3.1 Why an agent token can never carry the `owner` role
Even an owner-authorized agent session is capped at `staff`-equivalent permissions, never granted `owner` itself — a deliberate ceiling, not an oversight. The owner role carries irreversible, instance-defining authority (billing configuration, tunnel exposure, deleting the whole install) that should never be reachable by something that isn't a human directly making that specific decision in the moment. An owner who genuinely wants an agent to perform an owner-level action does it themselves, informed by the agent's own recommendation — the same "propose, human confirms" pattern already established for `MUTATING_STAGED` tools, applied here as a hard ceiling rather than a per-action gate.

---

## 4. The MCP server — reuses Tool Call's existing tool categories, extends it with a real, verified dev-tools category
```python
# mcp/tool_definitions.py
MCP_EXPOSED_TOOLS = [
    # READ_ONLY — reused directly from Tool Call's existing inventory
    "persistence_query", "find_setting",
    # MUTATING_STAGED — reused directly from Tool Call's existing inventory
    "propose_setting_change",
    # DEV_OBSERVABILITY — new in this API, real wrappers around existing RPCs,
    # not invented — see §4.1
    "get_run_status", "get_system_health", "get_historian_narrative",
    "tail_logs", "check_dependency_status",
]
```
**On the correction from an earlier draft**: `get_run_status` and `get_system_health` are back, and this time verified against real, existing capabilities rather than assumed. `get_run_status` wraps Execution Core's own real `GetRunStatus` RPC (`v3-deepdive-10-execution-core-api.md` §12, already server-streaming live progress — this API doesn't add a new capability, it exposes an existing one via MCP). `get_system_health` wraps Health API's own real live-diagnostic and capability-drift-check data (`v3-deepdive-20-health-api.md` §3-4). `persistence_query`, `find_setting`, and `propose_setting_change` remain the real, existing Tool Call reuses from the corrected draft; `search_receipts` and `trigger_rescan` stay retired, since nothing backing them actually exists.

### 4.1 A new `DEV_OBSERVABILITY` category — real wrappers, verified against each owning API before being listed here
- **`get_run_status(run_id)`** → Execution Core's `GetRunStatus`.
- **`get_system_health()`** → Health API's live diagnostic + capability-drift findings.
- **`get_historian_narrative(receipt_id)`** → Historian's own narrative track (`v3-deepdive-29-historian.md` §5) — genuinely useful mid-development: "what actually happened to this specific test receipt" without manually cross-referencing raw logs across five services.
- **`tail_logs(service, level)`** → Logs API's own query surface (`v3-deepdive-18-logs-api.md`).
- **`check_dependency_status()`** → Telemetrees' own tracked-fact inventory (`v3-deepdive-28-telemetrees-api.md` §3.1) — confirms whether the local dev environment's own dependency versions match what's expected, before chasing a bug that's actually just an out-of-date local install.

This is a genuinely new category, not a reuse — `DEV_OBSERVABILITY` tools are read-only in the same sense `READ_ONLY` already is, but scoped specifically to development/debugging use rather than end-user-relevant data, worth keeping conceptually separate in Tool Call's own inventory (a real, small addition needed there — `v3-deepdive-07-tool-call-api.md` §3's own category list gets this fourth entry) rather than folded into `READ_ONLY` and losing that distinction.

---

## 5. Headless/scriptable access — for automation that isn't MCP-shaped
```bash
# A real, scriptable CLI, distinct from the TUI's own interactive Textual interface
resibo-agent-cli --token $AGENT_TOKEN find-setting "email notifications"
resibo-agent-cli --token $AGENT_TOKEN persistence-query --vendor "Denny's" --after 2026-01-01
resibo-agent-cli --token $AGENT_TOKEN propose-setting-change smtp.enabled=false
```
Useful for CI pipelines, scripted queries, or any automation context where MCP's own conversational tool-calling shape isn't the right fit — same underlying gRPC calls and the same token/scope/audit discipline as the MCP path, just a different transport for a different kind of caller. A genuine run-status/health-check command is a real, plausible future addition to this CLI, but isn't included above since it isn't yet a real tool in Tool Call's own inventory (§4's own correction) — worth designing there first, not implied here as if it already existed.

---

## 6. Audit logging — every agent action, no exceptions
Every action taken through either surface (MCP or headless) is Audit-logged with the specific `token_id` that took it, the same way a break-glass grant or a staff action already is (`v3-deepdive-08-audit-event-log-api.md`) — an agent's own actions need to be just as traceable after the fact as a human's, arguably more so given the different trust calculus involved in granting programmatic access at all.

---

## 7. Rate limiting — a real, distinct bound from a human session's own
```python
@dataclass(frozen=True)
class AgentRateLimit:
    max_actions_per_minute: int      # default: 30 — deliberately conservative
    max_mutating_actions_per_hour: int  # default: 20 — a real, separate, tighter cap on the riskier category specifically
```
An agent operating in a genuine automation loop can generate request volume a human interacting through a UI never would — these limits exist specifically to bound that, distinct from Gateway's own general rate limiting (`v3-deepdive-19-gateway-api.md` §10), which is calibrated for human-driven traffic patterns.

---

## 8. Asyncio, free-threading, and profiling
The MCP server and CLI are both thin, I/O-bound orchestration over the same gRPC calls every other client makes — no compute-bound work of its own. **Forward-compatibility check, explicit rather than assumed**: the MCP server implementation itself is the one new real dependency this API introduces (an MCP SDK/library) — a genuinely new Telemetrees tracking entry, its own Day-0/Python-3.15+ support status worth tracking continuously rather than asserted here as a fixed fact.

---

## 9. gRPC surface

```protobuf
service AgentControlService {
  rpc IssueAgentToken(IssueTokenRequest) returns (AgentTokenResponse);        // owner/staff only
  rpc RevokeAgentToken(RevokeTokenRequest) returns (RevokeResponse);
  rpc ListAgentTokens(ListTokensRequest) returns (ListTokensResponse);
  rpc ExecuteAgentAction(AgentActionRequest) returns (AgentActionResponse);     // the actual MCP/CLI call path
}
```

---

## 10. Testing hooks
- **Owner-role ceiling test**: confirms no code path exists for an agent token to ever act with `owner`-level permissions, regardless of the issuing user's own role — direct enforcement of §3.1's hard ceiling.
- **Rate-limit enforcement test**: confirms the tighter mutating-action cap (§7) actually triggers independently of the general action cap, not just the looser of the two.
- **Revocation-takes-effect-immediately test**: confirms a revoked token's next action attempt fails cleanly, not on some delay.

---

## 11. Open questions for this deep-dive (logged, not guessed at)
- **Which MCP SDK/library** — not picked here; a real Day-0-tracked dependency choice once made.
- **Webapp-side settings UI for agent token management** — whether this gets its own screen or folds into the existing settings pattern isn't designed here.
- **Whether a `client`-role-scoped agent token is ever a real use case** (as opposed to only `staff`-equivalent tokens) — not resolved here; the current design assumes `staff`-equivalent is the common case, given most agent-automation use cases this API anticipates are administrative/operational rather than a regular user's own automation.
