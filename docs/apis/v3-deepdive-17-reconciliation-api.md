# V3 Deep Dive: Reconciliation API

**Companion files:** all prior deep-dives, especially `v3-deepdive-08-audit-event-log-api.md`'s flag-taxonomy ownership discussion and `v3-deepdive-13-persistence-api.md`'s Reimport sub-API (a real interaction point, §5 below).

**Status:** Seventeenth deep-dive session. File 01 explicitly flags this API as needing deeper fleshing-out — V2's `reconcile.py` has dozens of distinct real checks that never got a proper V3 design pass. This session gives it that pass, the same way Setup's deep-dive gave Disaster Recovery its first real design rather than deferring again.

---

## 1. Scope & boundary

Reconciliation owns two related things: **propagating corrections** (when Architect's registry data changes — a vendor's TIN gets fixed, a branch gets merged — pushing that correction to every affected receipt already in the canonical database) and **running validation checks** (VAT math, TIN format, date plausibility, and the rest of V2's real check inventory) that surface a Review/Flagging flag on a hit. It does not:
- **own the flag taxonomy** — Architect's registry defines what flag types exist (Audit deep-dive §1 already states this distinction); Reconciliation's checks *produce* flags of types Architect already registered, never inventing a new flag type inline.
- **own the learning mechanism** — a vendor's TIN getting corrected happens in Architect's `temporal_learning`; Reconciliation only reacts to that correction already having happened, propagating its consequences.
- **run as a competing scheduler** — every check and propagation batch runs on Background Workers' execution substrate (its own deep-dive), scheduled and routed by that API's per-job classification, not a Reconciliation-owned thread pool.

---

## 2. Package layout

```
core/reconciliation/
  __init__.py
  contracts.py            # CheckResult, PropagationJob, error types
  service.py                 # thin gRPC service implementation
  propagation.py               # correction-propagation logic, see §3
  checks/
    __init__.py
    base.py                     # ReconciliationCheck protocol
    vat_math.py
    tin_format.py
    date_plausibility.py
    account_outlier.py
    semantic_duplicate.py         # see §4.5 — distinct from Ingestion's exact-byte dedup
    vendor_group_mismatch.py
    items_vendor_mismatch.py
    bir_completeness.py
    orphaned_archive_reference.py
    geo_vendor_cross_reference.py
    atp_validity.py
  errors.py
  metrics.py
```

---

## 3. Correction propagation
Triggered by an Architect registry change (a vendor TIN correction, a branch merge) — Reconciliation subscribes to those change events (Historian's own event stream, filtered to Architect's tables, per Persistence's deep-dive §5) rather than polling for changes. A propagation job finds every receipt referencing the changed entity and applies the correction through Persistence's normal write path — meaning every propagated correction is automatically Historian-logged with `actor: "worker"`, distinguishable from a human's direct edit.
```python
async def propagate_correction(entity_type: str, entity_id: str, change: FrozenDict) -> PropagationJob:
    """Registered as a Background Workers job, class CPU_PROCESS if the
    affected-receipt count is large enough that finding+updating them is
    genuine CPU-bound work worth parallelizing (file 02's own table
    already flags bulk propagation sweeps as a real no-GIL/multiprocessing
    candidate, not just I/O)."""
```

---

## 4. The check inventory — V2's real precedent, mapped to concrete V3 logic

### 4.1 VAT math check
Philippine VAT is a fixed, computable relationship between VAT-exclusive amount, VAT amount, and VAT-inclusive total (12% standard rate) — a receipt whose printed subtotal/VAT/total don't reconcile to within a small rounding tolerance is a real, mechanical check, not a fuzzy one.
```python
def check_vat_math(subtotal: float, vat: float, total: float, tolerance: float = 0.02) -> CheckResult:
    expected_vat = round(subtotal * 0.12, 2)
    expected_total = round(subtotal + expected_vat, 2)
    if abs(vat - expected_vat) > tolerance or abs(total - expected_total) > tolerance:
        return CheckResult(flag_type="vat_math_mismatch", severity="medium")
    return CheckResult(flag_type=None)
```

### 4.2 TIN format check
BIR TINs follow a known structural format (9 base digits, optionally a 3-digit branch/RDO suffix, conventionally dash-grouped) — a regex-level structural check, not a validity check against BIR's own records (that would need an actual BIR lookup service this project doesn't have access to; this check catches OCR misreads and malformed entries, not fraudulent-but-well-formatted TINs).

### 4.3 Date plausibility check
A receipt date in the future, or implausibly far in the past relative to when it was actually scanned/uploaded, is very likely an OCR misread (a `7` read as a `1`, a two-digit year misparsed) rather than a real anomaly — worth a generous but real bound (e.g. flag anything more than a few days in the future, or more than several years old), not a strict same-day requirement that would false-positive on legitimate batch-processing of older receipts.

### 4.4 Account/category outlier check
A receipt whose amount is a statistical outlier relative to that vendor's/category's own historical distribution (not a fixed global threshold) — this needs Architect's own learned vendor-history data as an input, making this check a genuine consumer of Architect's registry rather than self-contained logic.

### 4.5 Semantic duplicate check — a real gap neither Ingestion's nor Background Workers' dedup mechanisms cover
Ingestion's content-hash dedup (its own deep-dive) catches exact byte-duplicate uploads; it does **not** catch two genuinely different image files (different photo, different compression) that represent the *same real-world transaction* — same vendor, same amount, same date, same transaction/receipt number if OCR extracted one. This is a real, distinct check worth its own logic here: a fuzzy match across a small set of high-signal fields (not image similarity — that's a harder, unaddressed problem both the Background Workers and Preprocessing deep-dives already flagged as genuinely open) catching the common case of someone re-uploading the same physical receipt via a different channel or accidentally scanning it twice.

