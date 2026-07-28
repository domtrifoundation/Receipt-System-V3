# Update/Deployment API

Update/Deployment owns **no-downtime releases** — named, multi-channel release directories, health-gated cutover, and (via Proving Grounds) automated dependency-update testing.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `git_info.py` only stamped the current commit into output for traceability — there was no update, release-directory, channel, or rollback mechanism of any kind. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-24-update-deployment-api.md`](../../docs/apis/v3-deepdive-24-update-deployment-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **launch or supervise processes, decide which release is active, or drive rollback** — that's Supervisor's own job entirely (its own dedicated deep-dive, `v3-deepdive-38-supervisor.md`), a structurally separate process living outside every release clone, specifically so the thing deciding "should this release swap happen" is never the release being swapped in. This API's own job stops at *producing* a cloned, ready release directory — what happens to it after that is Supervisor's call, not this API's.
- **validate self-hosted license keys itself** — Keymaster (§4) is a genuinely separate, closed external system; this API only calls out to it before a clone attempt.
- **decide rollout health criteria** — Health API's own status/diagnostic layer (its deep-dive) is what actually gates cutover; this API consumes that signal, doesn't define what "healthy" means.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Every update is a fresh `git clone` into a new named directory — never a pull, never in-place mutation. This API's job stops at producing a ready release directory; deciding whether to activate it is Supervisor's, deliberately, so the thing choosing to swap a release is never the release being swapped in. Inference is the one API that never multiplies per channel.
