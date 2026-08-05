# DOMTRI / Resibo V3 — Documentation

This is the entry point for this repository's documentation. Everything here is versioned alongside the code (not a wiki) specifically so it's available the moment anyone — human or an LLM-assisted session — clones the repo, and so documentation changes go through the same PR review as code.

## Start here

- **[`../CONTRIBUTING.md`](../CONTRIBUTING.md)** — if you're about to open a PR, read this first.
- **[`PRINCIPLES.md`](PRINCIPLES.md)** — every cross-cutting design rule this project holds itself to (modularity, immutability, maintainability, transparency/safety, concurrency discipline), compiled in one place.
- **[`PROCESS_TOPOLOGY.md`](PROCESS_TOPOLOGY.md)** — the concrete map of which API runs in which process: the core service cluster (32 independent processes), Interface/Gateway as detachable clients, the webapp's actual runtime location, and Inference API's isolated generation workers.
- **[`VENV_AND_IMPORTS.md`](VENV_AND_IMPORTS.md)** — how each service's own venv is created and what goes in it, and how first-party code resolves inside one. The mechanism behind `PROCESS_TOPOLOGY.md`'s "each its own venv" claim, which that document asserts but does not describe.
- **[`MAINTENANCE.md`](MAINTENANCE.md)** — versioning scheme, channel/release management, dependency lifecycle, developer-mode setup instructions, decisions worth not re-litigating, and the real repo-settings action needed to make PR checklists actually enforced rather than advisory.
- **[`MAKING_README.md`](MAKING_README.md)** — instructions for writing the real, eventual user-facing `README.md` once real code exists to describe (not from this planning corpus).
- **[`SELF_HOSTED_NOMINATIM.md`](SELF_HOSTED_NOMINATIM.md)** — operational setup guide for a self-hosted Nominatim geocoding instance, one of Geo/Address API's own optional Provider Registry entries (`v3-deepdive-16-geo-address-api.md` §3). Not required for a normal install; linked from this doc rather than duplicated in the TUI itself.
- **`LEGAL_REVIEW_NEEDED.md`** — **deliberately not in this repository.** A formal legal memorandum (RA 10173, NPC Circular No. 2022-04, RA 11937, real penalty figures and case precedent), addressed to DOMTRI's Board and General Counsel. It is a genuine compliance document discussing real penalty exposure and unresolved legal risk, not an engineering task list — and this repository is public. `WIKI_MIGRATION_PLAN.md` §3 recommended keeping it in a private location once the repo's public/private status was settled; that was resolved in Phase 1 by removing it here and holding it privately. This entry is the stub that records where it went, so its absence reads as a decision rather than an oversight. Ask the repository owner if you need it.
- **[`SETUP_WIZARD_SCRIPT.md`](SETUP_WIZARD_SCRIPT.md)** — the complete, word-for-word first-run wizard script in plain language, branched by use case (personal / company / public). The user-facing counterpart to `v3-deepdive-11-setup-api.md` §7's own technical mechanism description.
- **[`REVIEW_COMMENT_FORMAT.md`](REVIEW_COMMENT_FORMAT.md)** — the format for DOMTRI's own audit comments, written as separate reviewer files rather than edits to the corpus itself. Follow this precisely — it's what makes comments reliably parseable when sent back.
- **[`CLAUDE_MD_GUIDE.md`](CLAUDE_MD_GUIDE.md)** — conventions for what goes in a `CLAUDE.md` at each level of the real repo once code exists (root, each Core API folder, each sub-API folder). A guide, not a template to copy blindly.
- **[`WIKI_MIGRATION_PLAN.md`](WIKI_MIGRATION_PLAN.md)** — the policy for what moves to GitHub Wiki vs. stays in-repo, plus an honest current-state assessment (most outward-facing content doesn't exist yet).
- **[`PHASE_1_KICKOFF.md`](PHASE_1_KICKOFF.md)** — hand this directly to the local Claude Code session that does repo hygiene, documentation setup, folder structure, every `CLAUDE.md`, and a real working implementation of the Agent Control API so it's ready for Phase 2 to use from the start.
- **[`PHASE_1_COMPLETE.md`](PHASE_1_COMPLETE.md)** — the Phase 1 session's own handoff record: what was created, what was flagged or deliberately skipped, the real V1/V2 lineage findings behind each API's version, and confirmation that branch protection and the Agent Control round trip both genuinely work. Read this before `PHASE_2_KICKOFF.md`.
- **[`PHASE_2_STATE.md`](PHASE_2_STATE.md)** — live state of the in-progress Phase 2 work: what is actually done, the two versioning decisions currently blocked on the repo owner, where the real receipt fixtures already are, and what the next session should do first. Read this before `PHASE_2_KICKOFF.md` if picking the work back up.
- **[`PHASE_2_KICKOFF.md`](PHASE_2_KICKOFF.md)** — the session that implements the full application. Also local, for real OCR/Preprocessing/Inference hardware access — includes a real checklist for confirming it's safe to move to remote sessions once x03.00.00 ships.
- **[`DAY_ZERO_COMPATIBILITY_PROMISE.md`](DAY_ZERO_COMPATIBILITY_PROMISE.md)** — the complete, verified inventory of every tracked forward-looking capability across the corpus (PEP 734, PEP 810, PEP 799/Tachyon, per-dependency free-threading status, model/dataset currency). Source material for the eventual README/Wiki, not itself finished public-facing copy.
- **[`PRE_STABLE_BENCH_VALIDATION.md`](PRE_STABLE_BENCH_VALIDATION.md)** — every reasoned-but-not-measured default across the corpus, required before tagging x03.00.00 Stable/LTSC. States plainly, up front: real receipt scans required for the OCR/Preprocessing/Inference/Matching items, never synthetic substitutes.

## Adding something to the project

- **[`templates/`](templates/)** — one explanation document per addition category (new Core API, new sub-API, new Provider Registry entry, new dependency, new gRPC endpoint, new menu item, new config key, new taxonomy type), each paired with a PR template under `.github/PULL_REQUEST_TEMPLATE/` and its own CI check. Start here before adding anything.
- **[`testing/TOOLKIT.md`](testing/TOOLKIT.md)** — the broader set of optional development tools (bench suite, profiling, fuzzing, load testing) beyond the mandatory per-category CI checks.

## API-level design documents

Every core API has its own full deep-dive document — package layout, data contracts, dependencies, hardware/concurrency, gRPC surface, config, testing hooks, and open questions. Where a sub-component is substantial enough to warrant it (e.g. Persistence's Historian or Reimport, Health's Watchdog), it has its own document too, linked from its parent API's own file.

These live in [`apis/`](apis/) as `v3-deepdive-01-ocr-api.md` through `v3-deepdive-56-test-orchestration.md` — moved there from the flat planning-corpus layout in Phase 1, as this document previously flagged should happen once real development started. Every Core API and sub-API `CLAUDE.md` points at its own file there.

**These documents are temporary and will not ship.** The whole `apis/` corpus is removed before `x03.00.00` Zircon; the `CLAUDE.md` files are what survive it. See [`CLAUDE_MD_GUIDE.md`](CLAUDE_MD_GUIDE.md) §2.1 for the rewrite every `CLAUDE.md`'s "Full design" section requires before that removal.

## Planning history

The original 5-file planning corpus (`v3-plan-00-index.md` through `v3-plan-04-v2-audit-findings.md`) is the historical record of how this design was reached, including the V2 postmortem and the full audit trail of decisions. Worth reading once for context; `PRINCIPLES.md` and `MAINTENANCE.md` above are the distilled, currently-authoritative versions of what matters day to day.
