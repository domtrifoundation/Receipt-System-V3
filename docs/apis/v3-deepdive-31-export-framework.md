# V3 Deep Dive: Export Framework (Persistence sub-capability)

**Parent API:** `v3-deepdive-13-persistence-api.md` §7. **Companion files:** `v3-deepdive-06-account-guardian-api.md` §6.2 (`data_portability.py`'s consumer), `v3-deepdive-30-reimport.md` (the round-trip partner for `excel_general.py`).

**Status:** Sub-capability deep-dive, full treatment — including real BIR SLSP format research this project's earlier passes flagged as still needed.

---

## 1. Scope & boundary

Export Framework owns the **Provider Registry mechanism for exports** and each concrete export provider's own format logic. It does not:
- **own canonical data** — every provider reads from Persistence's own tables; none maintains its own copy or cache of business data.
- **decide when an export happens** — a user/staff action or Account Guardian's data-portability flow triggers a given provider; this framework just runs whichever one was asked for.

---

## 2. Package layout

```
core/persistence/exports/
  __init__.py
  contracts.py             # ExportProvider protocol, ExportResult, error types
  registry.py                 # which providers are registered
  providers/
    __init__.py
    excel_general.py            # general-purpose Excel export — see §3
    slsp_summary.py               # BIR SLS/SLP — see §4
    audit_package.py               # bundled evidence export — see §5
    data_portability.py             # Account Guardian's own consumer, see §6
    group_export.py                  # Groups' own feature, see §7
    quickbooks_export.py               # one-time IIF file, see §8
    xero_export.py                       # one-time CSV import file, see §8
  errors.py
```

```python
class ExportProvider(Protocol):
    async def generate(self, user_id: str, params: FrozenDict) -> ExportResult: ...

@dataclass(frozen=True)
class ExportResult:
    export_blob_ref: BlobRef
    format: str
    generated_at: datetime
```

---

## 3. `excel_general.py` — the print-friendly summary export
`openpyxl`, reusing V2's live-formula technique (Persistence deep-dive §7's own note) — a print-friendly summary sheet built as Excel formulas pulling from a raw-data sheet, rebuilt only when structure actually changes. The hidden snapshot-reference cell Reimport's own deep-dive (§3 there) relies on is written here, at generation time — this provider and Reimport's parser are a matched pair, one writing the reference, one reading it.

---

## 4. `slsp_summary.py` — real BIR format detail, researched properly rather than left as a placeholder

### 4.1 What SLSP actually is, precisely
**SLSP is two separate lists, not one document**: the Summary List of Sales (SLS) and Summary List of Purchases (SLP), submitted together but structurally independent reports, filed quarterly alongside VAT Form 2550Q. Real, current thresholds worth encoding as config rather than hardcoding into logic that might need updating if BIR revises them: sales list required above ₱2,500,000 in quarterly sales/receipts; purchases list required above ₱1,000,000 in quarterly purchases/importations net of VAT. **Required fields per entry, per current BIR guidance**: counterparty TIN, registered name, gross amount, and the VAT amount specifically broken out — not just a total.

