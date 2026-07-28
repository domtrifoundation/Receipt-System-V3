## Summary
<!-- What dependency, and why -->

## Full guide
See [`docs/templates/new_dependency.md`](../../docs/templates/new_dependency.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Behind its own adapter module — no scattered direct imports in business logic
- [ ] "Why this dependency" reasoning stated, including alternatives considered
- [ ] Added to Telemetrees' tracked-dependency inventory with the right fact kinds
- [ ] Environment-marker-scoped install if version-sensitive
- [ ] If this introduces a version-sensitive shim, a check registered in Health API's capability drift registry
- [ ] License checked and stated
- [ ] If C-extension-backed, free-threading support status checked and noted
