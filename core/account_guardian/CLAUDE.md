# Account Guardian API

Account Guardian is the user-facing privacy and account security center — deliberately on the user's own side first, not the server owner's. It owns: device/session management, SSO provider changes, and data-subject-rights requests (export, deletion).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new — stated as such in `docs/apis/v3-plan-01-core-apis.md` #28 and confirmed against V2's source, which has no device management, account recovery, or data-subject-rights surface. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-06-account-guardian-api.md`](../../docs/apis/v3-deepdive-06-account-guardian-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own session/identity mechanics** — it consumes Auth & Tenancy's `SessionStore` and `User` primitives (this API's own companion deep-dive) rather than duplicating them.
- **own break-glass notification surfacing** — resolving file 01's own flagged open question here: that stays with Notifications API, which already owns dual-notifying the owner and affected client on a grant (Auth deep-dive §6.3, file 03's decision). Account Guardian's scope is self-service actions the *user* initiates; break-glass notification is something that happens *to* them passively, a different shape of concern that belongs with the API already built for passive delivery, not duplicated here just because both touch "the affected user."

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

"Password reset" never applied to this design — no local password exists anywhere. What this API owns is *account recovery*: regaining access when a user loses the authentication method they had, which is a harder, staff-mediated problem closer to a support escalation than a self-service flow. Deletion passes through a `BILLING_HOLD` stage before it can proceed.
