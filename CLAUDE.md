# DOMTRI / Resibo V3

A receipt-processing system: it takes receipt images in from several channels, reads them with
multiple OCR engines in parallel, corroborates the readings against each other and against a
learned vendor directory, and writes the result into a per-user canonical store that Philippine
BIR-relevant exports are generated from. It runs as a cluster of independent processes — every
Core API is its own OS process with its own venv, tied together entirely by internal gRPC — with
the TUI and the web Gateway as genuinely detachable clients of that cluster. It is deployed
either as DOMTRI's hosted multi-tenant service or as a self-hosted install, from the same code.

This is the third generation. The first was a Claude skill driving Excel; the second was a
single-process Python program whose failure modes are documented, not guessed at, in
`docs/apis/v3-plan-04-v2-audit-findings.md`. Most of the structure here exists because of
something specific that went wrong before.

## Where the real documentation lives

- **[`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)** — every cross-cutting rule this project holds
  itself to, and *why each one exists*. Read this before touching anything. If a change
  conflicts with something in it, the change is wrong until that document is deliberately
  edited in the same PR with reasoning attached.
- **[`docs/PROCESS_TOPOLOGY.md`](docs/PROCESS_TOPOLOGY.md)** — the authoritative map of what runs
  in which process. Several deep-dives say "the main process" as loose shorthand; there is no
  such thing, and this document is the correction.
- **[`docs/MAINTENANCE.md`](docs/MAINTENANCE.md)** — versioning, channels, dependency lifecycle,
  developer-mode setup, and the decisions worth not re-litigating.
- **[`docs/index.md`](docs/index.md)** — the full documentation entry point.
- **Each API's own folder has a `CLAUDE.md`** naming what it owns, what it explicitly does not,
  and where its full design lives. Start there rather than reading the corpus cold.

**The `docs/apis/` deep-dive corpus is temporary.** It is real, load-bearing material during
development and it will not be in the repo once `x03.00.00` Zircon ships. The `CLAUDE.md` files
are what survive that removal and become the ongoing development reference. Before the corpus is
deleted, every `CLAUDE.md`'s "Full design" section must be rewritten from "read the deep-dive"
into a self-contained summary plus a pointer to the real `contracts.py`/`service.py`
(`docs/CLAUDE_MD_GUIDE.md` §2.1). That is a required step, not polish — a `CLAUDE.md` still
pointing at a file that no longer exists is a broken reference in the one document future
sessions depend on most.

## Hard rules that apply everywhere in this repo

- **V2 is never a source of code, patterns, data, or "good practices."** It is analyzed only to
  identify what broke and what V3 must independently design around. Reaching for V2's
  implementation "because it's already there" is the exact failure this rule exists to prevent
  (`docs/PRINCIPLES.md` §0).
- **Package per API, not file per API.** Soft target ~300–400 lines per file, CI-enforced hard
  ceiling. `contracts.py` holds types and no logic, and is the only file other packages import
  from. This is not aesthetics: long files measurably degrade an LLM-assisted session's output,
  and this project's real development model depends on those sessions (§1.1).
- **Frozen contracts, and `FrozenDict` for dict-typed fields.** A frozen dataclass with a plain
  `dict` field is only shallowly immutable. Use `common/frozen_dict.py` — the one centralized
  shim — and remember the 3.15 builtin is *not* a `dict` subclass, so `isinstance(x, dict)`
  silently misses it; test `collections.abc.Mapping` (§2.1). Module-level constant lookup tables
  are `FrozenDict` too (§2.1.1).
- **Errors are data at API boundaries, not exceptions.** Return a result object with an `.error`
  field; never raise across a gRPC boundary. The single deliberate exception is Auth's
  session/role failures, where failing loudly is correct (§4.1).
- **Every pluggable capability is a Provider Registry, and more than one provider can run at
  once** where corroboration adds real value — not a single config value swapped one at a time
  (§1.2). Every external service and every external library sits behind one small internal
  adapter, never hardcoded into scattered call sites (§1.3).
- **Any new typed, learned, or schema data goes through Architect API. No exceptions.** No API
  defines its own taxonomy or spins up its own table for schema data, even for one narrow case.
  This same pattern was independently reinvented five times before Architect existed (§3.4).
- **Fail closed on security checks, degrade gracefully everywhere else.** A failed or timed-out
  content scan means unsafe, never a silent bypass (§4.2). A missing OCR engine means that
  engine is unavailable, never a failed run (§4.4).
- **Never silently override a genuine conflict — surface it to a human** (§4.3).
- **A real feature gets its own sub-API document, never a buried subsection.** The threshold is
  concrete and in §1.8 because "it seemed small at the time" is how this was already gotten
  wrong twice.
- **Anything the live pipeline can do, Reconciliation should be able to do to old data** — one
  reusable function with two orchestrators, never a second implementation for the historical
  case (§1.9).
- **The Forward-Compatibility Pattern (§3.3–3.3.1) applies everywhere in this repo**, not only in
  folders that obviously touch a version-sensitive dependency. Any `FrozenDict`-typed field, any
  assumption baked in about the GIL, anything touching `asyncio` behaviour that has shifted
  across Python versions — check it against that policy rather than assuming this folder is
  exempt because its own `CLAUDE.md` did not happen to mention it. Every folder's `CLAUDE.md`
  states its applicability explicitly, including when the answer is "not applicable," and that
  line gets updated in the same PR that makes it wrong.
- **Never put user data in this repository.** Per-user data lives in the top-level installation
  directory, a sibling of every release clone (§1.6, §2.4). The `config/`, `data/`, and `models/`
  directories here are empty scaffolding with their contents gitignored, because V2 committed
  real financial data into source history by defaulting its data paths inside the program's own
  directory.

## Before you commit

- **Pick the right template.** [`docs/templates/`](docs/templates/) has one explanation document
  per addition category — new Core API, new sub-API, new Provider Registry entry, new dependency,
  new gRPC endpoint, new menu item, new config key, new taxonomy type. Each pairs with a PR
  template in `.github/PULL_REQUEST_TEMPLATE/` and its own CI check. Read the explanation before
  filling in the checklist; the checklist is the summary, not the reasoning.
- **The checklist is enforced, not advisory.** `.github/workflows/pr_checklist_enforcement.yml`
  parses the PR body and fails CI on an unchecked box, or on either of the two highest-stakes
  items (Forward-Compatibility Hygiene, Backward-Carrying Capability) being checked with no real
  justification behind it. `main` is protected, that check is required, and administrators are
  deliberately included — an admin waiving their own project's hygiene rules "just this once" is
  precisely how the V2-era mistakes this project keeps correcting actually happened
  (`docs/MAINTENANCE.md` §7).
- **Update the docs in the same PR, not after.** `docs/PRINCIPLES.md` changes in the same PR as
  any change to a cross-cutting rule; a deep-dive's open question gets resolved in the PR that
  resolves it; and a folder's `CLAUDE.md` — especially its "does NOT own" list and its
  Forward-Compatibility line — gets updated in the PR that makes it stale (§6, and
  `docs/CLAUDE_MD_GUIDE.md` §6).
- **A PR may not exceed 99 commits.** A PR that large is unreviewable regardless, and this is
  also what keeps the version scheme's `pp` segment at two digits (§3.1).
- **Development setup is not `git clone`.** Cloning gets you the code but no working top-level
  directory, config, or database to run against. Download the release archive and run the
  *developer-mode* setup script (`docs/MAINTENANCE.md` §5).
