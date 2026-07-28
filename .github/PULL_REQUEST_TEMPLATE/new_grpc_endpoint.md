## Summary
<!-- What RPC/field, on which API -->

## Full guide
See [`docs/templates/new_grpc_endpoint.md`](../../docs/templates/new_grpc_endpoint.md) for the full explanation and reasoning behind this checklist.

## Checklist
- [ ] No existing field removed or renumbered
- [ ] New fields only, appended with the next available field number
- [ ] Error fields follow the existing `error_code`/`error_detail` string-pair convention
- [ ] Unary vs. streaming decision stated with reasoning
- [ ] Matching `contracts.py` type added/updated
- [ ] **Forward-Compatibility Hygiene**: dict-typed fields on the new message use `FrozenDict`
- [ ] `buf breaking` (or equivalent) passes clean
- [ ] API's own deep-dive gRPC section updated if this is a new RPC
