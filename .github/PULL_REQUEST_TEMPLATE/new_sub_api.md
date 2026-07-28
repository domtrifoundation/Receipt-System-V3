## Summary
<!-- What sub-API/capability is this, and which Core API is it under -->

## Full guide
See [`docs/templates/new_sub_api.md`](../../docs/templates/new_sub_api.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Parent API identified, and the "why a sub-package, not a peer API" reasoning stated
- [ ] Scope boundary against sibling sub-APIs/capabilities explicitly stated
- [ ] Package lives under the correct parent path
- [ ] Contracts follow the frozen-dataclass/`FrozenDict` discipline
- [ ] **Forward-Compatibility Hygiene checked as ONE pass**: concurrency bucket stated; any new dependency's Day-0/3.15+ support checked
- [ ] **Backward-Carrying Capability checked**: if this touches scan/output quality or Reconciliation, is it reachable from Reconciliation's own retroactive sweep? If N/A, say why
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): if this touches scan/output quality or Reconciliation, wire it in or state why not
- [ ] Parent document's own section updated with at minimum a summary and a pointer
- [ ] If a separate full deep-dive document was warranted, it exists and is linked bidirectionally
