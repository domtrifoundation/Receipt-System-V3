# V3 Deep Dive: Logs API

**Companion files:** all prior deep-dives — every API in this batch writes through this one for operational trace; `v3-deepdive-08-audit-event-log-api.md` §1 already draws the precise three-way distinction (Logs/Historian/Audit) this document builds on rather than repeats.

**Status:** Eighteenth deep-dive session.

---

## 1. Scope & boundary

Logs owns comprehensive, verbose **operational trace** — OCR engine outputs/timing, LLM prompts/responses/tool calls, preprocessing steps, worker activity, errors — covering every subsystem. **Logs API runs as part of the main process (the core execution cluster, alongside Execution Core, Persistence, OCR, and every other Core API) — it is not part of, does not live inside, and does not depend on Interface API in any way.** This is a concrete instance of `docs/PRINCIPLES.md` §1.7 (process separation via gRPC) — worth stating this plainly given an earlier version of Interface API's own deep-dive blurred the line by describing log rendering in enough depth to read as if Logs itself were an Interface concern: Logs API writes, rotates, and serves its own data entirely independently of whether Interface's TUI process is running, attached, or has ever been launched at all. Interface is a gRPC *client* of Logs API (via the `LogsService.Query` streaming RPC, §7) — a client that can be closed, crash, or simply not exist for a given install, with zero effect on Logs API's own operation. It does not:
- **go through Persistence's Historian** — already settled in file 01: gitignored, rotated flat files with their own retention policy, not an events table or git history. Historian is the *data-change* audit trail; Logs is *operational* trace, a genuinely different volume and purpose that doesn't belong in the same atomic-transaction-per-write model Historian relies on.
- **duplicate Audit's privileged-action record** — a receipt's OCR timing is Logs' job; a staff member's break-glass grant is Audit's, never both.
- **own any rendering/presentation logic** — a `LogEntry`'s `level` carries a `suggested_style` hint (§3.1) precisely so a renderer doesn't need its own independently-maintained opinion about what each level should look like, but Logs API itself never renders anything — it's a client-agnostic data service the same way Persistence is.

---

## 2. Package layout

```
core/logs/
  __init__.py
  contracts.py           # LogEntry, Verbosity, error types
  writer.py                 # rotated JSONL writer — see §3
  index.py                    # run_id/user_id → file+offset index for fast query — see §3.2
  query.py                      # permission-gated read access — see §4
  errors.py
  metrics.py
```

---

## 3. Storage: rotated, structured, indexed for query without a database

### 3.1 Format — JSON Lines, day-rotated
```python
class LogLevel(str, Enum):
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    ATTENTION = "attention"      # new — see §3.4: distinct from ERROR, "this is running below its own achievable baseline," not "something broke"

# A rendering hint, owned here where the level itself is defined — not
# duplicated as a second, independently-maintained opinion inside
# whatever client happens to render it (Interface's TUI today; nothing
# stops a future client from existing and needing the same hint). This
# is metadata Logs API publishes, not rendering logic Logs API performs
# — the client still decides how to actually apply it (Rich markup
# strings for a terminal client, something else entirely for a client
# that isn't a terminal), but the *mapping itself* has exactly one
# source of truth.
LEVEL_STYLE_HINT: FrozenDict[LogLevel, str] = FrozenDict({   # FrozenDict per docs/PRINCIPLES.md §2.1.1
    LogLevel.TRACE: "dim",
    LogLevel.DEBUG: "subdued",
    LogLevel.INFO: "default",
    LogLevel.WARNING: "caution",
    LogLevel.ERROR: "critical",
    LogLevel.ATTENTION: "critical_persistent",   # deliberately a distinct hint from "critical" — a client should render this as harder to miss than ERROR, per §3.4
})

@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    run_id: str | None
    user_id: str | None
    service: str              # "ocr" | "inference" | "preprocessing" | ...
    level: LogLevel
    message: str
    traceback: str | None        # full traceback text, see §3.3 — never just str(e)
```
One append-only JSONL file per service per day (`logs/ocr/2026-07-17.jsonl`) — simple to write (pure append, no in-place rewrite ever), simple to rotate (a new file at day boundary, no truncation logic needed), and trivially streamable for a live tail view without needing a database connection for the write path itself.

### 3.2 Query without full-file scans — a lightweight index, not a second database
Given "structured/queryable" is a real requirement (feeding the live run monitor, and a per-receipt audit screen pulling "the relevant slice"), a full linear scan of a day's file for one `run_id` doesn't scale as log volume grows. **A small SQLite index table** (`run_id`/`user_id` → file path + byte-offset ranges), separate from Persistence's own canonical database and explicitly not routed through Historian — this is purely a query-acceleration structure over the real data (the JSONL files), not a second copy of the log content itself, so it stays cheap to rebuild from the JSONL files if it's ever lost or needs to be regenerated after a format change.

