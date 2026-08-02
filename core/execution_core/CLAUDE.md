# Execution Core API

Execution Core owns **the run** — scheduling (per-user and global concurrency limits), sequencing (Ingestion → Preprocessing → OCR → Matching → Geo → Inference → Persistence write → Review/Flagging on low confidence → Notifications on completion), and applying the active tier profile's knobs to a given run. It is the API that actually calls every pipeline stage in order, which makes every other API's gRPC contract a direct dependency here — and makes the discipline of *not* reaching into any of them the thing this package has to keep getting right.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather than
asserted (`docs/MAINTENANCE.md` §1). V2 had a pipeline runner — `processor.py`/`main.py`'s
`daemon_loop` — but it is not a prior generation of *this* API in any meaningful sense: it
launched processes, drove the menu system and owned the keyboard listener, none of which this
API does or may do. What V3 keeps from it is the list of things that went wrong, which is why
this is `a01`. The `.00.00` tail matches the same deliberate-jump discipline `x03.00.00` itself
follows: Zircon is the first stable release of this generation, not a running total of the
commits that got there.

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this API
lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp` in the
same commit as any change to this API's own behaviour, alongside the program's own `pp` in
`common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing practice and
why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-10-execution-core-api.md`](../../docs/apis/v3-deepdive-10-execution-core-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it. Unusually for this corpus, that deep-dive formalizes an already-thorough
Decisions Log entry (file 03) written by a session that read V2's `processor.py`/`main.py` in
full, so its claims about V2 are evidence rather than recollection.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being valid
the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **launching processes** — that is Supervisor's job (file 01 #21, `v3-deepdive-38-supervisor.md`), structurally separate precisely so that the component deciding whether Execution Core's own release should be swapped is never Execution Core itself. `PROCESS_TOPOLOGY.md` §3.2 has Supervisor launching Persistence before Execution Core, in dependency order, health-gated by Watchdog.
- **any pipeline stage's own logic** — Execution Core calls OCR, Preprocessing, Inference, Matching, Geo/Address and Persistence through their own gRPC contracts and never reimplements a fragment of what any of them do internally. Concretely, that is why stages arrive at `pipeline.py` as a mapping of `ReceiptStage` to a zero-argument awaitable: the caller closes over each API's own request shape, and this package stays ignorant of all seven.
- **UI or interaction concerns** — V2's `daemon_loop` literally instantiated the menu system, keyboard listener and dashboard inside the same loop that ran the pipeline. V3's process separation makes that impossible rather than merely discouraged: Interface reaches this API only through `service.py`'s gRPC surface.
- **generating Excel** — export is on demand and entirely decoupled from run lifecycle (Persistence's own territory). A run reaching `CLOSING` finalizes Persistence writes and fires the completion notification; it does not produce a workbook.
- **deciding what a tier unlocks** — Execution Core applies the active tier profile's knobs to a run; what `pro` actually means is each consuming API's own config bundle, and which tier is being paid for is Billing's.

## Forward-Compatibility Pattern applicability

Yes, on two axes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed and
mapping-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain
`dict` (`docs/PRINCIPLES.md` §2.1), and module-level lookup tables — `ALLOWED_TRANSITIONS` in
particular — are `FrozenDict` too, per §2.1.1. Any `isinstance` check against one must test
`collections.abc.Mapping`, never `dict`: the 3.15 builtin is not a `dict` subclass, and the
specific failure that would cause here is `ReceiptWork.stages` reading as empty, which makes a
receipt process no stages at all and report success.

The second axis is `asyncio`, which §10.1 makes load-bearing here in a way it is not in most of
this repo — the scheduler's semaphores and the debounce coalescer are pure asyncio primitives
and this is the one API whose whole hot path is `await`-all-the-way-down. Free-threading
relevance is genuinely minimal (§10.2): there is no compute-bound pure-Python hot path in this
package to contend over, because coordinating other APIs' work is all it does. `metrics.py`
still takes a real lock rather than relying on the GIL making `+=` atomic, since a collector
reached from whatever thread a run's coordination lands on is exactly where that assumption
breaks (§3.3.1).

## Real gotchas specific to this folder

**`RunState.RUNNING` is in the enum and is deliberately unreachable.** §3's own sketch lists it
and §3's prose immediately explains why it is not a fifth state: a run that is actually
processing is always more precisely `OPEN` or `CLOSING`. Deleting the member would break a
caller still sending the string; leaving it assignable reintroduces the ambiguous state §3 says
to avoid. So `ASSIGNABLE_STATES` excludes it, no row in `ALLOWED_TRANSITIONS` has an inbound
edge to it, and `is_processing()` is the honest way to ask "is it running?". A comment saying
all this would not survive contact with a future implementer; the table does.

**Two asymmetries in `checkpointing.run_stage` are the whole point and read like inconsistency.**
A checkpoint write failure is fatal to the attempt; a Historian narrative failure is swallowed.
An uncheckpointed success is indistinguishable from a failure on the next pass, so treating it
as success means silently redoing the expensive OCR and Inference work §6 exists to protect — a
missing narrative line is a gap in a human-readable record, and failing a paid-for run over an
unreachable logging dependency is the outage-from-one-degraded-component failure §4.4 forbids.
Relatedly, a **resumed** stage does not re-emit narrative: it did not happen again, and
Historian's record must not show a receipt being OCR'd twice because a process crashed after.

**`retry_policy.attempt_stage` deliberately diverges from §7's own sketch, twice.** That sketch
calls `create_flag` unconditionally whenever the cap check trips, which creates a fresh flag on
every subsequent sweep — reintroducing §7's own stated motivating bug ("one bad scan produced 57
identical warnings in a single session") with flags instead of warnings. The escalation is
therefore latched through `AttemptCounter.mark_escalated`. The sketch also returns `None` on
escalation, which no caller can tell apart from a stage whose genuine output is `None`, and the
two demand opposite handling; `StageAttempt` carries the outcome as data instead (§4.1). Both
divergences are tested by name.

**The attempt counter increments on failure, never on entry.** Counting entries would let three
interrupted-but-successful passes trip a cap of three and flag a perfectly good receipt for
human review — noise in exactly the queue §7 exists to keep meaningful.

**`pipeline.process_run` takes cancellation as a callable, and it has to.** `Run` is frozen and
`state_machine.transition` returns a *new* object, so re-reading `run.state` inside the loop
would read the same snapshot every iteration and §8's per-receipt check would be decorative
rather than the fix for V2's 156-receipt run that kept going for minutes after a stop request.
`service.RunRegistry.is_cancelled_for` is the live signal; the default preserves the honest
degenerate case where a run handed over already `SHUTTING_DOWN` processes nothing.

**`cancellation_check_interval` is not a field on `ExecutionConfig`, on purpose.** §12 lists it
in the config surface and states it is "not configurable to anything coarser — this is a hard
requirement, not a tunable". The only way to make that true is to give it no knob; a field
defaulted to `per_receipt` would be a knob someone could turn, and turning it is how V2's bug
comes back. A test asserts the field's absence.

**Run-level idempotency and blob-level dedup are two different questions** (§4) and conflating
them loses one of them. Same-SHA-256-same-blob is Persistence's storage concern; whether this
content has already been processed all the way into a database row is this API's. Keyed on
content hash and never mtime, because cloud sync touches mtime on bytes that did not change —
V2's `_file_fingerprint()` learned that the expensive way. An empty hash never matches, since an
unanswerable question answering itself "yes" would silently drop a real receipt.

**The debounce ceiling is measured from `opened_at`, never from the most recent trigger** (§5.2),
and a trigger arriving at or past it starts a *new* run rather than joining the old one — the
ceiling "is a real boundary, not advisory". A late file sneaking into a run already finalizing
its writes would be a receipt in the database that no run ever announced. Note that a ceiling
can fire through either path — the `due_for_closing` sweep or `on_trigger` itself — and both are
legitimate; the test asserts the run stopped being open rather than which mechanism closed it.

**`RunScheduler` acquires global before per-user, always.** Two coroutines taking the same two
locks in opposite orders is the textbook deadlock and consistent ordering is the only defence.
The release is in a `finally`, so a failing run never strands a slot — the same
abandoned-reservation failure Health's ledger needed a TTL sweep to survive, prevented
structurally here instead.

**Files here that the deep-dive's §2 package layout does not list**: `execution_core.proto` and
`generated/`, which §11 specifies as a surface but §2 does not name as files; and `CLAUDE.md`
itself. §2 also writes the package as `services/execution_core/` — every Core API in this repo
lives under `core/`, so the path follows repo convention rather than that one line.

## Known gaps, flagged rather than silently filled

- **There is no distinct "completed" run state.** §3's enum ends at `SHUTTING_DOWN`, and a run
  that finished normally is `CLOSING` with every receipt at `WRITTEN`. Adding a `COMPLETED`
  member would be defining taxonomy this API does not own (`docs/PRINCIPLES.md` §3.4), so it is
  recorded here rather than invented. Worth resolving before Interface renders run history.
- **`GetRunStatus` reports `receipts_completed` from the metrics collector rather than from
  per-run progress.** The stream, its framing and its termination conditions are real; what is
  missing is a per-run progress record, which belongs with the run registry once runs are
  durable rather than in-memory.
- **`RunRegistry` keeps runs in memory.** Every behaviour above is implemented and tested; what
  is missing is the persistence adapter. This joins the same open question `core/billing/` and
  `core/support_ticketing/` each record for their own stores.
- **Nothing here wires the stage callables to the seven APIs they will call.** That is
  deliberate and is the boundary working — but OCR, Preprocessing, Inference, Ingestion and
  Reconciliation are all still empty scaffolding in this repo, so no end-to-end run exists yet
  to integration-test against.
