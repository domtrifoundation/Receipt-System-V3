# Agent Control API

Agent Control owns programmatic access to a running instance for AI agents and automation — Claude Code specifically, but designed generally rather than Claude-Code-specific. It provides two related but distinct surfaces: an MCP server, and a headless/scriptable interface that doesn't require either the TUI or webapp to be rendered.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `ai_agent.py` gave V2's *own* embedded LLM a toolset inside the running program — the ancestor of Tool Call API, not of this one. Nothing in V1 or V2 exposed a running instance to an external agent or automation. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

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
