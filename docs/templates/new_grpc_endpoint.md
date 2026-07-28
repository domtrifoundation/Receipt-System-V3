# Adding a New gRPC Endpoint / RPC

## When this applies
You're adding a new RPC to an existing API's `.proto` service definition, or adding a new field to an existing message. This is one of the more mechanically constrained addition categories in this project, since protobuf compatibility rules are largely non-negotiable once something has shipped.

## What a new endpoint requires
1. **Only add fields, never remove or renumber existing ones** (Migration API's own deep-dive, `v3-deepdive-23-migration-api.md` §5) — this is protobuf's own backward-compatible evolution rule, applied consistently across every `.proto` surface in this project. A field that's no longer needed gets marked deprecated in a comment, not deleted, and its field number is never reused.
2. **Match the existing conventions in that API's own `.proto`** — error fields as `string error_code`/`string error_detail` pairs (the "errors are data" convention, `docs/PRINCIPLES.md` §4.1), not a new ad hoc error shape; streaming (`stream` keyword) only where genuinely justified (a long-running or continuously-updating result), never used just because it seems more sophisticated than a unary call.
3. **Decide unary vs. streaming deliberately** — the project's own precedent (OCR's `Read` stays unary since a single call is fast; Execution Core's `GetRunStatus` streams because run progress is genuinely continuous) is a real design choice each time, not a default to copy without thinking about whether this specific endpoint's own shape actually needs it.
4. **A corresponding contract in `contracts.py`** matching the `.proto` message shape, with the same frozen-dataclass/`FrozenDict` discipline.

## PR checklist
- [ ] No existing field removed or renumbered
- [ ] New fields only, appended with the next available field number
- [ ] Error fields follow the existing `error_code`/`error_detail` string-pair convention
- [ ] Unary vs. streaming decision stated with reasoning, not defaulted
- [ ] Matching `contracts.py` type added/updated
- [ ] **Forward-Compatibility Hygiene**: if the new message includes a dict-typed field, the matching `contracts.py` type uses `FrozenDict`, not plain `dict`
- [ ] If this is a new RPC (not just a new field), the API's own deep-dive document's gRPC section is updated

## CI test: `check_grpc_compatibility.yml`
**What it checks**: runs `buf breaking` (or equivalent protobuf compatibility checker) against the previous release's `.proto` files, failing the build on any field removal, field renumbering, or field-type change that would break wire compatibility with an already-deployed client. This is the single most valuable CI check in this category, since a compatibility break here can silently corrupt data for a client running an older version against a newer server, not just fail loudly.
**Recommended use**: automatic on every PR touching any `.proto` file, no exceptions — this check should never be skippable via a label or override, given what a silent break here actually costs. If you genuinely need to make a breaking change, that's a new RPC/message version, not an edit to the existing one.
