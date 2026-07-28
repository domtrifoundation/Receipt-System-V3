---
applyTo:
  - "core/**"
  - "services/**"
---
# New Core API review focus

This PR touches a top-level Core API package. Check specifically:

- **Contracts are frozen dataclasses; any dict-typed field uses `FrozenDict`, never plain `dict`** (docs/PRINCIPLES.md §2.1). Flag any plain `dict` type hint on a cross-boundary contract field.
- **Concurrency bucket stated explicitly** somewhere in the PR description or a docstring — I/O-bound, CPU-bound, or hybrid. A new API with no stated classification is a real gap, not a formality (docs/PRINCIPLES.md §5).
- **Backward-Carrying Capability** (docs/PRINCIPLES.md §1.9): if this touches scan/output quality (OCR, Preprocessing, Matching, Inference, Geo/Address) or Reconciliation itself, confirm it's reachable from Reconciliation's own retroactive sweep — one shared function, not two implementations. Flag if this looks like a fresh copy of logic that already exists elsewhere in the live pipeline.
- **`contracts.py` is the only file other packages import from.** Flag any cross-package import reaching into a module other than `contracts.py`.
- Does the PR description actually address the checklist in `docs/templates/new_core_api.md`, or does it look like the checklist was copy-pasted with boxes checked but no real reasoning behind them?
