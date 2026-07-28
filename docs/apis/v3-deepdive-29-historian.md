# V3 Deep Dive: Historian (Persistence sub-package)

**Parent API:** `v3-deepdive-13-persistence-api.md` §5. **Companion files:** `v3-deepdive-08-audit-event-log-api.md` §1 (the three-way distinction this document now sharpens further — see §2), `v3-deepdive-10-execution-core-api.md` §6 (the actual emission chokepoint for the narrative track, §4 below), `v3-deepdive-18-logs-api.md` (the full-verbosity, server-only counterpart this track is deliberately *not*).

**Status:** Revised — scope substantially expanded from the original version. Historian isn't just a data-change audit trail; it's the full narrative of a scan's lifetime, quantized for remote display, from first ingestion through every pipeline stage's own deliberation to the final write — and every subsequent human audit or system rescan after that.

---

## 1. Scope & boundary

Historian owns **two related but structurally distinct tracks**, both append-only, both living in the same database, both queryable together as one chronological per-receipt history:
- **The data-change track** (unchanged from the original design) — table/row/before/after for every logical write to canonical data, atomic with the write itself.
- **The narrative track** (new, this revision) — a quantized, human-readable account of every pipeline stage a receipt passed through: ingestion, preprocessing, each OCR engine's own reading and confidence, corroboration's outcome, matching, geocoding, the LLM's own deliberation and confidence, any flag raised, the final write — starting at first scan and continuing through every subsequent human audit or system-triggered rescan.

It does not:
- **track privileged/security actions** — still Audit API's job, a structurally separate database for a structurally different kind of event.
- **duplicate Logs API's full verbosity** — this is the load-bearing distinction for the narrative track specifically, worth stating as a hard rule rather than a preference: Historian's narrative is **quantized and summarized by design** — "Tesseract read this receipt at 87% confidence" is a narrative entry; the actual raw OCR text, the full LLM prompt/response, and detailed timing data are Logs' own territory, full-verbosity, gitignored, **origin-server-only, never surfaced to the webapp**. Historian's narrative is deliberately the *readable digest* of what Logs records in exhaustive detail — the two are companions at different resolutions, not competitors, and a developer extending either needs to keep that resolution difference intact rather than letting Historian's narrative creep toward Logs' own verbosity (which would both bloat the canonical database and start leaking server-internal detail to a remote audience).
- **provide disaster recovery** — the day-rotated `.sqlite` snapshot checkpoints are Persistence's own recovery mechanism, unchanged.

---

## 2. Sharpening the three-way distinction, now that Historian has two tracks of its own
Restating Audit's own framing (its deep-dive §1) with the added nuance this revision introduces:
- **Logs** — everything, full detail, origin-server-only. Answers "what exactly did the system do, byte for byte."
- **Historian's data-change track** — structured before/after on canonical rows, origin-server *and* webapp (a user's own data, or staff under break-glass). Answers "how did this receipt's stored fields get to their current values."
- **Historian's narrative track** — quantized, human-readable, webapp-displayable. Answers "what happened during this scan, and why did the system conclude what it concluded" — the specific gap neither Logs (too detailed, too private) nor the data-change track (only covers final canonical writes, not the deliberation that produced them) actually filled. A per-engine OCR confidence or the LLM's stated reasoning-summary for flagging something never becomes a canonical data-table write at all (only the *corroborated, final* result does) — meaning without this track, that whole deliberation trail was invisible to anyone without direct Logs access, which is exactly the gap this revision closes.
- **Audit** — privileged/security actions, a separate database entirely, unchanged.

---

## 3. Package layout

```
core/persistence/historian/
  __init__.py
  contracts.py            # HistorianEvent (data-change), NarrativeEvent (new), NarrativeStage
  writer.py                  # same-transaction event insertion, both tracks
  narrative/
    __init__.py
    summarizers.py             # per-stage raw-result → NarrativeEvent, see §5
  query.py                    # interleaved chronological lookup — see §6
  github_mirror.py              # optional, unchanged from prior version
  errors.py
```

---

## 4. The narrative track's data contract

```python
class NarrativeStage(str, Enum):
    RUN_STARTED = "run_started"
    INGESTED = "ingested"
    PREPROCESSED = "preprocessed"
    OCR_ENGINE_RESULT = "ocr_engine_result"     # one event per engine reading, not one per stage
    OCR_CORROBORATED = "ocr_corroborated"
    MATCHED = "matched"
    GEOD = "geod"
    INFERENCE_DELIBERATED = "inference_deliberated"
    FLAGGED = "flagged"
    WRITTEN = "written"
    RESCAN_STARTED = "rescan_started"             # see §7

@dataclass(frozen=True)
class NarrativeEvent:
    event_id: str
    receipt_id: str
    run_id: str
    stage: NarrativeStage
    summary: str                # the human-readable line — "OCR (Tesseract) read this receipt at 87% confidence"
    detail: FrozenDict            # structured, quantized facts backing the summary — engine name, confidence, agreement level. NEVER raw OCR text, full prompts, or anything Logs-resolution — see §1's hard rule
    occurred_at: datetime
    triggered_by: str              # "initial_scan" | "user_rescan:<user_id>" | "system_rescan:<reason>" — see §7
```

