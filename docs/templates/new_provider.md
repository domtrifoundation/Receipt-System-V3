# Adding a New Provider Registry Entry

## When this applies
This is the **most common** addition category in this project, and the lightest-weight — a new OCR engine, a new Preprocessing variant kind, a new Inference hardware backend/preset, a new Geo/Address provider, a new blob backup target, a new Export Framework provider, a new Notifications outbound channel, a new SSO/credential strategy, a new payment provider. All of these follow the identical shape: `docs/PRINCIPLES.md` §1.2's Provider Registry pattern — implement a small `Protocol`, register it, gate it behind config, let the existing registry mechanism handle enable/disable and (where applicable) parallel corroboration.

## What a new provider requires
1. **Confirm it actually fits the Protocol** the relevant registry already defines (e.g. `OcrEngineProvider`, `ExportProvider`, `GeoProvider`) — don't invent a parallel interface shape for "just this one provider," even if it feels like it needs one extra method. If it genuinely doesn't fit the existing Protocol, that's a design conversation before a PR, not a PR that quietly forks the interface.
2. **Graceful degradation** (`docs/PRINCIPLES.md` §4.4) — a missing dependency or unavailable provider degrades to "unavailable," never crashes the registry or the run.
3. **Swappable, not hardcoded** (`docs/PRINCIPLES.md` §1.3) — any external library/service this provider needs sits behind its own small adapter, not called directly from the provider's own logic in a way that makes swapping the underlying library later a rewrite instead of an edit.
4. **A config entry** — enabled/disabled, and any provider-specific settings, following the existing config-block shape for that registry.
5. **If it corroborates with existing providers** (an OCR engine, a Geo provider) — confirm it's been checked against real data for whether it actually adds corroboration value, not assumed useful by default (`docs/PRINCIPLES.md` §5's "reasoned, then measured" discipline).

## PR checklist
- [ ] Implements the existing Protocol for this registry — no parallel interface invented
- [ ] Degrades gracefully to "unavailable" if its dependency is missing/unreachable
- [ ] External library/service sits behind its own adapter
- [ ] **Forward-Compatibility Hygiene checked as ONE pass, not split apart** (`docs/PRINCIPLES.md` §3.3, §5): if this provider's own contract has any dict-typed field, it uses `FrozenDict`; the underlying library's Day-0/Python 3.15+ and free-threading support checked, not assumed
- [ ] **Backward-Carrying Capability checked** (`docs/PRINCIPLES.md` §1.9): if this provider is part of a scan/output-quality API (an OCR engine, a Geo provider, a Matching corroboration source) or Reconciliation itself, is it reachable from Reconciliation's own idle-time sweep against old receipts, not just the live pipeline? If not applicable, state why explicitly.
- [ ] **Backward-carrying capability check** (`docs/PRINCIPLES.md` §1.9): a new provider is exactly the shape this rule targets (a new OCR engine, a new geo provider, a new matching technique) — either wire it so Reconciliation can apply it retroactively to already-processed receipts, or explicitly state why not. Never silently skipped.
- [ ] Config entry added, following the existing block shape
- [ ] If corroborating with existing providers, real-data comparison included or explicitly flagged as still needed
- [ ] Unit test added under the relevant API's `tests/unit/` path
- [ ] If this provider is genuinely new-to-the-project technology (not just "another instance of a pattern already well-covered"), the relevant deep-dive document's own provider section is updated

## CI test: `check_new_provider.yml`
**What it checks**: for the specific registry being extended, confirms the new provider class actually implements every method the registry's own Protocol requires (a straightforward `issubclass`/structural check), confirms a config-gated enable/disable path exists for it, and confirms there's at least one unit test exercising both its success and its "dependency unavailable" failure path.
**Recommended use**: automatic on any PR touching a `providers/` or `engines/` directory under an existing API. This is the CI check you'll hit most often in this project given how common this addition category is — worth running locally (`pytest tests/ci/test_new_provider.py --registry=<name>`) before pushing, since it's fast and catches the most common mistake (forgetting the graceful-degradation path) early.
