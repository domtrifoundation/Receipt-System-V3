# Adding a New External Dependency

## When this applies
You're adding a new Python package, a new external service integration, or a new system-level binary dependency (something installed outside pip, like Tesseract or ClamAV). This applies whether the dependency is brand new to the project or you're adding a *new use* of a dependency already present elsewhere.

## What a new dependency requires
1. **Behind an adapter, always** (`docs/PRINCIPLES.md` §1.3) — no direct `import somelibrary` calls scattered through business logic; one module owns the integration, everything else calls that module.
2. **A real reason it's the right choice**, stated in the PR description — this project's own deep-dives consistently include a "why this over the alternatives" paragraph for every dependency choice (e.g. why Authlib over a hand-rolled OAuth client, why Postmark over SendGrid). A one-line "it works" is not sufficient justification for a new dependency in this codebase.
3. **Registered with Telemetrees' Dependencies Warden** (`docs/MAINTENANCE.md` §3) — added to the tracked-dependency inventory with the right fact kinds (at minimum `release_version`; add `free_threading_support` if it's a C-extension-backed package, add `upstream_issue_status` if you're depending on a specific not-yet-resolved upstream issue).
4. **Checked against the Forward-Compatibility Pattern** (`docs/PRINCIPLES.md` §3.3) if it's at all version-sensitive — does it need an environment-marker-scoped install for certain Python versions? Does it have a free-threading story worth knowing about before it becomes a surprise? **This is one combined check, not three separate ones** — FrozenDict-for-any-dict-field, the concurrency classification, and Day-0/3.15+/Tachyon-py-spy support all get verified together, since checking one without the others is exactly the mistake this project has made repeatedly.
5. **If this dependency introduces a version-sensitive shim** (an older-Python fallback path that a newer Python version should eventually supersede, like the frozendict PyPI-package-vs-builtin split) — **register a check in Health API's capability drift registry** (`v3-deepdive-20-health-api.md` §4.1), not just the shim itself. A shim that gracefully degrades on old Python is also capable of silently staying on the fallback path forever on new Python if nothing ever re-checks which branch it's actually taking — this is the concrete mechanism that catches that.
6. **License-compatibility checked** — this project cites real licensing considerations throughout (Provider Registry entries dropped for licensing reasons exist in the actual corpus, e.g. Surya's GPL-3.0 licensing). State the license in the PR.

## PR checklist
- [ ] Behind its own adapter module — no scattered direct imports in business logic
- [ ] "Why this dependency" reasoning stated in the PR description, including alternatives considered
- [ ] Added to Telemetrees' tracked-dependency inventory (`docs/MAINTENANCE.md` §3) with the right fact kinds
- [ ] Environment-marker-scoped install if version-sensitive, per the Forward-Compatibility Pattern
- [ ] If this introduces a version-sensitive shim, a corresponding check registered in Health API's capability drift registry
- [ ] License checked and stated
- [ ] If it's a C-extension-backed package, free-threading support status checked and noted (even if the answer is "unknown as of this writing")

## CI test: `check_new_dependency.yml`
**What it checks**: diffs `pyproject.toml`/`requirements.txt` against the previous commit, and for any newly-added package, confirms (a) it appears in Telemetrees' tracked-dependency config block, and (b) grepping the diff for direct imports of the new package outside a single identifiable adapter module — flagging (not failing outright, since some genuinely small utility dependencies don't need a full adapter) if it's imported from more than one non-adapter location.
**Recommended use**: automatic on any PR that touches dependency manifests. The "imported from multiple places" flag is a soft warning, not a hard failure — use judgment (a genuinely tiny, stable utility like `python-dateutil` doesn't need the same adapter ceremony as an OCR engine binding does), but the CI output should prompt you to actually make that judgment call explicitly rather than never noticing the dependency spread.
