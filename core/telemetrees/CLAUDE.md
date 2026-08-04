# Telemetrees API

Telemetrees owns **continuous dependency monitoring** via its Dependencies Warden sub-API — tracking every registered dependency's release activity (stable *and* pre-release), surfacing changelogs and compatibility-status changes to developers automatically.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no outbound diagnostic reporting of any kind — no issue filing, no dependency monitoring, no dedup. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.04`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-28-telemetrees-api.md`](../../docs/apis/v3-deepdive-28-telemetrees-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide whether to adopt a new version** — that's Proving Grounds' job (Update deep-dive §6): Dependencies Warden surfaces "this exists now," Proving Grounds actually tests it against real bench workloads before promotion to any channel.
- **track every dependency uniformly** — different dependencies need different tracked facts (a plain version bump vs. a free-threading-support flag vs. an upstream GitHub issue's open/closed status), a real design requirement worked through in §3, not assumed to be one-size-fits-all.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Deduplication is load-bearing, not polish: the same underlying problem recurring must group into one issue that gets updated, never a flood of duplicates — fingerprint the signal, not the occurrence. Authenticate with a GitHub App, not a personal access token: org-owned, scoped to `issues` and nothing else, short-lived auto-rotating tokens. Any diagnostic data leaving an install is scrubbed of receipt and financial content first, and non-DOMTRI installs must opt in explicitly.

**`telemetrees.proto`/`service.py` did not exist at all until this session** — the deep-dive's
own §6 sketches a real two-RPC contract (`GetTrackedDependencies`, `GetChangelog`), but nothing
had compiled it. `TelemetreesServicer` wires the real `TrackedDependencyRegistry` (seeded from
the real, complete `INVENTORY`, confirmed live at 14 tracked dependencies) and the real
`docs/CHANGELOG.md` file to it. `GetChangelog` returns the file's own raw Markdown rather than a
structured entry list — this API keeps no separate structured store of past entries;
`ChangelogWriter` is the single writer and the file itself is the single source of truth.
Confirmed live: a real repo with no changelog yet returns empty markdown with no error (the
honest, correct state for this repository today, not a bug), and a real file's content is read
back verbatim once one exists.

**Real, live-tested `RecordFiledIssue`/`ListFiledIssues` RPCs and a new `diagnostics/`
sub-package, answering a direct user question: "we should have honest stats about when
it reports anything to GitHub — issue link, status, whether a fix PR is already
developing."** `diagnostics/ledger.py`'s `FiledIssueLedger` is a real, persisted,
append-only record of every issue this install has ever filed (deduped by `fingerprint`,
never overwriting an existing entry). `diagnostics/github_status_client.py`'s
`GitHubIssueStatusClient` is a real, unauthenticated, read-only GitHub REST client —
live-tested against `python/cpython#1` (a stable public fixture, not this project's own
issue tracker, which is currently empty) confirming both the real open/closed state lookup
and the real cross-referenced-PR lookup via GitHub's own Timeline API. `ListFiledIssues`
fetches live status per ledger entry on every call rather than caching it, so `checked_at`
is always genuinely current.

**Stated as plainly as `docs/PRINCIPLES.md`'s "never plausible-looking data" demands**:
this is the real *ledger and status-reporting* half of "Telemetrees compiles diagnosed
errors into tracked issues." The *detector* half — deciding a diagnosed error is worth
filing, deduplicating by fingerprint, and calling GitHub's App-authenticated
issue-creation API to actually open one — does not exist anywhere in this codebase yet.
`RecordFiledIssue` is the real seam that future component calls once built; nothing here
fabricates a filing that never happened. The TUI's own `custom_screens/
filed_issues_screen.py` (`services/interface/CLAUDE.md`) is real and tested against this
real backend, and correctly renders "no issues have been filed by this install yet" today
— the honest, correct state, not a bug.

**Real `GetOptIn`/`SetOptIn` RPCs, added for the TUI's own Settings screen**
(`telemetrees_opt_in`). Backed by `common/local_config_store.LocalConfigStore` at
`<install_root>/telemetrees/config.json`, defaulting to `False` — data only ever leaves
the install once explicitly turned on, matching this API's own stated opt-in-by-default
posture. `TelemetreesServicer` takes an optional `install_root`, resolved in `__main__`
via `common/install_paths.resolve_install_root()` (new shared utility — see `services/
setup/CLAUDE.md` for why no service had a way to compute this before this pass).
