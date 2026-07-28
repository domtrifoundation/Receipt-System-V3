---
applyTo:
  - "pyproject.toml"
  - "requirements*.txt"
---
# New dependency review focus

- **Forward-Compatibility Pattern checked** (docs/PRINCIPLES.md §3.3): does this dependency need an environment-marker-scoped install for certain Python versions? Does it have a known free-threading story worth flagging?
- **Telemetrees tracking entry** — does a new native/C-extension dependency have a corresponding tracked-dependency entry, or does the PR description explain why one isn't needed?
- Is this dependency actually necessary, or does an existing already-tracked dependency already cover the same need? Flag likely duplication (e.g. a second HTTP client library, a second fuzzy-matching library).
