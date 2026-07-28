# Adding a New Taxonomy / Typed Data Category

## When this applies
You need a new kind of structured, evolvable, or learned data — a new reference-identifier type (like license plate, utility account number), a new flag type, a new document-type category, a new anything that feels like "we need a new table for this." **Read this before you create a table.**

## The rule, restated because it's easy to talk yourself out of
`docs/PRINCIPLES.md` §3.4: **no API is permitted to define its own ad hoc extensible-typed-thing, spin up its own SQLite table for learned/schema data, or invent a parallel taxonomy, even for a single narrow case.** This rule exists because the same pattern was independently reinvented five separate times before Architect API was created specifically to consolidate it. If you're reading this template because your use case "is different" or "is too small to matter," it almost certainly isn't — that exact reasoning is how it happened five times already.

## What registering through Architect actually requires
1. **Confirm it's genuinely a new category**, not an instance of an existing one — check Architect's current registry first (`v3-deepdive-26-architect-api.md` §1) before assuming you need a new type.
2. **Submit through the same contribution/moderation pipeline** every other taxonomy addition goes through (`temporal_learning`'s staged-review flow, Architect deep-dive §4) — a new type isn't exempt from review just because it's infrastructure-shaped rather than data-shaped.
3. **State who consumes it** — a taxonomy type that nothing reads is dead weight; the PR should name the actual consuming API(s).
4. **If it's a reference-identifier type** (the `type`/`value` pairs pattern Persistence's own receipt data model uses), confirm it fits that existing shape rather than needing its own bespoke column.

## PR checklist
- [ ] Confirmed against Architect's current registry that this is genuinely new, not an existing type under a different name
- [ ] Submitted through Architect's contribution/moderation pipeline, not created directly
- [ ] At least one real consuming API identified in the PR description
- [ ] **Forward-Compatibility Hygiene**: if this type's contract has a dict-typed field, it uses `FrozenDict`
- [ ] No new SQLite table created outside Architect's own database for this

## CI test: `check_no_shadow_taxonomy.yml`
**What it checks**: a static scan across every package for `CREATE TABLE` statements, ad hoc `Enum` classes that look taxonomy-shaped (heuristically: an `Enum` with more than a handful of members living outside `core/architect/`), or new dataclass fields typed as a fresh, narrow `Literal[...]` where an existing Architect-registered type would fit — flagging (not silently blocking, since some of these are legitimately fine and this check will have false positives) for manual review.
**Recommended use**: automatic on every PR. Given this check is heuristic and will occasionally flag something that's actually fine (a genuinely API-internal enum that has nothing to do with cross-cutting taxonomy), the recommended workflow is: read the flag, confirm deliberately whether it's a real violation or a false positive, and if it's a false positive, add it to the check's own allowlist with a one-line reason in the same PR — so the next person hitting the same false positive doesn't have to re-litigate it.
