---
applyTo:
  - "**/*.proto"
---
# gRPC contract review focus

- **No field renumbering or removal** — a changed or reused field number on an existing message is a wire-compatibility break across every currently-running channel/version this project keeps active simultaneously (docs/PRINCIPLES.md §1.7). New fields should be appended with new numbers, never reusing a retired one.
- **New required fields on an existing message** are almost always wrong — a field required by a newer proto but absent from an older release's own generated code breaks that older release. New fields should default to optional/have a sensible zero-value fallback.
- Does the corresponding `contracts.py` type actually match this `.proto` definition, or has one drifted from the other?
