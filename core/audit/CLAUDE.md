# Audit/Event Log API

This project has three genuinely different logging mechanisms, and keeping them distinct rather than merging "for simplicity" is itself the design decision worth stating clearly:
- **Logs API** — operational trace (OCR timings, LLM prompts, worker activity, errors). High-volume, gitignored, rotated, retention-policy-driven. Answers "what did the system do."
- **Persistence's Historian sub-package** — data-change trail (table/row/before-after/actor for every logical write to a user's own receipt data). Lives inside each user's own Persistence database, atomic with the write itself. Answers "how did this receipt's data get to its current state."
- **Audit/Event Log API (this document)** — privileged, security-relevant *actions*, not data changes: break-glass access grants, global vendor contribution reviews (approve/reject), config/role changes, confirmed-malicious content verdicts (Content Security's staff resolution). Answers "who did something with real security/compliance weight, and when."

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no privileged-action log — its `docs/AUDITING.md` is a code-review guide for humans reading diffs, an unrelated sense of the word. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-08-audit-event-log-api.md`](../../docs/apis/v3-deepdive-08-audit-event-log-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

The deep-dive states its boundary as prose (its §1); this is that boundary as the list a fresh session actually needs, since "what looks like it should live here but doesn't" is the thing to get wrong here.

- **Operational trace** — OCR timings, LLM prompts, worker activity, errors. That is Logs API, high-volume and rotated. If the question is "what did the system do," it is not this API's.
- **The data-change trail** — table/row/before-after/actor for a logical write to a user's own receipt data. That is Persistence's Historian sub-package, living inside that user's own database and atomic with the write. A user correcting their own vendor name is Historian's; a staff member gaining access to that user's folder is this API's, even though both are "an action someone took."
- **Deciding whether a privileged action is permitted.** Auth & Tenancy decides; this API records that it happened. Nothing here is in a permission path, and adding a check here would create a second, drifting copy of Auth's own rules.
- **Telling a client that they were affected.** A client learning "staff member X accessed my folder on date Y for reason Z" is served directly by Notifications, per Auth's break-glass design. Read access here is staff/owner only and deliberately does not serve that same information a second way.
- **Any per-user data, and any place in a per-user database.** Audit events span every user and every staff action, so they are cross-tenancy infrastructure — its own small top-level SQLite database beside Auth's and Architect's, never a table inside a per-user Persistence folder (§3.1, `docs/PRINCIPLES.md` §1.6).
- **Taxonomy or learned data.** `ActionType` is this API's own closed vocabulary of things that happened, not an extensible typed thing. Anything genuinely typed, learned or schema-shaped goes through Architect API (`docs/PRINCIPLES.md` §3.4).
- **Agent Control's own action trail.** Agent Control's `store.py` currently holds its own `agent_audit` table as a bounded exception taken before this API existed. Folding it in is a real, known migration — but it is that API's move to make, not something to reach across and do from here.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1) — `AuditEvent.details` and `AuditMetrics.events_by_action` specifically. Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict`; `writer.coerce_details` is the live instance of that, and `db.event_to_row` is the other one people miss — `json.dumps` refuses a 3.15 builtin `frozendict` because it is not a `dict` subclass, so it is converted with `dict(...)` first. Module-level lookup tables here are `FrozenDict` too, per §2.1.1: `contracts.PRIVILEGED_ACTIONS`, `contracts.RETENTION_SETTING_SPEC`, `errors.ERROR_SUMMARIES`, `db.PROFILE_EXTRA_OPS`. `SinkRegistry`'s own sink list stays mutable on purpose — a registry populated at startup is what §2.1.1 names as correctly mutable, and the difference in type is the point. The `@pytest.mark.forward_compat` tests covering all of this are in `tests/unit/core/audit/test_metrics_and_contracts.py`; they pass on both 3.14.6 and 3.15.0b4, with `type(table) is FrozenDict` confirming the builtin branch is genuinely taken on 3.15 rather than the PyPI package silently still being used.

## Real gotchas specific to this folder

**Append-only is structural, and it is enforced three independent ways.** No `update_event()` or `delete_event()` exists on any class here; no module hands out its connection object; and each connection is opened under a `db.py` authorizer profile that makes SQLite itself refuse the statement (`sqlite3.set_authorizer`, the deep-dive's own resolved mechanism). `SQLITE_UPDATE` is in *no* profile at all. `tests/unit/core/audit/test_append_only.py` goes around the public API and issues the raw SQL to prove it, and it also asserts that no public method name in this package looks like a mutation path — if you add one, that test is what will tell you.

**`retention.py` is the one place rows are deleted, and it is deliberately hard to reach.** Its `purge()` takes a policy and an actor, never an event id or a predicate, so the only expressible operation is "apply the configured horizon." It appends a `RETENTION_PURGE_EXECUTED` record of what it removed, and those records are themselves exempt from purging — otherwise the trail of prunings would eventually prune itself.

**Every timestamp goes through `db.to_storage_ts` before it is stored or compared.** `occurred_at` is a TEXT column, so the retention horizon's `<`, the query filter's range bounds and `ORDER BY occurred_at DESC` are all *lexical* string comparisons. An event recorded by a caller in `+08:00` spells an instant as a string that sorts seven hours later than the same instant in UTC — which meant a row genuinely past its horizon survived the sweep, and rows from different offsets sorted out of chronological order. Normalising to UTC at the single point where a timestamp enters storage is what makes the lexical comparison agree with real chronology; do not add a new comparison against this column that bypasses it. A naive datetime is treated as UTC rather than refused — losing the evidence over a missing `tzinfo` would be the wrong trade.

**Nothing in this package may raise out of a read path.** A row is decoded with `ActionType(...)`, `json.loads` and `datetime.fromisoformat`, all of which raise `ValueError` on data written by a *different* build of this package — a newer release's `ActionType`, say. `query.py` and `metrics.py` therefore catch `ValueError`/`TypeError` alongside `sqlite3.DatabaseError` and report `READ_FAILED` as data; `service.py` parses wire timestamps through a local `_BadTimestamp` for the same reason. This is §4.1 applied to the read side, which is easier to miss than the write side.

**Do not put `AUTOINCREMENT` on the sequence column.** It makes SQLite maintain `sqlite_sequence`, so every INSERT also issues an UPDATE against that table — which the append profile correctly denies, breaking ordinary appends in a way whose error message points nowhere near the cause. A plain `INTEGER PRIMARY KEY` is a rowid alias and is enough.

**Files here that the deep-dive's §2 layout does not list**, added with reasons: `db.py` (the sole `sqlite3` adapter — three modules need three different authorizer profiles, and putting the factory in `writer.py` would mean the read path imports the writer to get a read handle); `sinks.py` (the `AuditSink` Protocol's registry, so a compliance-driven install can mirror to a WORM target *alongside* the SQLite primary rather than replacing it); `retention.py` (§5, kept out of the writer for the reason above); `audit.proto` + `generated/` (§2 predates showing where the `.proto` lives — regenerate with `python -m grpc_tools.protoc` and re-apply the relative-import fix in `audit_pb2_grpc.py`; never hand-edit generated files).

**`ActionType` carries six members beyond the deep-dive's §4 list.** They close a real gap between §4 and §7 — §7's coverage test names `ForceWake`, `PinServiceVersion`, agent-token issuance and `is_group_manager` toggles as actions that must be audited, and §4's enum could not represent any of them — plus `RETENTION_PURGE_EXECUTED` for §5. Enum *values* are stable wire strings stored in rows that live ten years: add members freely, never rename or reuse a value.

**`service.py`'s default role resolver denies everything.** Auth & Tenancy owns session resolution and does not exist yet, so the resolver is injected and its default is closed. Wiring Auth in means passing a real resolver — not deleting a permissive default someone forgot was there.
