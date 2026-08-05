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

`a01.00.10`

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
itself.

**This package lives at `services/execution_core/`, matching the deep-dive's own §2.** It spent
Phase 2 at `core/execution_core/` instead, justified in this file by the claim that "every Core
API in this repo lives under `core/`" — which was simply not true: Interface (#6), Gateway
(#16), Update (#21), Setup (#23) and Status Page (#30) are all Core APIs, and every one of them
lives under `services/` per its own deep-dive §2. The move also cleared a genuine duplicate: a
0-byte `services/execution_core/` scaffold was shadowing this implementation, each with its own
`CLAUDE.md`. `docs/PROCESS_TOPOLOGY.md` §2.1 now states the actual `core/` vs `services/` rule,
so the next package does not have to re-derive it from whichever neighbour it happens to look at.

## Known gaps, flagged rather than silently filled

- **There is no distinct "completed" run state.** §3's enum ends at `SHUTTING_DOWN`, and a run
  that finished normally is `CLOSING` with every receipt at `WRITTEN`. Adding a `COMPLETED`
  member would be defining taxonomy this API does not own (`docs/PRINCIPLES.md` §3.4), so it is
  recorded here rather than invented. Worth resolving before Interface renders run history.
- **`GetRunStatus` reports `receipts_completed` from the metrics collector rather than from
  per-run progress.** The stream, its framing and its termination conditions are real; what is
  missing is a per-run progress record, which belongs with the run registry once runs are
  durable rather than in-memory.
- **`ListActiveRuns` is new and real** — closes the actual gap behind the TUI's own Run
  Monitor screen never being buildable: `GetRunStatus` requires already knowing a `run_id`,
  and nothing exposed the set of runs this process knows about. `RunRegistry.list_all()`
  is the same in-memory `dict.values()` every other method here already reads from.
- **`RunRegistry` keeps runs in memory.** Every behaviour above is implemented and tested; what
  is missing is the persistence adapter. This joins the same open question `core/billing/` and
  `core/support_ticketing/` each record for their own stores.
- **All six real pipeline stages are now wired — the gap this bullet used to describe is
  closed.** OCR, Preprocessing, and Persistence were the first three (below); Matching,
  Geo, and Inference are wired now too, found and closed the same session as a real
  prerequisite for testing extraction quality against real receipts (a real request to
  test extraction/vendor-matching/persistence/reconciliation against real data surfaced
  that `SubmitReceipt` produced OCR text and nothing else — not a hypothetical gap). New
  `gateways.py` classes: `GrpcArchitectGateway` (not itself a `ReceiptStage` — `matched()`
  needs real candidates before it can call Matching at all, and Matching never fetches its
  own, `core/matching/CLAUDE.md`'s own "does NOT own" line), `GrpcMatchingGateway`,
  `GrpcGeoGateway`, `GrpcInferenceGateway`. `receipt_orchestration.py`'s `matched()` takes
  the first non-empty OCR line as a naive vendor-search query into Architect, then calls
  Matching's `GetVendorMatchContext`; `geod()` geocodes using `matched()`'s own top
  candidate as a hint, degrading honestly to Geo's own default `UnavailableTransport`
  result rather than crashing when no real provider is configured; `inferred()` builds a
  real `RECEIPT_EXTRACTION_SCHEMA` (vendor_name, transaction_date, amounts, vat_treatment,
  tin, or_number, address — a deliberately scoped v1, not the full eventual field set) and
  calls Inference's `Generate` with `response_schema_json` set, corroborated with
  `matched()`'s own candidate in the prompt rather than blind to it; `written()` now folds
  `inferred`/`matched`/`geod`'s real output into the persisted record instead of raw OCR
  text alone. All three new stage params on `build_receipt_work()` default to `None` and
  are skipped when absent (`docs/PRINCIPLES.md` §4.4) — an existing caller supplying only
  the original four `addresses` keys (`tests/unit/services/execution_core/
  test_receipt_pipeline_e2e.py`, unmodified) keeps the exact prior three-stage behavior,
  confirmed by that test still passing unchanged. Live-tested end to end against seven
  genuine running servicers, no mocked gRPC stub anywhere in the chain (`test_receipt_
  pipeline_full_e2e.py`) — Inference runs a fake worker (no real model in a unit test,
  matching `core/inference/tests`' own established pattern), Architect/Matching/Geo run
  for real with their own real default (empty directory / no configured provider), and the
  persisted record is asserted to actually carry the real structured extraction, a real
  (empty-but-present) vendor-match result, and a real geocode attempt.

**`ocrd()` now runs a real multi-variant, multi-engine corroboration sweep, not a single
rasterize-then-read pass — a direct fix for a real, live-found extraction-quality problem,
not a speculative enhancement.** Running real receipts through the full pipeline for the
first time surfaced messy extraction (vendor names with the street address run in,
`tin`/`or_number` never populated) that traced back to `ocrd()` only ever reading one
plain rasterized image — Preprocessing's own real `GenerateVariants` RPC (`generate_
variants()`, new on `GrpcPreprocessingGateway`) was built and tested in its own package
but never actually called from the live pipeline. `_OCR_VARIANT_KINDS` (`standard`,
`bw_threshold`, `high_contrast`, `deskew`, `denoise`) is a deliberately broader real set
than Preprocessing's own conservative `DEFAULT_VARIANTS_ENABLED` (`{standard,
bw_threshold}`, `variant_registry.py`) — chosen for the extraction-quality problem this
exists to help with, each variant read by every one of OCR's own enabled engines
internally (the real "N variants x M engines" sweep). The variant/engine combination
with the highest real `OcrReadResponse.confidence` wins; a variant whose own generation
failed (`Variant.error_code` set) is skipped, never fatal, and if every variant fails the
stage falls back to the one base rasterized image rather than failing the receipt over a
corroboration enhancement with nothing to enhance. Only applies to the real production
default (`ocr_source="preprocessed"`) — the `ocr_source="source"` digital-PDF-text-layer
path has no rasterized image to generate variants from, unaffected. **Real, live-found
test-setup bug fixed in the same pass**: the one existing test exercising this default
path (`test_receipt_pipeline_e2e.py`'s own `test_the_default_production_path_...`) passed
a lambda as `blob_store_factory`, which had silently worked until `GenerateVariants` was
actually called for the first time — Preprocessing's own variant generation runs in a
real `ProcessPoolExecutor` (`core/preprocessing/CLAUDE.md`'s own documented "closures
cannot be pickled" constraint), and a lambda genuinely cannot cross that boundary
(`_pickle.PicklingError`, confirmed live). Fixed with a module-level factory reading a
real env var for the dynamic per-test address, matching `core/preprocessing`'s own
established `_make_test_blob_store` pattern exactly rather than inventing a new one.

**`inferred()`'s own prompt was rewritten with explicit, real corrections for the exact
mistakes live testing found**, not generic prompt-engineering guesswork: real extracted
output before this fix included `vendor_name` fields with the street address run
directly into the business name (`"J.R. Balara Puregold Ommonwealih Ave City Quezon
Balara M.E."`) and `tin`/`or_number` left empty on every single real receipt tested. The
prompt now explicitly names both mistakes and states the fix (`vendor_name` is the
business name only, address goes in the separate `address` field; look specifically near
`"VAT REG TIN"`/`"TIN"`/`"OR#"`/`"SI#"` labels). `max_tokens` for this specific call also
dropped from Inference's generic 1024 default to 400 (later raised to 600 once `items`
joined the schema, see below) — this schema's own output is one compact JSON object, and
letting a struggling generation run 2-3x longer than a complete answer ever needs was
real, unnecessary latency on top of the real timeout problem the thread-limiting fix
(`core/inference/CLAUDE.md`) addresses from the other side.

**Two more real fixes the same session, found by testing real concurrent receipts and
reading the actual output quality, not by guessing:**

- **`ocrd()`'s own variant reads were sequential — a real, measured 52-135 seconds per
  receipt for this one stage alone**, the single largest real contributor to
  "embarrassingly slow" once Inference's own timeout was fixed. Fixed with
  `asyncio.gather` over the real variant list instead of a `for` loop awaiting each one
  in turn — the 5 variants' OCR reads now genuinely run concurrently.
- **`inferred()` used to see only the single highest-confidence OCR reading — a real,
  live-found architecture gap, not a deliberate simplification.** A direct request asked
  whether the LLM was "properly receiving the full outputs of all the OCR for
  deliberating the final output" — it was not; this orchestrator picked one "best"
  reading and discarded the rest before the LLM ever saw them, which is exactly backward
  for a model whose own real strength is cross-referencing disagreeing sources.
  `ocrd()`'s own stage output changed shape (`{"best_text": ..., "readings": [...]}` —
  `matched()`/`geod()` still use `best_text` for their own cheap heuristics, which have
  no real use for multiple candidates) and `inferred()`'s prompt now includes every
  distinct real reading, labeled with its own variant/confidence/agreement, explicitly
  asking the model to cross-reference them.

**`RECEIPT_EXTRACTION_SCHEMA` grew real fields on direct request: `franchiser`,
`franchiser_tin`, and `items` (real line-item detail).** Extraction alone is not
learning, stated plainly rather than implied solved: nothing here yet calls Architect's
own real `temporal_learning` pipeline to actually learn which franchisers serve which
vendors, which TINs/addresses belong to which vendor or franchiser — that association
work is real, separate, larger follow-up against an already-built mechanism (`core/
architect/temporal_learning/`), not something this pass invented or wired.

**Real architecture finding, not yet a fix: Inference itself has no genuine
multi-request parallelism.** Raising `RunScheduler`'s `per_user_limit` (previously
defaulted to 1, which fully serialized one user's own receipts end to end — the direct
answer to "are we waiting rather than pipelining the next receipt") proved real
concurrency benefit at the *run* level (5 receipts submitted concurrently: 550s
wall-clock vs. 2039s summed individually, live-measured) — but every one of those
receipts' own `inferred()` calls still queues behind the others at the single shared
`PresetWorker` process (`core/inference/CLAUDE.md`'s own account of `_worker_main`'s
strictly-sequential batch-drain loop). Preprocessing/OCR of receipt B now genuinely
overlaps with Inference of receipt A — real, working pipelining — but Inference-vs-
Inference concurrency across receipts does not exist yet. Flagged here as the honest,
unresolved half of "is inference concurrent," not silently claimed fixed alongside the
real wins above.

