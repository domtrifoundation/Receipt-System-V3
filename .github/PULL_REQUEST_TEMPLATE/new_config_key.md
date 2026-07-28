## Summary
<!-- What key, on which API's config block -->

## Full guide
See [`docs/templates/new_config_key.md`](../../docs/templates/new_config_key.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] Namespaced under the owning API's own config block
- [ ] Default value stated with reasoning (bench-derived or explicitly provisional)
- [ ] Tier-profile applicability stated (yes/no/not-yet-relevant)
- [ ] **Forward-Compatibility Hygiene**: if dict-shaped in code, uses `FrozenDict`
- [ ] If changing an existing key's shape/meaning, a Migration API step is included in the same PR
