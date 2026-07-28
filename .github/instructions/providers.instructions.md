---
applyTo:
  - "**/providers/**"
  - "**/engines/**"
---
# New provider review focus

This PR adds or modifies a provider behind an existing Protocol (a Provider Registry entry — an OCR engine, a Geo/Address source, a backup target, an auth method, etc.).

- **Genuine `Protocol` conformance** — does the new provider actually implement every method the Protocol requires, with matching signatures, not a partial or duck-typed approximation?
- **Graceful degradation** — does this provider fail cleanly to "unavailable" if its own dependency (an API key, a binary, a network service) is missing, rather than raising an unhandled exception that could take down a shared code path?
- **Backward-Carrying Capability** (docs/PRINCIPLES.md §1.9): if this is a scan/output-quality provider, is it reachable from Reconciliation's own retroactive sweep against old receipts, not just the live pipeline?
- **No hardcoded assumption that this is the only provider** — check for any code elsewhere that assumes a single provider rather than iterating the enabled set.
- Real external library calls sit behind this provider's own adapter, not called directly from calling code elsewhere.
