# Contributing to DOMTRI / Resibo (V3)

Thanks for looking at this before opening a PR — a few minutes here saves a round-trip of review comments later.

This file is the **entry point**, not the full reference. It tells you what you need to know to make a first contribution correctly. For the complete set of design principles this project holds itself to, see **[`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)**. For release process, versioning, and dependency-lifecycle detail, see **[`docs/MAINTENANCE.md`](docs/MAINTENANCE.md)**.

---

## Adding something? Use the right template.

Before opening a PR that adds anything, check whether it fits one of these categories — each has its own PR template (auto-suggested by GitHub when you open a PR), a full explanation doc, and its own CI check:

| Adding... | PR template | Full guide |
|---|---|---|
| A new Core API | `new_core_api` | [`docs/templates/new_core_api.md`](docs/templates/new_core_api.md) |
| A new sub-API/sub-package | `new_sub_api` | [`docs/templates/new_sub_api.md`](docs/templates/new_sub_api.md) |
| An OCR engine, export provider, or any other Provider Registry entry | `new_provider` | [`docs/templates/new_provider.md`](docs/templates/new_provider.md) |
| An external library or service | `new_dependency` | [`docs/templates/new_dependency.md`](docs/templates/new_dependency.md) |
| A gRPC endpoint or field | `new_grpc_endpoint` | [`docs/templates/new_grpc_endpoint.md`](docs/templates/new_grpc_endpoint.md) |
| A menu item or TUI screen | `new_menu_item` | [`docs/templates/new_menu_item.md`](docs/templates/new_menu_item.md) |
| A config key | `new_config_key` | [`docs/templates/new_config_key.md`](docs/templates/new_config_key.md) |
| A new taxonomy/typed data category | `new_taxonomy_type` | [`docs/templates/new_taxonomy_type.md`](docs/templates/new_taxonomy_type.md) — **read this before creating a table** |

Most additions to this project are the "Provider Registry entry" category — check that one first if you're unsure. For anything genuinely outside these eight, open a PR with a plain description and flag it in review as not fitting an existing category — that's useful signal that a ninth template might be needed.

See [`docs/testing/TOOLKIT.md`](docs/testing/TOOLKIT.md) for the broader set of optional tools (bench suite, profiling, fuzzing, load testing) beyond the mandatory per-category CI checks.

---

## Before you write any code

**If you're touching anything related to V2** (the previous generation of this project): V2 is analyzed for exactly one reason — to identify what broke, why, and what V3 must independently design around. **V2 is never a source of code to port, patterns to adopt, data to reuse, or "good practices" to carry forward.** Every V3 design decision — down to individual thresholds and config values — is derived independently on its own merits, even where a V2 number happens to exist. If you find yourself copying a value or a technique from V2 "because it was already there," stop — that's exactly the failure mode this rule exists to prevent. See `docs/PRINCIPLES.md`'s own section on this for the full reasoning.

**If you're adding a new schema, taxonomy, learned-data type, or SQLite table for typed/learned data**: this always goes through Architect API's registry, no exceptions. This rule exists because the same "extensible typed thing" pattern was independently reinvented five separate times before Architect API was created to consolidate it. If your change needs a new type of structured, evolvable data, that's an Architect registry entry, not a new table somewhere else.

**If you're adding a dependency on an external service or library**: it goes behind a small internal adapter your code calls, never hardcoded into call sites. This is standing, non-negotiable — see `docs/PRINCIPLES.md`'s modularity section.

---

## Coding standards, summarized (full detail in `docs/PRINCIPLES.md`)

- **Package-per-API, not file-per-API.** Every core API is its own subpackage, split internally by responsibility (`contracts.py`, `service.py`, one file per distinct concern). Soft cap ~300–400 lines per file; a CI check warns past the soft cap and fails past the hard ceiling.
- **Immutable contracts at every API boundary.** `@dataclass(frozen=True)` for every request/response/result type; any `dict`-typed field on one of these uses `FrozenDict`, not plain `dict` (see `docs/PRINCIPLES.md` for the version-gated shim). A frozen dataclass with a plain `dict` field is only shallowly immutable — this is a real, checked requirement, not a style preference.
- **Errors are data at API boundaries, not exceptions** — a result object with an `.error` field, populated and returned, never raised across a gRPC boundary. (The one deliberate exception: Auth & Tenancy's session/role failures, where failing loudly and stopping is the correct behavior — see that API's own deep-dive for why.)
- **No hardcoded TUI.** Any screen that's fundamentally "a list of labeled actions" is expressed as declarative menu data and rendered through the one generic `MenuScreen` — never a bespoke screen class, except the small, explicitly enumerated set of genuinely stateful screens.
- **Day-0 dependency support is an ongoing discipline, not a policy statement.** New Python and dependency releases (stable *and* pre-release) get tracked continuously via Telemetrees' Dependencies Warden, not reacted to after the fact. See `docs/PRINCIPLES.md` for the full Forward-Compatibility Pattern this implies for any version-sensitive code you write.

## Testing requirements

- New code needs unit tests mirroring the package-per-API layout (`tests/unit/core/<api>/`).
- Anything touching a real pipeline stage (OCR, Preprocessing, Inference) needs a bench-suite entry — real pipeline, never mocked, per-test process isolation so a native crash doesn't take the whole bench run down.
- A new menu item is automatically covered by the interface walker (it reads the live menu data) — you don't need to write that test yourself, but don't bypass the menu-data pattern in a way that makes your screen invisible to it either.

## Versioning: every commit ticks a version — this is not optional

This is a standing practice, enforced by review, not something to remember when convenient.
The full scheme lives in [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) §1; what you actually
have to *do* is here.

**Two numbers, and they move together.**

1. **The program version** — `PROGRAM_VERSION` in [`common/version.py`](common/version.py).
   **Every commit ticks its `pp`.** Including a commit that only fixes a typo or reworks a
   comment. There is no such thing as a commit too small to tick it, because the number's
   job is to identify a build, and a process-only commit still produces a different build.
2. **Each touched API's own version** — the value under `## Current API version` in that
   API's own `CLAUDE.md`. **A commit that changes a given API's own behaviour ticks that
   API's `pp` too, in the same commit as the behaviour change**, never in a follow-up.

A commit touching three APIs ticks the program version once and each of those three APIs'
own lines once each. A commit touching no API's behaviour ticks only the program version.

**Before you consider an API-touching commit finished, open that API's `CLAUDE.md` and
confirm the line actually changed.** This check exists because "I'll tick it at the end" is
how the number silently stops meaning anything — and a version that's stale is worse than
no version, since Health API's heartbeat, Watchdog's per-instance version reporting, and
the TUI's fleet screen all report it as fact.

**Why two lines per `CLAUDE.md`, not one.** Each API's `CLAUDE.md` carries both
`## API version at x03.00.00 Zircon` (the *target* — where that API lands when Zircon ships,
with the `MM` lineage determined against real V1/V2 source) and `## Current API version`
(the *running* counter described above). A target and a running counter genuinely cannot be
the same line, and collapsing them loses one or the other. The `MM` lineage reasoning under
the target heading is settled and derived from actual source inspection — don't re-derive it.

**A skipped version tick is an incomplete unit of work**, the same standing as a skipped
`nox -s forward_compat` checkpoint (`docs/MAINTENANCE.md` §8.3).

## Pull requests

- **Max 99 commits per PR** — this isn't arbitrary: it's what keeps the API version scheme's `pp` segment safely at 2 digits, and a PR that large is already a reviewability problem independent of versioning. Split it.
- PRs get the same review treatment whether they touch code or `docs/` — documentation changes aren't exempt from review.
- If your change affects a documented cross-cutting principle (something in `docs/PRINCIPLES.md`), update that file in the same PR, not as a follow-up someone else has to remember to do.

## Questions

Open an issue, or if it's a design question that might affect a principle documented in `docs/PRINCIPLES.md`, say so explicitly in the issue — it helps route it to the right kind of review.
