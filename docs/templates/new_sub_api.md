# Adding a New Sub-API / Sub-Package

## When this applies
You're adding a genuinely substantial capability that belongs *under* an existing Core API's own package (like Historian, Reimport, or Disaster Recovery under Persistence; Watchdog under Health) — narrower in scope than a full Core API, but big enough to warrant its own contracts, its own testing hooks, and often its own full deep-dive document per the project's own precedent (`v3-deepdive-29` through `v3-deepdive-37`). If what you're adding is really just one more entry in an existing registry (one more OCR engine, one more export provider), use `new_provider.md` instead — that's a much lighter-weight addition.

## What a new sub-API requires
1. **A clear parent relationship** — which Core API it lives under, and why it's a sub-package rather than its own peer API (the test used throughout this project: does it need its own independent gRPC service and lifecycle, or does it make more sense living inside its parent's own package and being queried through the parent's own service?).
2. **Package placement**: `core/<parent>/<sub_api_name>/`, following the same file-size discipline as everything else.
3. **A scope-boundary statement relative to its siblings**, not just the outside world — e.g. Historian's own deep-dive spends real effort distinguishing itself from Logs and Audit specifically, since the boundary between adjacent things is where confusion actually happens, not the boundary against something obviously unrelated.
4. **Whether it needs its own full deep-dive document** — the project's own judgment call (see the parent PR that split Persistence's five sub-components into their own documents): if the parent document's own summary would either get too long or genuinely undersell the sub-API's real design surface, it gets its own file, linked from the parent's own section.

## PR checklist
- [ ] Parent API identified, and the "why a sub-package, not a peer API" reasoning stated
- [ ] Scope boundary against sibling sub-APIs/capabilities explicitly stated, not just against the outside world
- [ ] Package lives under the correct parent path
- [ ] Contracts follow the same frozen-dataclass/`FrozenDict` discipline as everything else
- [ ] **Forward-Compatibility Hygiene checked as ONE pass, not split apart** (`docs/PRINCIPLES.md` §3.3, §5): concurrency bucket stated; any new dependency's Day-0/Python 3.15+ support checked; free-threading relevance confirmed or explicitly ruled out
- [ ] **Backward-Carrying Capability checked** (`docs/PRINCIPLES.md` §1.9): if this sub-API touches scan/output quality or Reconciliation itself, is it built so Reconciliation can apply it retroactively to already-processed receipts, one shared function rather than two implementations? If not applicable, state why explicitly.
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): if this sub-API touches scan/output quality or Reconciliation itself — either wire the improvement into Reconciliation so it can be applied retroactively to already-processed receipts, or explicitly state why not. Never silently skipped.
- [ ] Parent document's own section updated with at minimum a summary and a pointer, even if the full detail lives in a separate file
- [ ] If a separate full deep-dive document was warranted, it exists and is linked bidirectionally (parent → child, child → parent)

## CI test: `check_new_sub_api.yml`
**What it checks**: confirms every subdirectory nested inside an existing Core API's package that contains its own `contracts.py` also has a corresponding section (searchable by directory name) in that parent API's own deep-dive document — catching the specific failure mode of a sub-package existing in code with no discoverable design documentation pointing at it.
**Recommended use**: automatic on any PR adding a new subdirectory with its own `contracts.py` inside an existing Core API's package. Also worth running manually (`pytest tests/ci/test_new_sub_api.py`) after any refactor that moves code between a parent and a sub-package, since that's exactly the kind of change that can silently orphan a documentation pointer.