### 4.2 Output format — DAT, not just Excel
The actual BIR-accepted submission format is a **DAT file** (a BIR-prescribed delimited electronic format, historically generated via BIR's own RELIEF facility or third-party accounting-software equivalents), not a plain spreadsheet — an Excel export alone wouldn't be directly submittable even though it's a genuinely useful working/review copy. This provider needs to generate **both**: a `.xlsx` working copy (for review before submission, using the same `openpyxl` path as `excel_general.py`) and the actual `.dat` file(s) in BIR's prescribed delimited format for real submission — two output artifacts from one provider call, not two separate export types.
```python
@dataclass(frozen=True)
class SlspResult:
    xlsx_review_copy: BlobRef
    sls_dat: BlobRef | None      # None if this user's quarter didn't cross the sales threshold
    slp_dat: BlobRef | None       # None if this user's quarter didn't cross the purchases threshold
```
**The exact byte-level DAT field delimiter/encoding spec needs primary-source confirmation before implementation** — this research pass confirmed *what* SLSP requires and *that* DAT is the real submission format, but not the precise field-order/delimiter specification a working DAT generator needs line-for-line correct; flagged honestly in §8 rather than guessed at from secondary sources, since a submission-format bug here has real compliance consequences.

---

## 5. `audit_package.py` — bundled evidence export
A zip bundle (Content Security's own container-bomb-check logic applies symmetrically here even though this is an *outbound* archive, not inbound — worth confirming the outbound bundle itself doesn't accidentally trip the same automated checks on the recipient's end, a real, easy-to-overlook detail) combining: the relevant receipts' own archival images (Persistence's blob store), a filtered Historian export covering just the receipts in scope, and an `excel_general.py`-style summary sheet — everything an auditor would plausibly want in one download, assembled from providers/mechanisms that already exist rather than needing new logic of its own.

---

## 6. `data_portability.py` — Account Guardian's own consumer, confirmed here
Already specified from Account Guardian's side (its deep-dive §6.2) as reusing this exact mechanism — full account scope (every table touching a user's own data), not the curated business view `excel_general.py` produces. Confirmed here as the concrete provider file that document's package layout already pointed to.

---

## 7. `group_export.py` — Auth API's Groups feature, surfaced during the Setup Sequence walkthrough
Pulls every receipt tagged with a given `group_id` (Groups' own design, `v3-deepdive-41-groups.md` §1), adding a contributing-user column (name/email, never raw `user_id`) to the same `excel_general.py`-style formula-driven summary sheet technique — reused, not reinvented, consistent with this framework's own point of existing. Access-gated by Groups' own rule (its deep-dive §4.1): callable only by the instance owner/staff or that specific group's `is_group_manager` members — this provider calls Groups' `ListGroupMembers`/permission check before generating anything, never trusts a bare `group_id` parameter on its own.

## 8. `quickbooks_export.py` / `xero_export.py` — one-time accounting exports, distinct from live sync
The genuinely simple half of accounting integration — a one-time file (QuickBooks' own IIF format, Xero's own CSV import layout) a user downloads and imports manually into their own accounting software, no OAuth or ongoing connection needed. **Deliberately kept separate from `v3-deepdive-50-accounting-sync.md`'s live-sync API** — that API owns credentialed, ongoing push; this is just another export format alongside `excel_general.py` and the SLSP summary, reusing this framework's own established pattern (pull canonical data, format it, done) rather than pulled into the more complex live-integration API's own scope.

## 9. Asyncio
Every provider is a Background Worker job (idle-time class for routine exports, immediate dispatch for a user-triggered download) — I/O-bound (reading Persistence, writing the output blob), no compute-heavy work of its own beyond `openpyxl`'s own row-generation cost, which is fast at this project's realistic per-export row counts.

---

## 10. Testing hooks — a real gap found during a pre-development sweep
- **Outbound archive-bomb symmetry test**: confirms `audit_package.py`'s own generated zip passes the same compression-ratio/size/entry-count checks Content Security applies inbound (§10's own resolution), rather than trusting generated output implicitly.
- **Excel formula-integrity test**: confirms the generated second-page summary sheet's live formulas actually reference the raw data sheet correctly after a regeneration, not just that the file opens.
- **SLSP threshold-currency test**: confirms the threshold values used come from config (Telemetrees-tracked, §10) rather than a hardcoded constant that would silently go stale if BIR revises them.

---

## 11. Open questions for this deep-dive (logged, not guessed at)
- **DAT file's exact byte-level format** (§4.2) — genuinely researched, with a real finding: the precise field-order/delimiter specification isn't publicly available even on direct request. A Freedom-of-Information request filed with BIR this same month (June 2026) asking for the complete SLSP technical specification (RMC-24-2002's own Annexes A-F) was denied — confirmed, dated evidence this isn't a lookup gap, the primary source isn't released to the public. The realistic path is reverse-engineering the format from a real, valid sample DAT file (via an accountant with RELIEF Data Entry Module access, or a BIR-compliant commercial tool), not reading documentation that doesn't exist publicly.
- **Outbound archive bomb-check symmetry, resolved: yes, the same discipline applies.** `audit_package.py`'s own zip generation goes through the identical basic sanity checks Content Security applies to inbound archives (compression ratio, cumulative size, entry count) — genuinely the same underlying risk (a mistakenly-huge bundle, however unlikely to happen on the generating side) and no real cost to applying the same guard symmetrically rather than trusting the generating code never to produce something degenerate.
- **SLSP threshold values as live-updatable config, resolved: a real Telemetrees tracked-fact entry.** Added to Telemetrees' own regulatory-change tracking category (`v3-deepdive-28-telemetrees-api.md`) — the same continuous-monitoring discipline already applied to dependency currency and capability drift, extended to "has BIR revised this threshold" as one more fact worth tracking rather than assumed static.
