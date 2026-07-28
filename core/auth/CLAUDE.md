# Auth & Tenancy API

Auth & Tenancy owns **session/identity mechanics**: SSO/OIDC authentication, issuing and validating the server-side session that backs every authenticated request, the owner/staff/client role model, break-glass access grants, and the `tenancy_mode` (single/multi) config flag that makes this whole API a no-op in self-hosted single-user mode.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 was a single-user local program with no identity, session, or role concept at all — its only OAuth was a Google Drive service credential, which authenticates the program to Drive, not a user to the program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-05-auth-tenancy-api.md`](../../docs/apis/v3-deepdive-05-auth-tenancy-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the user-facing self-service surface** — device management, password reset, SSO provider changes all live in Account Guardian API instead (this API's own companion deep-dive), which consumes Auth's primitives rather than duplicating them.
- **own authorization *content*** — this API answers "who is this request from and what role do they hold," not "is this specific action allowed" for any given domain API's own business logic. A role claim riding on a session is a fact Auth publishes; what a given API does with that fact (Gateway enforcing owner/staff-only routes, Persistence enforcing folder isolation) is each consumer's own job.
- **own break-glass's *notification* or *approval workflow* UI** — Auth issues and tracks the grant itself (time-boxed, reason-tagged, logged); Notifications API surfaces it to the owner and affected client, Review/Flagging or a staff-facing screen is where a request actually gets approved. Auth is the ledger of grants, not the request form.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This is the one deliberate exception to errors-as-data (`docs/PRINCIPLES.md` §4.1): session/role failures raise and stop, because a caller silently ignoring an auth failure is worse than one ignoring a business error. **No local password authentication exists anywhere in this design, under any circumstance** — four passwordless primary methods plus composable 2FA. A PR adding a password field is wrong before it is reviewed.