### 4.6 Mislabeled vendor group / items-vendor mismatch
Both consume Matching API's own candidate-scoring output (its deep-dive) — a receipt whose items strongly suggest one vendor category (e.g. grocery items) but whose matched vendor is categorized differently is a real, catchable inconsistency, not a fuzzy-match confidence question alone.

### 4.7 BIR completeness check
Required-field presence per BIR documentation requirements (TIN, official receipt/sales invoice number, date, VAT breakdown) — a straightforward presence/format check, distinct from VAT math's *correctness* check.

### 4.8 Reimport conflict — surfaced, not owned, here
Persistence's Reimport sub-API (its own deep-dive §6) already owns diff/conflict detection for a reimported file against current canonical state — Reconciliation doesn't reimplement that logic, it's simply the API that turns a detected conflict into a Review/Flagging flag of the already-registered `reimport_conflict` type, the same "produce a flag, don't own the taxonomy" boundary as every other check here.

### 4.9 Malicious/unsafe content — surfaced, not re-checked
Content Security's own staff-confirmed verdict (Audit deep-dive §4's `CONTENT_CONFIRMED_MALICIOUS` action type) flows into a Review/Flagging flag the same way — Reconciliation never re-runs a security scan itself, it's purely a routing/surfacing step for a verdict another API already reached.

### 4.10 Orphaned/missing archive-reference detection — a real, previously-missed check, added during Background Workers' own correction pass
Was in the original job-inventory discussion (`v3-deepdive-12-background-workers-api.md` §6.3) and never actually made it into this check inventory — a clean miss, not a rename or a fold-in. A lighter-weight, ongoing idle-time sweep distinct from Disaster Recovery's own full-instance verification pass (`v3-deepdive-33-disaster-recovery.md` §4): catches the same category of problem (a receipt row referencing a `logical_id` with no corresponding `BlobLocation` mapping, or vice versa) at routine operating scale, on a regular idle-time cadence, rather than only during a catastrophic-recovery scenario. Reuses Disaster Recovery's own verification logic directly (same check, different trigger and scope — one receipt or a small batch here, not a full-instance walk) rather than reimplementing it.
```python
def check_orphaned_archive_reference(receipt_id: str) -> CheckResult:
    """Calls the same BlobLocation-existence check Disaster Recovery's
    own verify_restore() uses (its deep-dive §4), scoped to just this
    receipt's own logical_id rather than walking the entire instance.
    A hit surfaces a Review/Flagging flag — this check finds the
    problem, it doesn't attempt automatic repair, since a missing blob
    for a receipt that's supposedly already processed is exactly the
    kind of thing a human should look at before deciding what to do."""
```

### 4.11 Address/vendor geo-cross-check — the same capability the main run uses, applied backward to old receipts
**A real, previously-missing check, found while tracing Geo/Address API's own two legitimate callers** (`docs/PRINCIPLES.md` §1.9): this API is supposed to be able to call Geo/Address's own reverse-geocoding capability against already-written receipts, but no actual check in this inventory did so until now. Applies to a receipt whose address either never got a successful geo lookup during its own original run (skipped for budget reasons, or the lookup failed at the time), or whose vendor/address combination is worth re-checking because Geo/Address's own provider set or corroboration logic has genuinely improved since that receipt was originally processed.
```python
def check_geo_vendor_cross_reference(receipt_id: str) -> CheckResult:
    """Calls the identical underlying Geo/Address function Execution
    Core's own GEOD stage calls for new receipts (v3-deepdive-16-geo-
    address-api.md §1) — not a separate 'old receipt' implementation.
    A mismatch between the OCR-read vendor name and what's actually
    at the geocoded address is a real corroboration signal, surfaced
    as a Review/Flagging flag rather than auto-corrected, consistent
    with every other check in this inventory that finds a discrepancy
    without unilaterally deciding which side is right."""
```