**Follow-up in the same session, once real concurrent-receipt testing confirmed the
above with real numbers: `ocrd()`'s own OCR-fix (real, confirmed working — timing
dropped from 52-135s to 17-38s) surfaced a second real cost from `inferred()`'s "hand
the LLM every reading" fix — the prompt got long enough, often enough, that prefill
time became a real, measured contributor to inference regularly exceeding the timeout
under concurrent load.** `_select_distinct_readings()` (`difflib.SequenceMatcher`-based
near-duplicate filtering, not just exact-text dedup, capped at `_MAX_READINGS_FOR_LLM=3`)
bounds this: highest-confidence readings kept first, a reading only added if it's
genuinely different from every one already kept. Real, deliberate tradeoff, not free —
most of the corroboration benefit for a bounded, predictable prompt size, at the cost of
not showing the LLM every single one of 5 real variant readings when several happen to
agree closely. `tests/unit/services/execution_core/test_receipt_orchestration_helpers.py`
covers the real selection logic directly (confidence ordering, near-duplicate rejection,
the real cap, empty input) without needing gRPC or a real model.

**Follow-up in the same session: the reading cap is a real, caller-configurable
parameter now, not a fixed module constant — a direct request, and it turned out
the cap wasn't the dominant cost after all.** `_select_distinct_readings()` now takes
`max_readings` explicitly; `build_receipt_work()`'s own new `max_ocr_readings_for_llm`
parameter (`DEFAULT_MAX_READINGS_FOR_LLM = 5`, raised back from the first pass's `3`)
is the real seam a future TUI/settings surface threads through — not yet wired to one,
real scoped follow-up, same posture as `core/inference/CLAUDE.md`'s own
`worker_pool_size`. Live concurrent-receipt testing after the cap fix landed showed
inference *still* regularly hitting the generation timeout — real evidence the reading
count was never the dominant cost; genuine single-worker queueing (see `core/inference/
CLAUDE.md`'s own account of the real `worker_pool_size` fix) was. The reading cap stays
because it's still a real, correct bound on prompt size, not because it turned out to be
the fix.

## Real, live-tested integration — the actual missing piece, closed

**`SubmitReceipt`, a new RPC, is what makes a receipt actually get processed.**
`StartRun` was always real but only ever tracked run metadata (debounce coalescing,
state) — confirmed live before this fix, nothing anywhere called `pipeline.process_run`
or constructed a real `ReceiptWork`. `gateways.py` (real gRPC clients for Preprocessing/
OCR/Persistence, plus an in-memory `CheckpointStore`/`AttemptCounter` — real within one
process's lifetime, not yet Persistence-backed since `persistence.proto` has no
checkpoint-storage RPC at all yet, and a real gRPC-backed `ReviewFlagger` against Review/
Flagging's already-existing `CreateFlag`) and `receipt_orchestration.py` (`build_receipt_
work()`, wiring `preprocessed`/`ocrd`/`written`) are the two new files. `SubmitReceipt`
runs under the real `RunScheduler` (`scheduler.acquire(user_id)`), so two different
users' receipts genuinely process concurrently up to the configured per-user/global
limits — confirmed live with a real concurrent-submission test, not just trusted from
`RunScheduler`'s own unit tests in isolation.

**A real, live-found bug, fixed**: OCR's `text_layer` engine reads a PDF's own embedded
text metadata; running it against `preprocessed`'s own rasterized bitmap output returns
an empty read every time (confirmed live before the fix). `build_receipt_work()` takes
`ocr_source`/`ocr_engines` so a caller can choose "read the original blob with a specific
engine" (a digital PDF) vs. the real production default, "read the rasterized image with
every enabled engine" (a photographed/scanned upload) — see that function's own
docstring for the full account, including that choosing the right one per actual source
kind automatically, rather than a caller having to know, is real follow-up work.

**Ingestion's `SubmitDirectUpload` now actually triggers this** — the real webapp/
direct-upload path, confirmed live end to end against six genuine running servicers
(Content Security, Persistence, Preprocessing, OCR, Execution Core, Ingestion itself; see
`core/ingestion/CLAUDE.md`). The Google Drive webhook path and the scheduled fallback
poll do not yet call `SubmitReceipt` — `webhook_manager`'s own `pending_events` queue
already exists as "a stand-in for Execution Core's own not-yet-built debounce consumer"
per that package's own docstring, and consuming it into real `SubmitReceipt` calls is
the identical pattern, not yet applied.
