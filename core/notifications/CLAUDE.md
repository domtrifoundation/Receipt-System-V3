# Notifications/Inbox API

Notifications/Inbox owns delivering a signal to a user (owner, staff, or client) that something happened — currently in-app only, with outbound channels (email, SMS) as this deep-dive's actual design task per file 01's own framing.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `events.py` is an in-process ring buffer the dashboard renders live — not a durable, per-user, addressable inbox, and it disappears with the process. V2's uses of the word "inbox" refer to the receipts input folder, not notifications. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together. This tick is the first real implementation: `contracts.py`
through `service.py`, the Provider Registry channels, and the generated gRPC surface, all
landing in one pass.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-09-notifications-inbox-api.md`](../../docs/apis/v3-deepdive-09-notifications-inbox-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what's worth notifying about** — every consumer (Auth's break-glass, Execution Core's run completion, Content Security's rejection, Account Guardian's export/deletion completion, **Review/Flagging's new-flag creation** — `v3-deepdive-25-review-flagging-api.md` §5, a real connection that had only ever been stated from that document's own side until a full pipeline walkthrough found it never actually listed here) decides *when* to notify; this API decides *how* the notification actually reaches the person.
- **own the underlying event** — a notification references what happened (a break-glass grant, a completed run), it doesn't duplicate that event's own record. Auth's `BreakGlassGrant`, Execution Core's run record, and so on remain the source of truth; a `Notification` carries a reference, not a copy.
- **define its own notification-category taxonomy** — `Notification.category` stays a plain, unvalidated string on purpose (`contracts.py`'s own docstring). A category is exactly the kind of extensible typed thing `docs/PRINCIPLES.md` §3.4 reserves for Architect API; `core/architect/contracts.py`'s `DefinitionKind` enum has no `NOTIFICATION_CATEGORY` member yet, and adding one is Architect's own move, not this package's. `CategoryValidator` (`contracts.py`) is the seam a real Architect-registry client plugs into later; `inbox.py`'s own `PermissiveCategoryValidator` is the honest default until then.
- **resolve sessions or evaluate break-glass grants itself** — `service.py`'s `SessionResolver`/`AuthSessionResolver` and `inbox.py`'s `CrossUserAccessChecker`/`AuthBreakGlassChecker` are adapter seams onto Auth & Tenancy, never a second identity or grant mechanism invented here (`docs/PRINCIPLES.md` §1.3). The default resolver denies everything (fail closed, §4.2) until a real Auth client is wired in.
- **own where the per-user notifications table ultimately lives long-term** — see this file's own "files not in the deep-dive's layout" section below on `db.py`: the deep-dive's own §3 target is a table inside Persistence's `canonical.sqlite`, and that migration is Persistence's own move to make once its schema grows a `notifications` table, not something reached across and done from here.

## Forward-Compatibility Pattern applicability

**Partially, and the specifics matter more than a blanket yes/no here.** None of `contracts.py`'s
own dataclasses carry a dict-typed field today — `Notification.reference` is a plain opaque
string, and every other field is a string/bool/enum/tuple/timestamp — so there is no `FrozenDict`
usage inside `contracts.py` itself, unlike `core/logs/contracts.py` or `core/health/contracts.py`.
The `FrozenDict` usage that *does* exist in this package lives in `errors.py`
(`ERROR_CODES`, `ERROR_SUMMARIES` — module-level lookup tables per `docs/PRINCIPLES.md` §2.1.1).
Any `isinstance` check against those tables must test `collections.abc.Mapping`, never `dict` —
the 3.15 builtin is not a `dict` subclass — and `tests/unit/core/notifications/test_contracts.py`
asserts exactly that, `forward_compat`-marked, the same way `core/logs/test_contracts.py` and
`core/health/test_contracts.py` each assert it for their own module-level tables. If a future
change gives any `contracts.py` dataclass a dict-typed field, it must be `FrozenDict` from the
first commit, not a plain `dict` added under time pressure — this line is what gets updated the
same PR that makes it true (`docs/CLAUDE_MD_GUIDE.md` §6).

## Real gotchas specific to this folder

A `Notification` carries a *reference* to the underlying event, never a copy of it. Auth's `BreakGlassGrant` and Execution Core's run record stay the source of truth — duplicating their content here creates a second thing that can drift.

**Unlike Logs' own `requesting_user_id`, which arrives as a wire field, this API resolves the
caller's identity from the session before any query is ever built.** `notifications.proto` has
no `requesting_user_id` field anywhere, and `QueryInboxRequest`/`MarkReadRequest`/
`GetPreferencesRequest`/`SetPreferenceRequest` carry no caller-asserted identity at all —
`service.py`'s `_session_resolver(context)` is the only source of who is calling. This is
deliberately a stronger posture than `core/logs/service.py`'s own `to_query`, per this task's
own explicit requirement to never trust a caller-asserted user id.

**`Notify` is never gated on the caller's own session.** It is a system-to-system call from
another Core API naming its own recipient (deep-dive §1's own list of callers), not a read of
anyone's own data — gating it the same way `QueryInbox` is gated would block Auth's break-glass
alerts and Execution Core's own run-completion notifications from ever being delivered.

**§7/§8's "three attempts with backoff over the following day" is implemented as a policy, not
a literal day-spanning wait.** `dispatch.py`'s own module docstring explains why: actually
spreading three attempts across a day is Background Workers' idle-time scheduling, and
Background Workers does not exist as an implemented Core API in this codebase yet. What is
built and fully tested today is the *count* (exactly three attempts) and the *escalation*
(surfaced once every attempt is spent) — `backoff_seconds` is an injectable seam for whatever
real schedule eventually drives the delay between attempts.

**Escalation to staff is a metrics counter today, not a real notification to an owner.**
`dispatch.MetricsOnlyEscalator` is the honest current behaviour, not a shortcut: raising a
`notification_delivery_failed` notification for "the owner" needs an `OwnerResolver`-shaped seam
onto Auth's `Role`/`User` model that does not exist yet. The design supports a real
implementation cleanly (`Notifier.notify` called recursively for the escalation itself) once
that resolver exists; inventing one now would mean inventing a recipient, which is worse than
the current, explicit gap.

## Files not in the deep-dive's own §2 package layout, added with reasons

- **`db.py`** — the deep-dive's own §3 target is a `notifications` table *inside* each user's
  existing Persistence `canonical.sqlite`, with "no separate top-level database needed here."
  That target could not be built as specified: `core/persistence/db/schema.py` (Wave 1, already
  implemented) defines no `notifications` table, and this task's own write boundary is
  `core/notifications/` only — adding a table to Persistence's own schema is that API's move to
  make, the identical situation `core/audit/CLAUDE.md` already documents for Agent Control's own
  `agent_audit` table. So `db.py` opens a **sibling** SQLite file per user, at the identical
  `RESIBO_TOP_LEVEL`/`users/<user_id>/` path convention `core/persistence/db/connection.py`,
  `core/audit/db.py`, and `core/logs/paths.py` each already apply independently (never imported
  from one another, since `docs/PRINCIPLES.md` §1.1 confines what one package imports from
  another to its `contracts.py`). Migrating these two tables into Persistence's own database
  later is a data migration, not an architectural one — the per-user isolation boundary, the
  row shapes, and the path convention are already identical.
- **`dispatch.py`** — the deep-dive's own layout names `inbox.py` (in-app storage) and
  `channels/` (the outbound registry) as separate concerns, but something has to call both in
  the right order and hold §8's own resolved delivery-failure policy (in-app write always
  happens first and unconditionally; a failing channel gets exactly three bounded attempts,
  then escalates). Putting that in `service.py` would make the thin gRPC translation layer also
  own a retry policy, exactly what `core/logs/service.py`'s and `core/health/service.py`'s own
  docstrings say never to do. One small orchestrator module is the shape `core/audit/writer.py`
  already uses for the identical kind of "call the write path, then fan out to a registry"
  composition.
- **`notifications.proto` + `generated/`** — the deep-dive's own §2 layout predates naming where
  the `.proto` lives, the same gap `core/health/CLAUDE.md` records for `health.proto`. Generated
  with `python3 -m grpc_tools.protoc --python_out … --grpc_python_out … --pyi_out …`; the
  relative-import fix (`from . import notifications_pb2 as notifications__pb2`) is re-applied by
  hand in `notifications_pb2_grpc.py` after every regeneration, and nothing else in the generated
  files is ever hand-edited. `service.py` imports them lazily, exactly as `core/logs/service.py`
  and `core/health/service.py` do, so this package stays importable — and its tests meaningful —
  on an interpreter with no `grpcio` wheel yet.