---

## 5. Emission — one chokepoint, not scattered calls across every pipeline API
The real design risk with "every step gets a narrative entry" is ending up with N different APIs each independently remembering (or forgetting) to call Historian. **Resolved by reusing a chokepoint that already exists for an unrelated reason**: Execution Core's own `run_stage()` checkpoint wrapper (its deep-dive §6) already sits at the exact right point — every pipeline stage's call and its output already flow through it for resumable-retry purposes. Extending it to *also* emit a narrative event as part of that same wrapper means every stage is covered automatically, by construction, the same way every canonical write already goes through Historian's data-change track by construction (§3 of the original design).

```python
# execution_core/checkpointing.py — extended, see that document's own §6 for the base version
async def run_stage(run_id: str, receipt_id: str, stage: ReceiptStage, fn: Callable) -> Any:
    existing = await get_checkpoint(receipt_id, stage)
    if existing is not None:
        return existing.stage_output_ref
    result = await fn()
    await write_checkpoint(run_id, receipt_id, stage, result)
    await _emit_narrative(run_id, receipt_id, stage, result)   # new — narrative_summarizers.py turns the raw stage output into one or more NarrativeEvents
    return result
```
`narrative/summarizers.py` holds one small function per `ReceiptStage`, each knowing how to turn that stage's own result type into a `NarrativeEvent` (or several — OCR's own summarizer emits one `OCR_ENGINE_RESULT` event per `EngineReading` in the corroborated `OcrResult.readings`, plus one `OCR_CORROBORATED` event for the merged outcome, directly matching the user-facing example: "OCR x scanned with a confidence of... OCR y has a confidence of..."). This keeps the summarization logic centralized and reviewable in one small module rather than scattered as ad hoc narrative-writing code inside OCR/Inference/Matching/Geo's own implementations, which each stay focused on their own domain logic and never need to know Historian's narrative track exists at all.

### 5.1 A real, concrete gap this surfaced in OCR's own contract — applied, not just flagged
Writing `OCR_ENGINE_RESULT`'s summarizer surfaced that `EngineReading` (OCR deep-dive §3) had no aggregate per-engine confidence field — only `TextRegion.confidence` at the individual-region level, buried inside `regions`. A one-line narrative ("Tesseract read this receipt at 87% confidence") needs a single number, not a list of per-region scores to average inline. **Fixed, applied directly to `v3-deepdive-01-ocr-api.md`'s own `EngineReading` contract**: `mean_confidence: float | None` — the mean of its own `regions[].confidence` where region-level data exists, `None` for engines that only return plain text with no confidence signal at all (Windows OCR, the tier-0 text-layer extractor). Computed once by the engine's own wrapper at the point `EngineReading` is constructed, not recomputed ad hoc by every consumer that wants a summary number.

---

## 6. Query — interleaved, chronological, both tracks together
```python
async def get_receipt_history(receipt_id: str) -> tuple[HistorianEvent | NarrativeEvent, ...]:
    """Both tracks, merged and sorted by occurred_at — a receipt's full
    story in one timeline: 'Scan started on run #4821 on 2026-07-17
    14:32' → 'Preprocessing: standard + high-contrast variants
    generated' → 'OCR (Tesseract): 87% confidence' → 'OCR (RapidOCR):
    91% confidence' → 'OCR corroborated: unanimous agreement, 91%
    confidence' → 'Matched: ABC Corp (94% match)' → 'Geocoded: address
    confirmed' → 'Inference deliberated: confident extraction, no
    flags' → 'Written to canonical record' — interspersed with any
    later data-change events (a human correction) or a subsequent
    RESCAN_STARTED entry, in the same single feed."""
```
This is the mechanism directly answering the stated goal: diagnosing why a specific file was processed the way it was, without needing origin-server Logs access — the whole deliberation trail, at narrative resolution, in one place.

---

## 7. Rescans and ongoing history after the initial scan
The narrative track isn't a one-time record written at ingestion and then frozen — it's the receipt's **entire lifetime**. After the initial scan's narrative completes, further entries come from exactly two sources, both captured via `triggered_by`:
- **A human user's own audit/edit** — when someone corrects a field (Review/Flagging's edit-entry-point, its deep-dive §3), that's already a data-change event on the other track; worth also emitting a short narrative line ("User corrected vendor name") so the *unified* timeline (§6) reads coherently rather than having a silent gap where the data-change track has an entry but the narrative track doesn't.
- **A system-triggered rescan** — Execution Core re-running the pipeline against an already-processed receipt (a newly promoted OCR engine, a Reconciliation-triggered reprocessing, a user-requested "rescan this") produces a fresh, full narrative sequence starting with `RESCAN_STARTED`, tagged with why (`system_rescan:new_ocr_engine_promoted`, `system_rescan:reconciliation_escalation`, etc.) — the full original narrative stays intact underneath it, never overwritten, so a receipt's history shows both the original deliberation and every subsequent one.

