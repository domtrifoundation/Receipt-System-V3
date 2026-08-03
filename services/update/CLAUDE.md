# Update/Deployment API

Update/Deployment owns **no-downtime releases** — named, multi-channel release directories, health-gated cutover, and (via Proving Grounds) automated dependency-update testing.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `git_info.py` only stamped the current commit into output for traceability — there was no update, release-directory, channel, or rollback mechanism of any kind. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

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

**Partially implemented, scoped to the release/installer pipeline specifically.** Real: `contracts.py` (`ChannelName`, Keymaster's client-side contracts only — `ReleaseDirectory` and the rest of §2's sketch are not built), `keymaster_client.py`, `requirements.txt`. Still 0-byte: `release_manager.py`, `errors.py`, `metrics.py`, all of `proving_grounds/`.

**`keymaster_client.py` is a client for a system that does not live in this repo, and never will.** `v3-plan-02-architecture.md` states the reason directly: license-validation logic that shipped inside a self-hosted clone would sit on the exact machine it is meant to check, "fully readable and patchable by the person it is meant to validate — not a real check." Keymaster's own server lives in a separate, DOMTRI-only repo. This module is a plain outbound HTTPS call, nothing more — never add validation logic here, that would silently reintroduce the exact flaw the architecture doc corrected.

**The wire contract (`POST {base_url}/v1/clone-tokens`) is this project's own design**, not specified anywhere else in the corpus — Keymaster's own repo is the real implementation of the server side. If that contract ever changes, `installer/common.sh`'s own raw `curl` call (the pre-Python bootstrap script's necessary duplicate of this same exchange, since it runs before this module is even on disk) has to change with it — the two are not wired together and cannot be, but they must never drift, since they speak to the same endpoint.

**§4's "never leak why a key failed" is a constraint on the wire, not on this client's own local error handling.** `KeymasterRejectionReason` distinguishes `NO_KEY_CONFIGURED`/`NETWORK_UNREACHABLE`/`MALFORMED_RESPONSE` from a single generic `SERVER_REJECTED` bucket — the server-side genericness is honored (every non-200 response collapses to one reason, its body never inspected), while an operator's own logs still get to tell "the network was down" from "the key was rejected," since that distinction is private to this client's own observation of its own request.