### 3.3 Full traceback, always — a hard requirement, not a preference
File 01 states this plainly: **always captures full tracebacks on failure, never just `str(e)`** — async/threaded failures are hard enough to debug without losing the traceback, and `str(e)` alone discards the exact line, call stack, and chained-exception context that's often the only way to actually diagnose an issue that happened inside a `run_in_executor`-dispatched call three layers deep. Verbosity tiers (`TRACE`/`DEBUG`/`INFO`/`WARNING`/`ERROR`/`ATTENTION`) control *volume* of routine logging, never whether a failure's traceback gets captured — that's unconditional regardless of tier.

### 3.4 Classification and rendering hints are this API's job; actually *applying* them is a client's — a real boundary, restated precisely
Logs API ensures every `LogEntry` carries enough **structured classification data** (`level`, `service`, `run_id`) plus a **rendering hint** (`LEVEL_STYLE_HINT`, §3.1 — a suggestion like `"critical_persistent"`, not a Rich markup string or any client-specific formatting) for any client to make good visual decisions consistently. Logs API does not render anything itself, hold a socket open to a terminal, or know that Interface's TUI exists at all — it publishes data and a hint over `LogsService.Query` (§7) to whoever's listening. **This means Interface API's own run-monitor screen doesn't independently invent a color table that could drift from what Logs API actually defines its levels to mean** — it reads `LEVEL_STYLE_HINT` and translates each hint into whatever its own rendering technology can express (Rich markup, for the TUI specifically), rather than maintaining a second, parallel opinion about severity that a future change to Logs' own level definitions could silently leave stale. **Logs API runs as part of the main process regardless of any of this** — the hint exists for whichever client happens to be attached at a given moment, and Logs API's own writing/rotation/storage never pauses, degrades, or even notices whether such a client exists.

**`ATTENTION` is a genuinely new level, not a renamed `WARNING`**: it exists specifically for findings like Health API's capability-drift check (its deep-dive §4.3) — "this process is running below its own achievable baseline on infrastructure that exists to prevent exactly this," a categorically different kind of thing from "an operation failed" (`ERROR`) or "something's worth noting" (`WARNING`). Worth a level of its own, with its own distinct hint (`critical_persistent`, not just `critical`), so a client can give it real visual priority rather than it blending into an `ERROR`-colored stream a busy operator's eye has already learned to skim past.

---

## 4. Read access — same per-user rules as Persistence, cross-user is break-glass-gated
Logs contain real receipt content (OCR text, LLM prompts referencing actual receipt data), so read access follows the identical per-user permission model as Persistence and Search/Query's own deep-dives — a client can read their own logs, staff/owner cross-user access requires an active break-glass grant checked the same way Auth's `check_access()` already gates it (Auth deep-dive §6.3), not a separate permission mechanism invented here.

---

## 5. Retention
Day-rotated files past a configurable retention window get purged by a Background Workers idle-time job — unlike Audit's retention (explicitly left as a legal/business question in its own deep-dive), Logs' retention is a pure operational-cost tradeoff (disk space vs. debugging lookback window), reasonable to set a default for rather than needing legal input, since operational trace carries no compliance record-keeping obligation the way privileged-action audit does.

---

## 6. Asyncio
Rotated-file writes are non-blocking appends via `run_in_executor` or `aiofiles` — file 02's own table already classifies this API as pure async, the same shape as every other I/O-bound API in this batch. No compute-bound work of its own.

---

## 7. gRPC surface

```protobuf
service LogsService {
  rpc Query(LogQueryRequest) returns (stream LogEntry);   // server-streaming — a live tail view or a large historical pull both want this
}

message LogQueryRequest {
  string run_id = 1;
  string user_id = 2;      // for the permission check, §4
  string min_level = 3;
}
```

---

## 8. Config

```
logs:
  retention_days: 90
  verbosity_default: info
  verbosity_per_service:
    ocr: trace       # OCR/LLM raw output is genuinely high-volume, worth its own override
    inference: trace
```

---

## 9. Testing hooks
- **Traceback-capture regression**: a forced exception inside a `run_in_executor`-dispatched call, confirming the full traceback (not `str(e)`) lands in the log entry — direct validation of §3.3's hard requirement.
- **Index-rebuild test**: deleting the SQLite index and confirming it can be fully regenerated from the JSONL files alone — validates §3.2's "purely a query accelerator, not a second source of truth" design claim.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Exact retention default: 90 days, locked in.** A reasonable, defensible starting point for operational logs specifically (distinct from Audit's own 10-year regulatory retention, a genuinely different record type with different stakes) — real cost/usefulness data can tune this later, not a blocking gap.
- **TRACE-tier volume at real scale, resolved: its own separate, shorter retention.** OCR/LLM raw-output logging at `trace` verbosity is primarily useful for immediate debugging, not a long-term record — a 7-day retention window for `trace`-level entries specifically, independent of the standard 90-day default above, keeps the realistic volume bounded without needing a whole separate rotation mechanism, just a shorter TTL for that one verbosity tier.
