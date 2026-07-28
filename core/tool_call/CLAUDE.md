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

`a02.00.00`

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
