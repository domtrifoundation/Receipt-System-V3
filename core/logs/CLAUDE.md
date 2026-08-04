# Logs API

Logs owns comprehensive, verbose **operational trace** — OCR engine outputs/timing, LLM prompts/responses/tool calls, preprocessing steps, worker activity, errors — covering every subsystem, stored as day-rotated JSONL files with a lightweight query index over them.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Second generation. V1 had no logging layer worth
the name. V2 did: `receipt_processor/verbosity.py` implemented real verbosity tiers, and V2's
own commit history carries the `str(e)`-instead-of-full-traceback bug that is now an explicit,
unconditional requirement here (§3.3 of the deep-dive) rather than something to rediscover.
V3 is the generation where operational trace becomes its own bounded service with structured
entries, an index, and permission-gated read access instead of tier-filtered console output.
The `.00.00` tail matches the same deliberate-jump discipline `x03.00.00` itself follows.
`MM` increments again on any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.02`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-18-logs-api.md`](../../docs/apis/v3-deepdive-18-logs-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **storage through Persistence's Historian** — Logs are gitignored, rotated flat files with their own retention policy, never an events table. Historian is the *data-change* audit trail; Logs is *operational* trace, a genuinely different volume and purpose that does not belong in Historian's atomic-transaction-per-write model.
- **Audit's privileged-action record** — a receipt's OCR timing is Logs' job; a staff member's break-glass grant is Audit's, never both.
- **any rendering or presentation logic** — a `LogEntry`'s level carries a `suggested_style` hint (`LEVEL_STYLE_HINT`) precisely so a renderer does not maintain its own drifting opinion about severity, but Logs itself never renders anything. It is a client-agnostic data service, the same way Persistence is.
- **its own permission model** — cross-user reads go through Auth's existing `check_access()` break-glass gate (`v3-deepdive-05-auth-tenancy-api.md` §6.3), never a second mechanism invented here. `query.py` reaches it through one `AccessChecker` adapter and holds no notion of roles or grants itself.
- **deciding whether a failure is survivable** — `writer.guarded_call` records the traceback and re-raises. Logs records what happened; what to do about it belongs to the caller.
- **running the retention sweep** — `retention.py` implements the policy, but it is invoked by a Background Workers idle-time job (§5), never from the write path, which stays a pure append.

## Forward-Compatibility Pattern applicability

Yes. `LEVEL_STYLE_HINT` and `LEVEL_SEVERITY` in `contracts.py` are module-level lookup tables
and are therefore `FrozenDict`, not plain `dict` — `docs/PRINCIPLES.md` §2.1.1 covers this case
specifically, and this module is one of the two instances that section was written from.
`LogEntry.context` and `Verbosity.per_service` are `FrozenDict`-typed contract fields for the
same reason. Any `isinstance` check against any of them must test `collections.abc.Mapping`,
never `dict`: the 3.15 builtin is not a `dict` subclass, so `isinstance(x, dict)` silently
returns False and the wrong branch is taken. `tests/unit/core/logs/test_contracts.py` carries
the one `@pytest.mark.forward_compat` test in this package, asserting exactly that.

The mutable structures here are deliberately **not** `FrozenDict` and the distinction is
visible in the type: `SinkRegistry`'s own sink map (populated at startup) and
`LogsMetricsCollector`'s counters are genuinely mutable internal state, which §2.1.1 does not
reach. The counters are guarded by a real lock rather than relying on the GIL making `+=`
atomic — this project targets free-threaded 3.14t, where that assumption does not hold.

This API is pure async I/O (`v3-plan-02-architecture.md`'s concurrency table, #13) with no
compute-bound work; `writer.py` is the only module that knows about the event loop.

## Real gotchas specific to this folder

The SQLite index in `index.py` is a **query accelerator over the JSONL files, not a second
source of truth**. It must stay fully rebuildable from the JSONL files alone — there is a
testing hook that deletes it and regenerates it precisely to keep that claim honest. If you
find yourself writing log *content* that exists only in the index, that is the bug.

Full tracebacks are captured unconditionally, independent of verbosity tier. Tiers control the
volume of routine logging; they never gate whether a failure's traceback is recorded. This is a
direct correction of a real V2 bug, not a preference. In the code that is `writer.should_write`,
where the traceback branch runs *before* the tier is consulted; `guarded_call` is the helper for
the case the deep-dive names specifically — an exception raised inside a
`run_in_executor`-dispatched call, formatted while its `__traceback__` still reaches back through
the executor frames. Catching such a failure further out and logging `str(e)` is the exact
regression this is here to prevent.

**TRACE entries are written to a sibling `<day>.trace.jsonl` file**, not mixed into the day's
main file. §10 gives TRACE its own 7-day window against everything else's 90, and purging only
the trace lines out of a mixed file would mean an in-place rewrite — which §3.1's whole storage
argument rules out. Splitting the tier keeps the shorter TTL a plain file delete. Rotation is
still one file per service per day, only two tracks of it.

**Files here that the deep-dive's §2 package layout does not list**, added with reasons:
- `paths.py` — `writer`, `index`, `query` and `retention` all need the same answer to "which
  file does this belong in", and the alternative was three of them importing it from the fourth.
- `jsonl.py` — one codec, both directions. Splitting encode into `writer.py` and decode into
  `query.py` would be two independently-maintained opinions about one file format.
- `sinks.py` — the Provider Registry for destinations (`docs/PRINCIPLES.md` §1.2, §1.3). The
  JSONL files stay the canonical one; the registry is what lets a live-tail buffer or a
  self-hosted forwarder run *alongside* it rather than instead of it. A failing sink degrades
  alone: logging must never be able to fail the thing being logged.
- `retention.py` — §5's policy, kept off both the append-only write path and the index.
- `logs.proto` + `generated/` — §7 specifies the surface but the layout predates showing where
  the `.proto` lives. Regenerate with `python -m grpc_tools.protoc` and re-apply the
  relative-import fix in `logs_pb2_grpc.py` (`from . import logs_pb2`); never hand-edit
  generated files. `service.py` imports them lazily, so the package stays importable — and its
  tests still meaningful — on an interpreter with no `grpcio` wheel yet (3.15 today).

**A real, foundational, previously-undiscovered gap, confirmed by grep rather than
assumed: `LogWriter` had zero callers anywhere outside this package.** `logs.proto` has
no `Write`/`Ingest` RPC at all — only `Query` — so the real, intended architecture (this
document's own §1: "every API in this batch writes through this one for operational
trace") is that each service imports `LogWriter` directly and appends to its own file on
the shared log root, never a gRPC hop into this API's own process for every write.
Nothing did. Every `except Exception: pass`-shaped best-effort catch in every other Core
API genuinely wrote to nothing.

**`core/ingestion/service.py` is the first package actually fixed** (its own `CLAUDE.md`
has the full account) — one `LogWriter` instance per process, injectable so tests never
write real files to this machine's own default log root, wired into every one of that
file's own broad `except` blocks, with a real end-to-end proof (`tests/unit/core/
ingestion/test_real_logging.py`: a forced failure is read back afterward through a real
`LogReader`, full traceback intact). **Every other Core API's own equivalent catches are
not yet fixed** — the identical mechanical pattern, real, separate, much larger
follow-up work.

**`.github/scripts/check_no_silent_except.py` is the new, permanent guard against this
recurring**, required on every PR (`docs/MAINTENANCE.md` §7.1). It fails on any *new*
broad `except` (bare, `Exception`, or `BaseException`) that neither re-raises nor calls
something with `log` in its name — narrow, named exception types converted to clean
error-as-data returns (`docs/PRINCIPLES.md` §4.1) are correctly never flagged, since
logging every one of those would be noise, not signal. The 102 pre-existing violations
found across the rest of the codebase the day this check was added are grandfathered in
`.github/silent_except_baseline.json`, real and visible, not hidden — the baseline only
ever shrinks as those sites get fixed, never grows to grandfather something new.
