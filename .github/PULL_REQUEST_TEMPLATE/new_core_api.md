## Summary
<!-- What API is this, in one or two sentences -->

## Full guide
See [`docs/templates/new_core_api.md`](../../docs/templates/new_core_api.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Scope/boundary stated, including explicit "does not own" list
- [ ] Package layout follows `docs/PRINCIPLES.md` §1.1
- [ ] All cross-boundary contracts are frozen dataclasses; dict fields use `FrozenDict`
- [ ] Concurrency bucket stated explicitly
- [ ] **Forward-Compatibility Hygiene checked as ONE pass**: FrozenDict done above; new dependency's Day-0/3.15+ support checked; free-threading relevance confirmed or ruled out
- [ ] **Collective enumerations updated**: file 02's concurrency table, PROCESS_TOPOLOGY's count/map, and any other all-API list — not just this API's own doc and file 01
- [ ] **Backward-Carrying Capability checked**: if this touches scan/output quality or Reconciliation, is it reachable from Reconciliation's own retroactive sweep? If N/A, say why
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): if this touches scan/output quality or Reconciliation, wire it in or state why not
- [ ] `.proto` sketch included
- [ ] No new ad hoc schema/taxonomy — confirmed routed through Architect API, or confirmed genuinely not applicable
- [ ] Full deep-dive document added
- [ ] Numbered entry added to the core API list
- [ ] Reviewed against `docs/PRINCIPLES.md` in full
