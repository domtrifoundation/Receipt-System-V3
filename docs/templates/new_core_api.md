# Adding a New Core API

## When this applies
You're proposing a genuinely new top-level domain of responsibility — something that doesn't fit inside any existing API's scope, isn't a sub-package of one, and needs its own gRPC service, its own `contracts.py`, and its own place in the numbered API list (`v3-plan-01-core-apis.md`). This is the highest-weight addition category in the project — most things you want to add are a Provider Registry entry (see `new_provider.md`) or a sub-API (see `new_sub_api.md`) instead. Check those first.

## What a new Core API requires, concretely
1. **A scope-and-boundary statement** — what it owns, and just as important, what it explicitly does *not* own (the pattern every existing deep-dive follows: 2-4 bullets of "it does not..."). If you can't write the "does not" list confidently, the scope isn't clear enough yet.
2. **Package layout** — `core/<api>/` or `services/<api>/`, following `docs/PRINCIPLES.md` §1.1 (package-per-API, ~300-400 line soft cap per file).
3. **Data contracts** (`contracts.py`) — every cross-boundary type `@dataclass(frozen=True)`, `FrozenDict` for any dict-typed field (`docs/PRINCIPLES.md` §2.1).
4. **A concurrency classification** — which of the three buckets (async I/O / native-GIL-released / no-GIL-candidate, `docs/PRINCIPLES.md` §5) it falls into, stated explicitly, not left implicit.
5. **A gRPC `.proto` sketch** — the actual service definition, following the versioning discipline in `new_grpc_endpoint.md`.
6. **Genuine checks against `docs/PRINCIPLES.md` §0 (the V2 Rule) and §3.4 (Architect owns all typed/learned data)** — if this API's job involves anything V2 also did, the design must be independently derived, not ported; if it needs any new schema/taxonomy/learned data, that goes through Architect API, not a new table here.
7. **A full deep-dive document**, matching the depth of the existing `v3-deepdive-*.md` corpus (package layout, contracts, dependencies, hardware/concurrency, gRPC surface, config, testing hooks, open questions) — not a stub.
8. **An entry in `v3-plan-01-core-apis.md`'s numbered list**, plus a note in `v3-plan-03-decisions.md` if the addition changes any cross-cutting decision.

## PR checklist
- [ ] Scope/boundary stated, including explicit "does not own" list
- [ ] Package layout follows `docs/PRINCIPLES.md` §1.1
- [ ] All cross-boundary contracts are frozen dataclasses; dict fields use `FrozenDict`
- [ ] Concurrency bucket stated explicitly
- [ ] **Forward-Compatibility Hygiene checked as ONE pass, not split apart** (`docs/PRINCIPLES.md` §3.3, §5): FrozenDict done above; any new dependency's Day-0/Python 3.15+ support checked; free-threading relevance confirmed or explicitly ruled out; Tachyon/py-spy applicability stated if this API does any real compute work
- [ ] **Collective enumerations updated** — a new Core API must be added to *every* document that enumerates or classifies all APIs together, not just its own deep-dive and `v3-plan-01-core-apis.md`: `v3-plan-02-architecture.md`'s own per-API concurrency table, `docs/PROCESS_TOPOLOGY.md`'s own count and quick-reference map, and any other collective list. **This is the single most-repeated structural miss in this project's history** — it recurred at least three separate times before this checkbox existed, always the same way: the new API's own document gets written, file 01 gets updated, and the collective references silently go stale.
- [ ] **Backward-Carrying Capability checked** (`docs/PRINCIPLES.md` §1.9): if this API touches scan/output quality (OCR, Preprocessing, Matching, Inference, Geo/Address) or Reconciliation itself, is it built so Reconciliation can apply it retroactively to already-processed receipts — one shared function called by both the live pipeline and Reconciliation's own sweep, never two implementations? If not applicable, state why explicitly rather than omitting the question.
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): if this API touches scan/output quality (OCR, Preprocessing, Matching, Inference, Geo/Address) or Reconciliation itself — either wire the improvement into Reconciliation so it can be applied retroactively to already-processed receipts, or explicitly state in the PR description why backward application doesn't apply here. Never silently skipped.
- [ ] `.proto` sketch included
- [ ] No new ad hoc schema/taxonomy — confirmed routed through Architect API, or confirmed genuinely not applicable
- [ ] Full deep-dive document added to `docs/apis/` (or wherever the corpus lives at time of PR)
- [ ] Numbered entry added to the core API list
- [ ] Reviewed against `docs/PRINCIPLES.md` in full, not just skimmed

## CI test: `check_new_core_api.yml`
**What it checks**: every package under `core/`/`services/` has a corresponding `contracts.py` with only frozen dataclasses (via AST inspection — flags any non-frozen `@dataclass` or raw `dict`-typed field on one), a `service.py`, and a matching deep-dive document reachable from the docs index. Also checks the new API doesn't define any table/schema construct that isn't routed through Architect API's own registry (a static grep for `CREATE TABLE`/`sqlite3.connect` outside `core/architect/` and outside each API's own already-approved cross-user database — see `docs/PRINCIPLES.md` §3.4).
**Recommended use**: runs automatically on any PR touching a new top-level package under `core/`/`services/`. Also runnable locally (`pytest tests/ci/test_new_core_api.py`) before pushing, to catch the same issues without waiting on CI round-trip time.