---

## 8. Access control — the same rules already established elsewhere, not a new mechanism
The narrative track (and the data-change track) are visible to: the receipt's own owning user, always (it's their own data's story); staff/owner under an active break-glass grant for cross-user access, checked the same way Search/Query's own permission gate already works (its deep-dive §4) — no new access-control mechanism invented here, this reuses what's already consistent everywhere else in this project.

---

## 9. Same-transaction atomicity — unchanged for the data-change track, and why it's looser for the narrative track
The data-change track keeps its original hard guarantee: `write_with_history()` commits the data write and its Historian event atomically, in one transaction (unchanged from the original design — see §3's original code sketch, still correct). **The narrative track is deliberately not held to the identical atomicity bar**: it's written by Execution Core's checkpoint wrapper (§5), not inline with a canonical data write, so a narrative event and its corresponding checkpoint are atomic with *each other*, but the narrative event isn't required to be atomic with the eventual final canonical write at the `WRITTEN` stage the way a direct data edit is. This is an acceptable, deliberate looseness: a crash between a stage completing and its narrative being recorded means, worst case, one missing narrative line for a receipt that gets retried anyway (Execution Core's own bounded-retry-with-checkpointing design already handles the retry correctly regardless) — a far smaller consequence than a canonical data write landing without its audit record, which is what the original hard guarantee actually exists to prevent.

---

## 10. GitHub mirror — unchanged, now covers both tracks
File 01's own framing still applies: an optional export/mirror for anyone who wants off-site durability or `git log`-style browsing, via a Background Worker idle-time job, never a dependency the core write path relies on. Now mirrors both the data-change and narrative tracks together, same chronological interleaving as the live query (§6).

---

## 11. Asyncio
Inherits Persistence's own async SQLite wrapper, same as the original design — the narrative track's writes happen inside Execution Core's own already-async stage-orchestration flow (its deep-dive §10.1), no new concurrency model needed.

---

## 12. gRPC surface
```protobuf
service PersistenceService {
  // ... existing RPCs ...
  rpc GetReceiptHistory(ReceiptHistoryRequest) returns (ReceiptHistoryResponse);   // interleaved, both tracks
}

message ReceiptHistoryResponse {
  repeated HistoryEntry entries = 1;   // a oneof-shaped union of HistorianEvent and NarrativeEvent, sorted chronologically
}
```

---

## 13. Testing hooks
- **Atomicity test** (data-change track, unchanged): a simulated crash between a data write and its event insertion confirms neither lands.
- **Full-pipeline narrative coverage test**: a synthetic run through every `ReceiptStage` confirms a `NarrativeEvent` was emitted for each one, including one `OCR_ENGINE_RESULT` per enabled OCR engine — the concrete check that Execution Core's chokepoint (§5) is actually catching every stage, not silently missing one.
- **Verbosity-leak test**: a regression check scanning `NarrativeEvent.detail` payloads for anything that looks like raw OCR text or LLM prompt content (a length/entropy heuristic, or simply asserting the summarizer functions never touch those fields at all) — the concrete enforcement of §1's hard "quantized, never Logs-resolution" rule, not just a documented intention.
- **Rescan continuity test**: confirms a system-triggered rescan's fresh narrative sequence coexists with the original scan's narrative in the same receipt history, neither overwriting the other.

---

## 14. Open questions for this deep-dive (logged, not guessed at)
- **Narrative summarizer coverage for Matching/Geo/Inference, given real design rather than left as "named but not designed."** Each follows the same pattern OCR's own summarizer already established (§5) — turn that stage's own result type into one readable line: Matching produces "Matched to [vendor] — [score]% confidence, [N] candidates considered"; Geo/Address produces "Address confirmed at [location]" or "Address/vendor mismatch flagged" depending on outcome; Inference produces "Extracted [field count] fields, schema-valid" or names the specific validation failure if the `LENGTH`-retry path was needed. Each summarizer lives in the same `historian/narrative/summarizers.py` module OCR's own already does, one function per stage's own result type, called through the identical `run_stage()` chokepoint (§5) — no new integration pattern needed, just the remaining summarizer functions actually written.
- **GitHub mirror commit granularity, resolved: one commit per contribution-review decision, not per individual field change.** A single approve/reject action on a `Contribution` (temporal_learning's own moderation pipeline, `v3-deepdive-40-temporal-learning.md` §6) is one commit, even if that contribution touches multiple fields — matching the actual reviewable unit a staff member acted on, so the git history reads as a real decision log rather than a noisy field-by-field diff stream that obscures what was actually being decided each time.
- **Query performance at real scale, remains a genuine pre-launch bench task, not a design gap.** The interleaved two-track query mechanism is designed; whether it holds up under realistic receipt-history volume per user needs real data to confirm, the same category as every other "reasoned, not yet measured" item in this corpus.
