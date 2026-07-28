# V3 Deep Dive: Receipt Detail & Historian Narrative Display (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` §5.2 (the section this document expands and replaces the brief version of).

**Companion files:** `v3-deepdive-29-historian.md` §6 (the narrative track this screen exists specifically to display — "displayable in the webapp" was that document's own stated design goal, never actually realized until this document), `v3-deepdive-46-client-data-layer.md` §4 (the query hook this screen consumes).

**Status:** New dedicated document, extracted per `docs/PRINCIPLES.md` §1.8's threshold — this is the single most information-dense screen in the application and the direct fulfillment of a design goal stated three documents ago and never followed through on until now.

---

## 1. Scope & boundary

This document owns the single-receipt detail screen — the image, extracted fields, and the interleaved Historian timeline. It does not:
- **own the underlying data** — every field shown here comes from Persistence's own canonical record and Historian's own `get_receipt_history()` (its deep-dive §6); this screen renders, it doesn't compute or derive.
- **own editing/correction flows** — a field correction on this screen routes through the normal write path (Persistence, with Historian logging the change automatically); this document owns the display and the trigger for an edit, not the write mechanism itself.

---

## 2. Layout — dual-pane, image and data side by side
Left pane: the receipt image itself (the archival blob, fetched via Persistence's own resolved `BlobLocation`). Right pane, tabbed: **Extracted Fields** (the current canonical values, editable) and **History** (§3 below). This split exists because the two panes serve genuinely different purposes — verifying the image against the extracted data is a different task from understanding how the system arrived at its current values, and collapsing them into one undifferentiated view would make both harder.

---

## 3. The History tab — Historian's narrative track, actually rendered
```typescript
function ReceiptHistoryTab({ receiptId }: { receiptId: string }) {
  const { data } = useReceiptHistory(receiptId);   // v3-deepdive-46-client-data-layer.md §4
  // data is the interleaved data-change/narrative timeline, already
  // ordered by Persistence's own get_receipt_history() — this
  // component renders it, doesn't re-sort or re-merge it
}
```
Each entry renders as one line in a vertical timeline, using the Design System's own primitives (`v3-deepdive-45-design-system.md`) — a data-change entry shows what field changed and who changed it; a narrative entry shows Historian's own quantized summary text ("OCR (Tesseract) read this receipt at 87% confidence") with its `LEVEL_STYLE_HINT`-equivalent visual treatment (the same hint-based approach Logs API's own ATTENTION-level design established, `v3-deepdive-18-logs-api.md` §3.1, reused here rather than this screen inventing its own severity-color mapping). **This is the concrete realization of Historian's own stated design goal** — a user or moderator diagnosing why a scan was processed the way it was, without needing origin-server Logs access, is what this tab specifically exists to deliver.

### 3.1 Rescans render as distinct, visually separated sequences
A receipt with a system-triggered rescan (Historian's own `RESCAN_STARTED` entry type, its deep-dive §7) shows its original narrative sequence and every subsequent rescan's own sequence as visually distinct blocks in the same timeline — never merged into one undifferentiated stream, consistent with Historian's own design intent that a rescan's narrative "coexists with the original scan's narrative, neither overwriting the other."

---

## 4. Live updates for an in-progress receipt
If the viewed receipt is still actively processing (a run in progress), this screen's History tab subscribes to the same streaming mechanism the Run Monitor view uses (`v3-deepdive-46-client-data-layer.md` §3) rather than requiring a manual refresh to see new narrative entries appear — a receipt detail screen opened mid-scan genuinely updates live as OCR/Inference/Matching produce their own narrative entries.

---

## 5. Asyncio/concurrency — not applicable in the Python sense
Same as every other webapp sub-API document — browser-side TypeScript.

---

## 6. Testing hooks
- **Interleaving fidelity test**: confirms this screen's rendered order exactly matches Persistence's own returned order — no client-side re-sorting introducing a discrepancy.
- **Live-update test**: confirms a narrative entry produced by an in-progress run appears in an already-open detail screen without a manual refresh — direct validation of §4.
- **Rescan visual separation test**: confirms two rescans of the same receipt render as distinguishable blocks, not one merged stream — direct validation of §3.1.

---

## 7. Open questions for this deep-dive (logged, not guessed at)
- **Long-history pagination, resolved: pagination, not virtualization.** Simpler to implement and sufficient at this project's actual scale — a "load more" action rather than infinite-scroll virtualization, which would be real added complexity this use case doesn't need.
- **Field-level "why did this change" drill-down, resolved: yes, included.** A genuinely low-cost, directly valuable UX improvement — clicking a specific extracted field jumps to its own relevant history entries rather than requiring a manual scroll through the full timeline, worth building into the initial design rather than deferred as a nice-to-have.
