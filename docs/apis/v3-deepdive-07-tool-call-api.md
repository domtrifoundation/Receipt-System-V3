# V3 Deep Dive: Tool Call API

**Companion files:** all prior deep-dives, especially `v3-deepdive-02-inference-api.md` (§5's `tool_calling.py` is this API's direct consumer).

**Status:** Seventh deep-dive session, first of a larger batch working through the remaining APIs. Unlike Auth/Account Guardian, this one has real V2 lineage (`llm_tools.py`, `ai_agent.py`) — but V2's tools were written against V2's own data model (a live, directly-writable Excel workbook), and a good chunk of this deep-dive's real work is re-mapping each tool category to its correct V3 API owner, not just relocating the code.

---

## 1. Scope & boundary

Tool Call API owns the **registry**: which tools exist, their JSON-schema parameter definitions, which are read-only vs. mutating, and which subset is enabled for a given calling context. It does not:
- **own tool implementation logic** — each tool is a thin wrapper calling into the API that actually owns the underlying capability (Architect's registry for vendor lookups, Geo/Address for geocoding, Search/Query for structured lookups). This API is a directory and a dispatch layer, not where business logic lives.
- **decide whether/when to call a tool** — that's the Inference API's tool-calling orchestrator's job (its own deep-dive §5), consuming this registry's manifest to build a constrained-decoding grammar and receiving back which tool the model chose. Tool Call API answers "what's available and how do I run it," never "should this run now."
- **auto-apply mutating actions** — see §4, a genuine safety principle worth carrying forward from V2 rather than an afterthought.

---

## 2. Package layout

```
core/tool_call/
  __init__.py
  contracts.py           # ToolSpec, ToolResult, ToolCategory, error types
  registry.py               # Provider Registry: which tools are registered, per-context filtering
  dispatch.py                # runs a requested tool call, never raises across the boundary
  tools/
    __init__.py
    vendor_tools.py            # wraps Architect API's registry (read) + temporal_learning (write)
    geo_tools.py                 # wraps Geo/Address API
    query_tools.py                # wraps Search/Query API — see §3.2, replaces V2's excel_query
    persistence_write_tools.py     # wraps Persistence's normal write path — see §3.2, replaces V2's excel_write_row
    settings_tools.py              # MUTATING_STAGED via review queue, not live confirmation — see §4.2
  errors.py
  metrics.py
```

---

## 3. Tool categories — mapped from V2's real precedent to their correct V3 owners

### 3.1 What carries forward directly
V2's read-only lookup tools map cleanly onto V3 APIs that already exist for exactly this purpose:
- `lookup_vendor_canon`, `lookup_vendor_tin_history`, `lookup_branch_by_address` → Architect API's registry (read side). The *write* equivalents (`remember_vendor`, `record_vendor_tin`, `record_vendor_address`, `record_vendor_franchiser`) → Architect's `temporal_learning` submodule, which already owns exactly this contribution/learning mechanism — these tools become thin wrappers around a mechanism that already exists, not new logic.
- `geocode_place` → Geo/Address API directly, same capability, same "only offer the tool if a provider is actually configured" pattern worth keeping (§3.3).
- The idle-worker tools (`find_next_quarantined_receipt`, `find_next_unreviewed_vendor`, `find_next_unbackfilled_row`, `find_next_flagged_amount_row`, `find_next_items_vendor_mismatch`, and their paired action tools) → Background Workers API's idle-time execution class for the *scheduling* half, and Review/Flagging's flag-resolution mechanism for the *acting-on-a-flag* half. These stay conceptually valid — V2's idle-time "go find something useful to fix" pattern was a genuinely good design, already folded into Background Workers API's own scope per file 01/03 — but the actual implementations now call V3's flag/queue mechanisms, not V2's direct file/row manipulation.

### 3.2 What needs correcting, not just relocating
**V2's `excel_query`/`excel_write_row` tools assumed a live, directly-queryable and directly-writable workbook file — that data model doesn't exist in V3 at all.** Excel is now a generated export (Persistence's Export Framework) with an explicit Reimport round-trip for edits flowing back in (Ingestion deep-dive's earlier corrections, and file 01's Persistence entry) — there's no "the workbook" for a tool to query or write against live during a run. The correct V3 replacements:
- **`persistence_query`** (`query_tools.py`) — wraps Search/Query API's FTS5-backed structured search, the actual V3 equivalent of "look up rows by vendor/date/trans ID." Read-only, same category as V2's `excel_query` was.
- **`persistence_write_field`** (`persistence_write_tools.py`) — wraps Persistence's normal write path directly (not Excel at all), meaning every tool-initiated write is automatically Historian-logged the same as any other write in the system — a strictly better guarantee than V2 had, since V2's `excel_write_row` calls didn't carry the same structural audit trail Persistence's write path now provides for free.

**V2's `finalize_receipt`/`finish_reconciliation` "tools" were a workaround, not a genuine tool-calling need, and likely don't carry forward as tools at all.** V2's models (llama.cpp-backed, non-instruct-tuned for tool use) had no real structured-output mechanism, so V2 faked one by defining "call this tool with your final answer" as a pseudo-tool. **V3's Inference API already has a genuine structured-output mechanism** (constrained decoding against a `response_schema`, Inference deep-dive §5) — a receipt's final vendor/date/amount is the direct return value of a schema-constrained generation call, not something that needs a fake tool invocation to smuggle out. **Confirmed, with explicit direction**: don't register `finalize_receipt`/`finish_reconciliation` as tools in V3 — and the actual reason this is correct, not just a relocation, is §3.4 below: the model's own final answer is simply the natural conclusion of the same agentic loop that calls real tools, never a separate mode requiring its own pseudo-tool to signal.

### 3.3 The actual orchestration loop — genuinely agentic, continue-or-stop as needed, not a fixed pipeline
**Never designed explicitly before this confirmation — real, previously-missing content, not just restating §3.2's recommendation.** The requirement, stated directly: the model reasons and calls tools across multiple rounds exactly like a genuine agentic loop (the same shape this project's own development process runs on), deciding for itself each round whether it needs more information or is ready to answer — never a fixed number of forced tool-call steps before an answer is allowed, and never stuck looping when it's already confident.
```python
async def run_tool_loop(receipt_context: ReceiptContext, max_rounds: int = 8) -> FinalAnswer:
    """Each round, the model does exactly one of two things:
    (a) calls one or more tools (persistence_query, lookup_vendor_canon,
        geocode_place, etc.) — the loop continues, tool results feed
        back into the model's own context for the next round.
    (b) produces its final answer directly, via constrained decoding
        against the receipt's own response_schema (Inference deep-dive
        §5) — the loop ends here, naturally, because the model chose
        to answer rather than call another tool, never via a fake
        'finalize' tool call signaling completion.
    The model decides which, every round, based on its own assessment
    of whether it has enough information — this is the actual
    mechanism behind 'continue or stop as needed.' max_rounds is a
    genuine safety cap, not the primary termination logic — it exists
    only to bound cost/latency if a model gets stuck in an unproductive
    loop, and hitting it is treated as a real failure mode (the receipt
    surfaces via Review/Flagging for human attention), not a normal,
    expected path."""
```
This is what "reasoning like Claude" concretely means in this system's own architecture: tool use and final-answer generation aren't two different modes requiring different mechanisms — they're the same loop, and the model's own choice each round is what determines whether it continues or concludes.

### 3.4 The "don't offer an always-failing tool" pattern — carries forward as-is
V2's `tools_for(cfg)` conditionally excluded `geocode_place` when no geo provider was configured, on the reasoning that offering a tool that can only fail wastes the model's own turns. Genuinely good design, worth keeping exactly: `registry.enabled_tools(context)` filters by both *category* (which tools this calling context is allowed at all — read-only vs. mutating, per-context subsets per file 01's own phrasing) and *live availability* (is the underlying capability actually configured/reachable right now).

---

## 4. Mutating tools during automated processing — self-applying, not propose-then-confirm

**Correction to an assumption this deep-dive initially carried over from V2 without checking it against V3's actual architecture: there is no live user to confirm anything with during automated processing, and V3 has no "AI Mode" interactive chat surface at all.** V2's `propose_setting_change` pattern (surface a yes/no to the user, only apply on confirmation) worked specifically because V2's AI Mode was an interactive chat session with a human actively present. V3's automated pipeline runs unattended — Execution Core processes a batch with nobody watching in real time, so a tool-calling loop that paused to "ask the user" would simply hang forever with no one to answer. **The correct V3 design is the opposite of what a naive V2 port would assume: mutating tools available during automated processing self-apply, on the model's own discretion, with no confirmation step** — safety comes from *which* tools are even offered in this context, not from a confirmation gate that has no one on the other end of it.

```python
class ToolCategory(str, Enum):
    READ_ONLY = "read_only"
    MUTATING_STAGED = "mutating_staged"     # writes into an existing review/audit gate downstream — safe to self-apply
    DEV_OBSERVABILITY = "dev_observability"    # pure reads, zero side effects — run status, health, logs, dependency status
    TEST_EXECUTION = "test_execution"            # triggers a real action with real side effects — killing a process, wiping a test tenant's data, submitting a receipt through the live pipeline
```
**`TEST_EXECUTION` decided as its own category, genuinely separate from `DEV_OBSERVABILITY` — resolved directly rather than left as a follow-up.** The two look similar on the surface (both exist to support development/debugging) but carry a materially different risk profile: `DEV_OBSERVABILITY` tools can never cause harm, since they only read existing state; `TEST_EXECUTION` tools (`v3-deepdive-56-test-orchestration.md`'s own `run_crash_isolation_test`, `reset_test_environment`, and siblings) have real, disruptive side effects if misused or if a safety guard has a bug in it. Folding these into one category would blur exactly the kind of read-vs-mutate distinction this project draws everywhere else (`READ_ONLY` vs. `MUTATING_STAGED` existing as separate categories for the identical reason) — worth the same discipline here rather than treating "it's just for dev use" as license to relax it.
**`DEV_OBSERVABILITY` is a real, distinct category, not folded into `READ_ONLY`** — the tools in it (run status, system health, historian narrative, log tailing, dependency status) are genuinely read-only in the same safety sense `READ_ONLY` already is, but they exist specifically to serve development/debugging workflows (Agent Control API's own MCP server and headless CLI), not the reconciliation-loop tool-calling context this API's own §3-4 otherwise describes. Keeping the category distinct means a future policy change to one context (say, tightening what an automated processing run can read) doesn't accidentally also affect the other.
**`MUTATING_DIRECT` (an irreversible action with no existing review gate) is deliberately not a category this API offers to the automated-processing tool-calling context at all** — not gated behind a confirmation mechanism that doesn't exist, simply never on the menu. Concretely: `remember_vendor`/`record_vendor_tin`/etc. self-apply during processing because they're staging a proposal into Architect's existing contribution moderation queue (LLM-prescreen → staff review → approve/merge, file 01 #25) — the safety gate is downstream and asynchronous, not a live conversation. A genuinely direct, ungated mutation (an account-level settings change with no review step behind it) simply isn't a tool the automated pipeline ever gets access to — if that capability is ever needed, it's a human acting through the normal UI, which is a completely different code path from LLM tool-calling and already goes through Audit/Notifications on its own terms (§4.1).

### 4.1 Post-processing / human-initiated mutating actions go through Audit and Notifications — but that's not really this API's concern
Staff resolving a Review/Flagging item, an owner changing a role, an account-recovery approval — these are **not LLM tool calls at all**, they're a human directly performing a privileged action through the UI. They already have a home: Audit API records them (its own deep-dive §4), Notifications surfaces them where relevant (break-glass's dual-notify pattern, its own deep-dive). Tool Call API doesn't need its own parallel mechanism for this case — the "should mutating actions be logged and notified" requirement is already fully satisfied by APIs built for exactly that, for the *human-action* case. This API's own scope stays narrower: tools the LLM can call during a run, which is a different problem with a different (self-applying, staged-safety) answer.

### 4.2 Settings changes, reconsidered given no live confirmation exists
V2's `propose_setting_change` assumed a chat partner to ask. Without that, a settings-change tool offered during automated processing (if one is ever wanted at all — not confirmed as needed, see §7) would need to be `MUTATING_STAGED`: it stages a proposed change into a review queue (the same moderation-queue shape Architect already uses for vendor contributions) for staff to approve asynchronously, rather than either applying directly or blocking on a confirmation that has nowhere to go. Whether an LLM mid-run ever actually needs to propose a settings change — as opposed to that being purely a human/staff action through the UI — isn't confirmed; flagged in §7.

---

## 5. Data contracts (`contracts.py`)

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: FrozenDict         # JSON Schema — the exact shape Inference API's ToolSpec (its own deep-dive §3) expects
    category: ToolCategory

@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    result: FrozenDict                     # the tool's own return payload
    error: str | None = None          # populated, never raised — matches V2's own dispatch() convention, still correct

@dataclass(frozen=True)
class ToolContext:
    run_id: str
    user_id: str
    calling_api: str                  # "inference_reconciliation", etc. — determines the enabled subset
```
**`FrozenDict` here, not plain `dict`** — see §6's frozendict policy note. A `@dataclass(frozen=True)` with a plain `dict` field is only shallowly immutable; the dataclass itself can't be reassigned, but its `dict` field can still be mutated in place (`tool_result.result["x"] = "y"` would silently succeed). Given `ToolResult`/`ToolSpec` instances get passed across the Inference API boundary and potentially cached, this is exactly the kind of shared-mutable-state bug the rest of this project's "errors are data, immutability at the boundary" convention is trying to avoid — worth closing the gap here rather than leaving it as a subtle exception.

---

## 6. Asyncio, profiling, and the frozendict policy
Every tool wraps a call into another API (Architect, Geo/Address, Search/Query, Persistence) — this API has no compute of its own, same I/O-bound, thin-orchestration-layer shape as Account Guardian's own conclusion (its deep-dive §7). Nothing to add beyond that cross-reference for asyncio/profiling specifically.

**Frozendict policy (applies project-wide, stated here since this API's `contracts.py` is the first to need it directly)**: Python 3.15 adds `frozendict` as a genuine built-in immutable, hashable mapping type (PEP 814) — a real gap to close, since a `@dataclass(frozen=True)` with a plain `dict` field is only shallowly immutable (the field can't be reassigned, but the dict it points to can still be mutated in place). Every `dict`-typed field on an otherwise-frozen dataclass across this project's contracts should be `FrozenDict` instead, not left as a quietly-still-mutable exception. Version-gated shim, since `frozendict` is only a true zero-import builtin on 3.15+ and needs a PyPI package (`pip install frozendict`, environment-marker-scoped to `python_version < "3.15"` so it's never installed where it'd be redundant) on everything earlier:
```python
# common/frozen_dict.py
try:
    FrozenDict = frozendict            # Python 3.15+ builtin (PEP 814) — no import needed, just referencing the builtin name
except NameError:
    from frozendict import frozendict as FrozenDict   # PyPI package, pre-3.15
```
**One real compatibility gotcha worth flagging explicitly**: the builtin `frozendict` is *not* a subclass of `dict` (it inherits directly from `object`) — existing `isinstance(x, dict)` checks anywhere in this codebase silently fail to recognize a `FrozenDict` value on 3.15+. Any such check needs updating to `isinstance(x, (dict, frozendict))` or, better, the forward-compatible `isinstance(x, collections.abc.Mapping)` — worth an actual audit pass across the codebase once this lands, not assumed safe by default. **Telemetrees ownership, consistent with every prior deep-dive's version-tracking discipline**: track the PyPI `frozendict` package's own compatibility posture (does it get updated to match the builtin's exact semantics, e.g. hashability rules) as a Dependencies Warden entry, since the pre-3.15 shim's correctness depends on it matching, not just existing.

---

## 7. Testing hooks — a real gap found during a pre-development sweep, genuinely absent from the original document
- **Category-enforcement test**: confirms a `MUTATING_STAGED` tool genuinely cannot self-apply without landing in its downstream review gate, and that a `READ_ONLY` tool has no write path at all — the concrete validation of §3-4's entire safety model rather than trusting the categorization is honored by convention.
- **Agentic-loop termination test**: confirms the multi-round loop (§3.3) actually terminates on the model's own final answer, and that `max_rounds` genuinely caps a pathological non-terminating case rather than being a nominal limit nothing enforces.
- **`DEV_OBSERVABILITY`/`TEST_EXECUTION` separation test**: confirms no tool is registered in both categories, and that a `DEV_OBSERVABILITY` tool genuinely has no side effects — the distinction §4 draws is only real if something checks it.
- **Calling-context scoping test**: confirms a tool not in a given `calling_api`'s own enabled subset is genuinely unreachable from that context, not merely undocumented.

---

## 8. Open questions for this deep-dive (logged, not guessed at)

- (Confirm `finalize_receipt`/`finish_reconciliation` are dropped as tools — resolved, no longer open. Confirmed, and the actual reason it's correct is now designed explicitly: §3.3's genuine multi-round agentic loop, where the model's own final answer is simply the natural conclusion of the same loop that calls real tools, never a separate mode. `max_rounds` is a safety cap, not the primary termination logic — the model decides to continue or stop every round.)
- **`persistence_write_field`'s exact scope, resolved: a narrower, explicitly-enumerated set of writable fields, even within `MUTATING_STAGED`.** Consistent with this project's own repeated discipline against blanket capabilities (Task Scheduler's own curated schedulable-action allowlist, the enumerated custom-screen exception list) — "any field a schema permits" is exactly the kind of open-ended surface this project avoids elsewhere, and there's no reason this tool should be the exception. The concrete enumerated set is Persistence's own responsibility to define once its field/permission model exists, but the *shape* of the answer (narrow, explicit, not blanket) is settled here.
- **Whether any settings-change tool is needed during automated processing at all, resolved: no, not in the initial design.** Automated processing is about receipt reconciliation, not settings management — a genuinely different concern with no clear need to blend into the same tool-calling context. Settings changes stay a human/staff UI action exclusively unless a concrete, specific need surfaces later; not built speculatively now.
- (The `ai_mode_chat` calling context — resolved, no longer open in the form this question asked it. V2's general chat-driven control surface doesn't carry forward as a consumer of *this* API at all — the replacement, `v3-deepdive-54-webapp-assistant.md`, is a much narrower natural-language help feature with zero data access and no tool-calling of any kind, embedded directly into the settings-search and support-ticket UI rather than a chat surface with its own tool needs. This document's own reconciliation-loop tool set stays scoped to exactly what it already covers, untouched by any of this.)
- (Bounded tool-call conversation history — resolved, no longer open in the form this question asked it. `max_rounds` (§3.3, default 8) already is this bound — every round adds to the conversation history the same way it adds to the tool-call count, so capping rounds caps history length as a direct consequence, not a second mechanism needing its own separate value.)
