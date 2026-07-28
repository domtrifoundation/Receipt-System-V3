# Telemetrees API

Telemetrees owns **continuous dependency monitoring** via its Dependencies Warden sub-API — tracking every registered dependency's release activity (stable *and* pre-release), surfacing changelogs and compatibility-status changes to developers automatically.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no outbound diagnostic reporting of any kind — no issue filing, no dependency monitoring, no dedup. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

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