### 4.12 ATP (Authority to Print) validity check — the twelfth and final check in this inventory
A real BIR audit red flag, raised fresh rather than inherited from V2: an expired Authority to Print on a vendor's receipt is exactly the kind of thing a BIR audit looks for. Most BIR-compliant receipts print the ATP number and its own validity period near the vendor's TIN — a field OCR already extracts alongside vendor/date/amount when present, not a new extraction capability this check needs of its own.
```python
def check_atp_validity(receipt_id: str) -> CheckResult:
    """Compares the receipt's own transaction date against its printed
    ATP validity window. A receipt dated outside that window is a real,
    flaggable BIR-compliance concern — surfaced via Review/Flagging,
    never auto-rejected, since a printed date being illegible or an
    ATP field OCR failed to capture at all is a genuinely different,
    softer case than a confirmed date-outside-window mismatch, and
    conflating the two would misrepresent the actual finding."""
```

---

## 5. Asyncio and profiling
Individual checks (§4.1-4.11) are mostly fast, pure-Python logic over already-fetched data — negligible either way per file 02's own table, with one real exception: §4.11's own geo lookup is a genuine network call (the same cost Execution Core's own `GEOD` stage already accounts for), so this specific check is I/O-bound rather than pure computation, budget-gated by the same caller-policy discipline Geo/Address's own deep-dive states (§1 there) rather than run unconditionally against every receipt in a sweep. **Bulk propagation** (§3) is the one place this API has genuine CPU-bound pure-Python work at real scale — a large "propagate this correction across N receipts" job is explicitly named in file 02 as a real no-GIL/multiprocessing candidate, dispatched through Background Workers' `CPU_PROCESS` class rather than this API building its own parallel-dispatch mechanism.

---

## 6. gRPC surface

```protobuf
service ReconciliationService {
  rpc RunChecks(RunChecksRequest) returns (RunChecksResponse);       // run the full check inventory against one receipt
  rpc PropagateCorrection(PropagateRequest) returns (PropagationJobResponse);
}

message RunChecksResponse {
  repeated CheckResult results = 1;   // one per check that ran, empty flag_type = passed
}
```

---

## 7. Testing hooks
- Each check in §4 gets its own labeled test fixture set (a known-bad VAT math receipt, a malformed TIN, an implausible date) — straightforward per-check regression coverage, given each check is a small, independently testable function.
- **Propagation atomicity test**: a correction propagation interrupted mid-batch (simulated crash) shouldn't leave some receipts corrected and others silently skipped without a retry — worth the same checkpoint-resume discipline Execution Core's own deep-dive (§6) already established, reused here rather than reinvented.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **Account/category outlier statistical method, resolved: IQR-based.** More robust than a z-score approach for financial data specifically, which is often meaningfully skewed rather than normally distributed (a handful of genuinely large legitimate purchases shouldn't blow out a z-score's own assumptions the way they would for a normal distribution) — a real, defensible starting method, not a coin flip between the two. Real calibration against actual data can still tune the specific multiplier later.
- **Semantic duplicate check's exact field-matching threshold, given a reasoned starting point.** Vendor + date (same day) + amount (within 1%, allowing for rounding/tax-display differences) as the field set, treated as a likely-duplicate candidate worth flagging — deliberately conservative (a real tuning pass can loosen or tighten this once real data shows the actual false-positive/false-negative balance), never auto-merged regardless of threshold, only ever flagged for review per this check's own existing design.
- **Propagation atomicity mechanism, actually wired through now, not just named as the right pattern.** Bulk correction propagation reuses Execution Core's own `run_stage()`/checkpoint mechanism directly (`v3-deepdive-10-execution-core-api.md` §6) — each receipt in a propagation batch gets its own checkpoint record, so an interrupted batch resumes from the last successfully-propagated receipt rather than restarting or silently skipping ones already done. The same mechanism, not a second implementation of "resume after a crash."
- **ATP (Authority to Print) validity checking, added as the twelfth check, closing this out for real.** A receipt's own printed ATP number and validity period are exactly the kind of field OCR already extracts alongside vendor/date/amount when present (most BIR-compliant receipts print this near the vendor's TIN) — the check verifies the receipt's own transaction date falls within the ATP's own printed validity window, flagging a mismatch the same way every other check in this inventory does. Genuinely check #12, not a hypothetical future addition.
- **Rescue-vs-flag-immediately, resolved with a real synthesis rather than picking one of the two named options.** Flag immediately (this document's own existing design, full transparency preserved) **and** let Rescue run as an optional idle-time follow-up *after* the flag already exists, not instead of creating it — if Rescue's own LLM-assisted retry succeeds while the flag is still sitting unaddressed in the review queue, the flag auto-resolves with a clear note explaining what Rescue did and why, giving a human reviewer the chance to catch it faster without ever losing the transparency (b) was chosen for in the first place. Genuinely the better of the two original options combined, not a compromise that gives up what either one was good at.
