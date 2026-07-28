# Tool Call API

Tool Call API owns the **registry**: which tools exist, their JSON-schema parameter definitions, which are read-only vs. mutating, and which subset is enabled for a given calling context.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2's `ai_agent.py` and `llm_tools.py` had a real registry with per-context toolsets (`OCR_TOOLS`, `VENDOR_WRITE_TOOLS`, `EXCEL_TOOLS`, `SETTINGS_TOOLS`, `CONTROL_TOOLS`, `IDLE_TOOLS`), a mutating-action whitelist, and dispatch returning `{"error": ...}` rather than raising. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-07-tool-call-api.md`](../../docs/apis/v3-deepdive-07-tool-call-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own tool implementation logic** — each tool is a thin wrapper calling into the API that actually owns the underlying capability (Architect's registry for vendor lookups, Geo/Address for geocoding, Search/Query for structured lookups). This API is a directory and a dispatch layer, not where business logic lives.
- **decide whether/when to call a tool** — that's the Inference API's tool-calling orchestrator's job (its own deep-dive §5), consuming this registry's manifest to build a constrained-decoding grammar and receiving back which tool the model chose. Tool Call API answers "what's available and how do I run it," never "should this run now."
- **auto-apply mutating actions** — see §4, a genuine safety principle worth carrying forward from V2 rather than an afterthought.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

V2's propose-then-confirm pattern for mutating tools is deliberately *not* carried forward (`docs/MAINTENANCE.md` §4): V3 has no interactive chat surface during automated processing, so there is no live user to confirm with. Safety comes from *which* tools are offered — only ones staging into an existing review gate — not from a confirmation step with nothing to confirm against. The `DEV_OBSERVABILITY` category is defined here and consumed by Agent Control; it is not Agent Control's own private category.

**`ToolContext` carries no `role` field, and that absence is the guarantee.** Permission
resolution happens server-side from the caller's session through Auth & Tenancy; a `role` field
on the context would be a caller-asserted role, and the gate would be checking the caller's own
claim about itself. `session_id` is an addition beyond the deep-dive's own §5 sketch for exactly
this reason — a session is the one thing Auth can resolve a real `Role` from.

**The two gates are independent and both must pass, in this order**: the calling-context gate
first (`CALLING_API_ALLOWED_CATEGORIES`), then the role gate (`CATEGORY_ALLOWED_ROLES`). The
order is asserted in the tests, not incidental — if the role gate ran first, an owner-role
reconciliation run denied a `TEST_EXECUTION` tool would get `PERMISSION_DENIED`, implying the
right role would unlock it. `CONTEXT_NOT_ENABLED` says the correct thing instead: this surface
does not offer that tool at all, to anyone.

**Everything unresolvable is a denial.** A resolver that raises (Auth unreachable), a resolver
that returns `None`, an availability check that throws, an unknown `calling_api` — all four
deny (`docs/PRINCIPLES.md` §4.2). The default resolver, `deny_all_permissions`, denies
unconditionally, so a caller that forgets to wire Auth in gets a closed gate rather than a
silently permissive one.

**`MUTATING_DIRECT` deliberately does not exist as a category.** §4 of the deep-dive is
structural about this: an unattended pipeline has no confirmation mechanism to gate such a tool
*with*, so an ungated mutation is simply never on the menu rather than existing-but-restricted.
A test asserts the enum's exact membership so adding one has to be deliberate.

**A denied privileged attempt is audited, not just a successful one.** An audit trail showing
only what succeeded cannot answer "did something try", which is where an investigation starts.
This is why `dispatch` looks the entry up once *before* the enforcement gate — so a refused
`MUTATING_STAGED` call still has a known category to record against.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `metrics.py` — listed in the layout but with no design behind it; the counters are shaped to
  make one specific degradation visible: a gap between privileged `invocations_total` and
  `audit_records_written` is the operator-facing signal that the audit sink is failing, since
  an audit-sink outage must not corrupt a tool result already computed (§4.4) and therefore
  cannot announce itself by failing the call.

**Known gap, flagged rather than silently filled**: this API has no `.proto` yet. Its own
deep-dive specifies no gRPC surface — unusually, its §7 is testing hooks rather than a wire
contract — while `docs/PROCESS_TOPOLOGY.md` establishes that every Core API runs as its own
process reachable only over internal gRPC. Those two cannot both be right. Inventing a surface
the deep-dive never specified is a design decision, not an implementation detail, so it is
recorded here for the PR that resolves it rather than guessed at. The in-process entry point
(`dispatch.dispatch`) is complete and tested in the meantime.
