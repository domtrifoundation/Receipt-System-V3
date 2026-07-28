# Adding a New Config Key

## When this applies
You're adding a new value to an API's own config block — a threshold, a toggle, a provider selection, anything read from the top-level config rather than hardcoded.

## What a new config key requires
1. **Lives in the owning API's own config namespace** — `<api_name>.<key>`, matching the existing per-API config block convention throughout this project (`ocr:`, `preprocessing:`, `auth:`, etc.), never a top-level flat key that doesn't indicate which API owns it.
2. **A sensible default**, stated and justified — "reasoned, then measured" (`docs/PRINCIPLES.md` §5): if the default is a real bench-derived value, say so; if it's a starting placeholder pending real data, say that too, explicitly, the same way many of this project's own deep-dives flag their own config defaults as provisional in their open-questions sections.
3. **If it affects per-run tier-profile bundling** (the `basic`/`pro`/`enterprise` tier system, `v3-plan-03-decisions.md`'s own decision record) — state explicitly whether this new key is meant to be part of that bundle eventually, or is a global, non-tiered setting. Don't leave this ambiguous; a future tier-profile mechanism needs to know which knobs it's allowed to vary per tier.
4. **Schema-versioned if it changes an existing key's meaning or type** — goes through Migration API's own N→N+1 chain (`v3-deepdive-23-migration-api.md`), never a silent config-shape change that breaks an existing install's saved config.

## PR checklist
- [ ] Namespaced under the owning API's own config block
- [ ] Default value stated with reasoning (bench-derived or explicitly provisional)
- [ ] Tier-profile applicability stated (yes/no/not-yet-relevant)
- [ ] **Forward-Compatibility Hygiene**: if this key's value is dict-shaped in code (not just YAML), the corresponding contract uses `FrozenDict`
- [ ] If changing an existing key's shape/meaning, a Migration API step is included in the same PR

## CI test: `check_config_schema.yml`
**What it checks**: validates the config schema file against every API's own documented config block (parsed from each deep-dive's `## Config` section, or from a machine-readable schema file if the project has moved to one by the time you're reading this) — catching a config key that exists in code but was never documented, or documented but never actually read anywhere.
**Recommended use**: automatic on any PR touching config-loading code. Also worth running after any refactor that renames a config key, since that's exactly the kind of change that can leave a stale reference in a deep-dive document or an actual `.yaml`/`.toml` example that no longer matches what the code reads.
