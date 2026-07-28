## Summary
<!-- What new typed/learned data category, and which API(s) will consume it -->

## Full guide
See [`docs/templates/new_taxonomy_type.md`](../../docs/templates/new_taxonomy_type.md) for the full explanation and reasoning behind this checklist — **read this before creating a table.**

## Checklist
- [ ] Confirmed against Architect's current registry that this is genuinely new
- [ ] Submitted through Architect's contribution/moderation pipeline, not created directly
- [ ] At least one real consuming API identified
- [ ] **Forward-Compatibility Hygiene**: dict-typed fields on this type's contract use `FrozenDict`
- [ ] No new SQLite table created outside Architect's own database for this
