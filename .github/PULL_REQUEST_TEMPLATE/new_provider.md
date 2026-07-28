## Summary
<!-- What provider is this, and which registry (OCR engines, export providers, etc.) -->

## Full guide
See [`docs/templates/new_provider.md`](../../docs/templates/new_provider.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Implements the existing Protocol for this registry — no parallel interface invented
- [ ] Degrades gracefully to "unavailable" if its dependency is missing/unreachable
- [ ] External library/service sits behind its own adapter
- [ ] **Forward-Compatibility Hygiene checked as ONE pass**: FrozenDict for any dict-typed contract field; underlying library's Day-0/3.15+ and free-threading support checked
- [ ] **Backward-Carrying Capability checked**: if this is a scan/output-quality provider, is it reachable from Reconciliation's own retroactive sweep? If N/A, say why
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): a new provider is exactly this rule's target case, wire it into Reconciliation or state why not
- [ ] Config entry added, following the existing block shape
- [ ] If corroborating with existing providers, real-data comparison included or explicitly flagged as still needed
- [ ] Unit test added covering both success and "dependency unavailable" paths
- [ ] Relevant deep-dive document's provider section updated if this is genuinely new technology
