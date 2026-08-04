# Groups

Groups owns letting an owner (or a designated group manager) organize users into teams whose receipts get automatically pooled for aggregate, labeled reporting — the real case this solves: a company self-hosting for its whole team, where employees each upload their own receipts but management wants one combined view across the team, labeled by who contributed what.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no multi-user model at all, so there was nothing to group. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.02`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-41-groups.md`](../../docs/apis/v3-deepdive-41-groups.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own the actual data being aggregated** — receipts stay in each member's own Persistence database exactly as isolated as they'd otherwise be; Groups only adds a visibility grant and a tagging convention, never a shared data store.
- **replace break-glass** — see §2, a deliberately distinct third access shape, never modeled as "break-glass that never expires."
- **own the export mechanism itself** — `group_export.py` (§6) is Export Framework's own provider, reusing its existing `excel_general.py`-style technique; Groups only supplies the access rule and the data to pull.
- **resolve sessions itself** — `permission_gate.py`'s `SessionResolver` is a Protocol adapter onto Auth & Tenancy (`docs/PRINCIPLES.md` §1.3); this package holds no login flow, no role taxonomy of its own, and no notion of a session beyond what Auth hands back.
- **record its own privileged-action history** — flipping `is_group_manager` is recorded through an injected async callable shaped like `core.audit.writer.AuditWriter.record_action`, matching Auth's own `core/auth/break_glass/grant.py` pattern; Groups never writes to Audit's database directly and never invents a second audit mechanism.
- **decide job dispatch, exports, or search ranking** — those are Export Framework's and Search/Query's own consumers of this package's data and permission checks, never reimplemented here.

## Forward-Compatibility Pattern applicability

Partially, and the distinction is worth stating precisely rather than a blanket "yes". `contracts.py` itself declares **no** `FrozenDict`-typed field today — `Group` and `GroupMembership` are a flat, small relation, not a bag of arbitrary key/values, so there is nothing to get wrong there (see that module's own docstring for the reasoning, kept live in case a future field changes this). `errors.py`'s `ERROR_CODES` and `ERROR_SUMMARIES` **are** module-level lookup tables and therefore `FrozenDict`, not plain `dict`, per §2.1.1 — any `isinstance` check against either must test `collections.abc.Mapping`, never `dict`, since the Python 3.15 builtin `frozendict` is not a `dict` subclass. `tests/unit/core/groups/test_contracts.py` carries this package's `@pytest.mark.forward_compat` coverage. No code in this folder makes a GIL-protected assumption or touches `asyncio` behaviour that has shifted across Python versions — every mutable structure (`store.py`'s own SQLite connection, guarded by a real lock) is already written the same way Auth's own `AuthDatabase` is, independent of this pattern.

## Real gotchas specific to this folder

The other real instance behind `docs/PRINCIPLES.md` §1.8 — this was buried inside Auth's deep-dive and had to be extracted later. Groups adds a visibility grant and a tagging convention; it never creates a shared data store. Members' receipts stay in their own Persistence databases exactly as isolated as they would otherwise be, which is structural isolation doing the work rather than a permission check (§4.5). It is a genuinely distinct third access shape, not break-glass that never expires.

**Every gated call resolves the caller from a real, live session — never a caller-asserted `user_id`/role/group fact.** `permission_gate.py` is the one place in this package that is deliberately *not* graceful (`docs/PRINCIPLES.md` §4.2): an unresolvable session, a resolver that raises, and a resolved-but-forbidden session all collapse to the identical denial. The shipped default (`DenyAllSessions`) denies everything, by design, until a real `SessionResolver` is wired in.

**The real `SessionResolver` is now wired in — `auth_client.py`'s `GrpcSessionResolver`, calling Auth's own `ValidateSession` RPC.** Confirmed live, not assumed: before this, `service.py`'s own `__main__` called `serve(addr)` with no `resolver` argument at all, so every real running Groups instance actually denied every gated call it ever received — this was the documented-but-not-yet-closed gap the paragraph above already named. `GrpcSessionResolver` never raises (every failure mode — expired, revoked, unknown, Auth unreachable — collapses to `None`, matching the Protocol's own contract), and is live-tested against a genuine running `AuthServicer` in both single- and multi-tenant mode (`tests/unit/core/groups/test_auth_client.py`), including a full `CreateGroup` round trip actually succeeding end to end.

**`is_group_manager` is read live from `store.py` on every call, with no caching layer anywhere.** §7's own testing hook — revoking manager status must deny the very next `search_group()`-shaped call — is only true because nothing in this package remembers a prior answer.

**§11's "active group" selector has an explicit setter (`effective_group.EffectiveGroupResolver.set_active_group`) that is deliberately *not* one of the six gRPC RPCs in `groups.proto`.** The deep-dive's own §9 RPC list is fixed at exactly six and none of them is a mutator for the selector; §11 nonetheless requires a real explicit choice to exist, not only a bootstrap default. Resolved here by keeping the setter as an in-process Python API for whatever surface eventually calls it — Interface's own dedicated group-management screen and the webapp's settings page (§11's third bullet) — rather than inventing a seventh RPC the deep-dive does not name. Revisit this the same session either surface is actually built, since at that point the setter needs a real caller, not just a test.

## Files here that the deep-dive's §3 package layout does not list, added with reasons

- `store.py` — the deep-dive's §3 layout names `membership.py` as owning create/add/remove/manager-toggle, but that is orchestration (validation, id generation, the audit hook), not raw SQL. `permission_gate.py` and `effective_group.py` both need to read live membership state too, so one adapter avoids three independently-maintained row-mappings — the same reasoning `core/audit/db.py` and `core/logs/paths.py` already document for themselves. It also opens the **same physical SQLite file** Auth's own `core/auth/store.py` does (deep-dive §3's placement decision), re-deriving `default_db_path()` rather than importing Auth's own internal file, since `contracts.py` is the only module another package may import from (`docs/PRINCIPLES.md` §1.1).
- `groups.proto` + `generated/` — §9 specifies the six-RPC surface but the layout predates showing where the `.proto` lives. Regenerate with `python -m grpc_tools.protoc` and re-apply the relative-import fix in `groups_pb2_grpc.py` (`from . import groups_pb2`); never hand-edit generated files. `service.py` imports them lazily, so the package stays importable — and its tests still meaningful — on an interpreter with no `grpcio` wheel yet.
- `service.py` — the deep-dive's §9 gives Groups a real six-RPC gRPC surface (own data model, cross-referenced from four other APIs' own deep-dives, its own dedicated TUI screen — meeting §1.8's own extraction threshold on every count), so it gets a service the same way every Core API with a real surface does. It runs as its own process in the core service cluster (`docs/PROCESS_TOPOLOGY.md`), holding its own independent SQLite connection to the same physical file Auth's process opens — the identical multi-connection-one-file mechanism Persistence and Audit already rely on, never a shared in-memory object across a process boundary.
