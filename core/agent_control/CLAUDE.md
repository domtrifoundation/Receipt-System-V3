# Agent Control API

Agent Control owns programmatic access to a running instance for AI agents and automation — Claude Code specifically, but designed generally rather than Claude-Code-specific. It provides two related but distinct surfaces: an MCP server, and a headless/scriptable interface that doesn't require either the TUI or webapp to be rendered.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `ai_agent.py` gave V2's *own* embedded LLM a toolset inside the running program — the ancestor of Tool Call API, not of this one. Nothing in V1 or V2 exposed a running instance to an external agent or automation. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-55-agent-control-api.md`](../../docs/apis/v3-deepdive-55-agent-control-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own a second, parallel permission model.** Every agent action is bound by the exact same role-based enforcement a human session would be — Auth's own roles, Tool Call's own `MUTATING_STAGED`/`READ_ONLY` categorization. An agent is never more capable than the human who authorized it.
- **bypass the TUI or webapp's own capabilities** — it's a genuine third interface onto the same underlying gRPC core both of them already talk to, not a backdoor around either. Anything an agent can do through this API, a human could also do through the TUI or webapp; this API just makes it scriptable.
- **grant itself access** — an agent token is always explicitly issued by a human owner/staff member through the normal settings surface (§3 below), never self-provisioned.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This is the one API implemented for real in Phase 1 rather than scaffolded — its MCP server and headless CLI have to work from the start of Phase 2, not be built partway through it. Three properties are structural, not policy: an agent is never more capable than the human who authorized it, an agent token can never carry `owner` role regardless of who issues it, and a token is always issued by a human — never self-provisioned. Tokens are stored as SHA-256 hashes; the plaintext is shown once at issue time and is not recoverable.

**The MCP server and the CLI are both gRPC clients of `service.py`, not independent implementations.** Every token check, scope check, rate limit, and audit write happens once, server-side. Keep it that way — the moment either surface starts enforcing anything itself, the two can drift and one of them becomes the more permissive path.

**MCP transport is deliberately dependency-free.** The deep-dive's §11 logs "which MCP SDK/library" as a genuinely open question, so `mcp/server.py` implements the wire protocol directly (JSON-RPC 2.0 over newline-delimited stdio) rather than settling that question by importing one. Adopting an SDK later replaces that one file instead of rippling outward.

**Files here that the deep-dive's §2 package layout does not list**, added in Phase 1 with reasons:
- `agent_control.proto` + `generated/` — §9 specifies the gRPC surface but the layout predates showing where the `.proto` lives. Regenerate with `python -m grpc_tools.protoc` and re-apply the relative-import fix in `agent_control_pb2_grpc.py`; do not hand-edit generated files.
- `service.py` — the servicer implementing §9. The layout jumps straight from `contracts.py` to the two surfaces without naming the thing they are both clients of.
- `backends/` — the swappable Core-API transport (`docs/PRINCIPLES.md` §1.3). The layout assumed the core cluster was running; in Phase 1 it is not, so this is where "which callees actually exist" is answered honestly rather than at each call site.
- `store.py` — SQLite for tokens, the agent audit trail, and rate counters. **This is a bounded exception to "only Persistence touches disk"**, taken because Agent Control is implemented before Persistence exists. It holds no receipt or user business data and lives in the top-level install directory, never the repo. When Persistence and Audit exist, the audit half moves to Audit API's own append-only log and this file keeps only the token table.

**Unavailable callees return `CoreUnavailable`, never plausible-looking data.** A fabricated health report or invented run status is worse than an error, because an agent will reason from it. Preserve that when filling the backends in.

**`dev_token_gateway.py` — the real answer to "how does a fully-AI developer, with no
human ever in the loop, get MCP access from a fresh install."** This project's own rule
(above) is that a token is always issued by a real human — correct for a human-operated
install, where the whole premise of a human sitting there means MCP would not typically
even be used. It does not fit an unattended AI-developer install, where there is no human
to click anything, ever. `AgentControlDevTokenGateway` implements
`services/setup/contracts.py`'s `AgentTokenSeedGateway` Protocol, called only from
`services/setup/dev_fixtures.py`'s `seed_dev_environment()` when a caller explicitly
supplies it — never automatically. The authorizing human act is running `setup-dev`
itself (the same reasoning the deep-dive's §4.1 already uses for silently creating the
implicit-owner account in dev mode); `issued_by="setup-dev-bootstrap"` names that decision
honestly rather than attributing it to an invented person. The issued token is `staff`-role
(never `owner`, §3.1's ceiling still applies), scoped to `read_only`/`mutating_staged`/
`dev_observability` — never `test_execution`, which kills processes and wipes test
tenants — and its plaintext is written to `<install_root>/config/dev_agent_token.txt`
rather than shown once through a UI, since there is no human present to show it to.

**This is documented explicitly for the AI-developer-only track this project is headed
toward once Zircon ships** (see `docs/MAINTENANCE.md`'s own "AI-developer installs" note)
— a future session picking up that track should start here, not reinvent this seam.
