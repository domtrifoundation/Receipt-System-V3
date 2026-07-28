# V3 Deep Dive: Persistence API

**Companion files:** all prior deep-dives — `BlobRef` has been used as a first-class type across every single one of them; this document is where it's finally formally defined, along with the five sub-packages (Historian, Reimport, Export Framework, Archive Sync, Disaster Recovery) that have each been referenced in prose but never given their own package/contract shape.

**Status:** Thirteenth deep-dive session. Mixed lineage — the SQLite/blob-store core has real V2 precedent worth reacting to (V2's actual `excel_backup.commit_all()` git-backup-on-every-write pattern, now fully superseded by Historian's atomic transaction approach); Disaster Recovery has explicitly none, flagged in file 01 as "genuinely new territory... needs its own deep-dive" — this session gives it that first real pass.

---

## 1. Scope & boundary

Persistence owns **all disk access** — nothing else in this system touches disk directly. Two storage mechanisms: a canonical per-user SQLite database (structured records, WAL mode) and a content-addressable blob store (raw/archival images). It does not:
- **decide what schema/taxonomy exists** — that's Architect API's registry (file 01 #25, rule #7's binding constraint); Persistence stores instance values against whatever types Architect has registered, never invents its own parallel taxonomy.
- **implement search logic beyond hosting the tables** — Search/Query API (its own future deep-dive) owns the actual FTS5 query logic; the tables live in Persistence's own database because a separate synced copy would be redundant infrastructure, not because Persistence owns search.
- **decide export *content*** — Export Framework (§7) provides the mechanism; what a given export actually contains is each export provider's own concern.
- **decide group access rules** — a receipt row carries an optional `group_id` column, stamped at write time from Groups' own `GetEffectiveGroup()` call (its deep-dive §5), but *who's allowed to query across a group* is Groups' own permission rule (§4.1 there) and Search/Query's own enforcement (its deep-dive §4), not something Persistence itself gates — Persistence just stores the tag faithfully.

---

## 2. Package layout

```
core/persistence/
  __init__.py
  contracts.py             # BlobRef, Receipt, ReferenceIdentifier, error types — the canonical BlobRef definition
  service.py                  # thin gRPC service implementation
  db/
    __init__.py
    connection.py               # WAL-mode SQLite connection, async wrapper — see §3
    schema.py                     # table definitions, ties into Migration API's schema_version
  blob_store/
    __init__.py
    store.py                     # content-addressable read/write — see §4
    backup/
      __init__.py
      base.py                     # BackupTarget protocol — Provider Registry
      b2_target.py
      storj_target.py
  historian/                  # Sub-package — see §5
    __init__.py
    writer.py
    query.py
  reimport/                   # Sub-API — see §6
    __init__.py
    diff.py
    conflict_resolution.py
  exports/                    # Sub-capability: Export Framework — see §7
    __init__.py
    registry.py
    providers/
      excel_general.py
      slsp_summary.py
      audit_package.py
      data_portability.py         # consumed by Account Guardian's deep-dive §6.2
  archive_sync/               # Sub-capability — see §8
    __init__.py
    sync.py
  disaster_recovery/          # Sub-API — see §9, first real design pass
    __init__.py
    restore.py
    verify.py
  errors.py
  metrics.py
```

---

## 3. The canonical database

### 3.1 WAL mode and the async wrapper
`sqlite3`'s WAL (Write-Ahead Logging) mode is what makes safe concurrent access possible at all — readers don't block writers, writers don't block readers, at the cost of a small amount of extra disk I/O for the WAL file itself. This is a per-database `PRAGMA journal_mode=WAL` set once at creation, not a per-connection toggle. Python's `sqlite3` module is blocking by nature — every deep-dive in this project that touches SQLite (Auth's sessions, Audit's events, this API's own canonical data) needs the same `run_in_executor`-wrapped async pattern, worth a single shared internal utility (`common/async_sqlite.py`) rather than four independent reimplementations of the same wrapper, consistent with the "shared plumbing, separate domain logic" principle already established for the OCR/Inference ONNX substrate.

### 3.2 Schema versioning ties directly into Migration API
Every table carries a `schema_version` (Migration API's own deep-dive, file 01 #20) — migrations write through this API's own normal write path, meaning each migration is automatically an atomic, Historian-logged event with no separate rollback machinery needed. Worth stating precisely: a migration isn't a special kind of write, it's an ordinary write that happens to touch schema-defining rows, so it gets the same atomicity/audit guarantees every other write already has for free.

### 3.3 `BlobRef` — corrected: stable logical identity, separate from physical storage address
The original version of this contract used the same hash for both "permanent identity" and "storage filename" — a real bug, caught late: once the original uploaded bytes are deleted (this project's actual retention policy — originals are kept briefly, then purged, only the re-encoded archival copy survives long-term), a file addressed by its *original* bytes' hash no longer matches what's actually stored under that name. That breaks genuine content-addressability (the address should always be derivable from what's actually there) and specifically breaks Disaster Recovery's own verification step (§4.3 there), which recomputes a stored file's hash and checks it against its own filename — a check that would fail for every blob, permanently, the moment originals get purged, not just after a codec change.

**Fixed with one added layer of indirection:**
```python
@dataclass(frozen=True)
class BlobRef:
    logical_id: str          # SHA-256 of the ORIGINAL uploaded bytes — permanent, stable identity. Every reference anywhere in the system (SQLite rows, Historian events, Audit events, exports, narrative events) uses this and only this. Never used to locate a file directly.

@dataclass(frozen=True)
class BlobLocation:
    logical_id: str            # foreign key into the mapping below
    physical_hash: str           # SHA-256 of what's ACTUALLY stored on disk right now — this IS the real filename/path (§4.2's sharded layout), always genuinely self-verifying
    codec: str                    # "webp" | "avif" | "original"
    updated_at: datetime
```
```python
async def resolve_blob_path(logical_id: str) -> Path:
    """logical_id → blob_locations (one indexed SQLite lookup) → physical_hash → the real sharded-by-prefix disk path (§4.2). Every consumer that needs actual bytes goes through this, never assumes logical_id is a filename."""
```
`stored_encoding` is no longer a field on `BlobRef` itself — it was a mutable fact (the codec can change) living on what was supposed to be an immutable-looking frozen dataclass, the same category of bug the project-wide `FrozenDict` policy exists to catch, just one level up (a mutable *fact about* a record, not a mutable field *within* one). It now lives on `BlobLocation` instead, where it belongs: a fact about current physical storage, looked up through the mapping, never assumed permanent.

**What this actually buys**: the original can be purged on whatever retention schedule the ingestion pipeline uses, and nothing that references `logical_id` — which is everything, everywhere — ever needs to change, because none of those references were ever pointing at the original's own storage location in the first place. A future owner-initiated codec change becomes an explicit, bounded migration job that updates `blob_locations.physical_hash`/`.codec` in bulk, never a mass rewrite of every historical reference across Historian, Audit, and every export that's ever been generated.

**Canonical data retention, confirmed against real research rather than left implicit**: this document never states an expiry/purge policy for the archival copy or canonical SQLite records — receipts are kept indefinitely by design. Checked against actual Philippine legal requirement rather than assumed: BIR's RR No. 17-2013 (amended by RR 5-2014) requires taxpayers to preserve books of accounts and accounting records — invoices, receipts, vouchers, source documents — for **ten years** from the relevant tax return's filing deadline. This design's own "keep archival data indefinitely, never auto-purge" already satisfies that requirement with real margin, confirmed correct rather than accidentally sufficient — worth stating explicitly now rather than leaving it an unstated assumption.

---

## 4. The blob store

### 4.1 Content-addressable, hashed on original bytes — restated with the corrected logical/physical split
The hash is computed over the **original uploaded bytes, before any re-encoding** — an immutable lookup/dedup key (`logical_id`, §3.3) decoupled from whichever archival codec is currently the system-wide choice, and decoupled from whether the original bytes even still exist on disk anywhere. **This section's original phrasing — "only the stored bytes under a hash would ever need to change, never the address itself" — undersold the actual mechanism**: it's not that a hash-named file's *contents* silently change while keeping the same name (that would break real content-addressability); it's that `logical_id` was never the storage address at all, only a stable key resolved through `BlobLocation` (§3.3) to whatever the current, genuinely self-consistent `physical_hash` is. The file on disk is always exactly what its own filename claims it is.

### 4.2 File layout — sharded by hash prefix, the standard technique — now applies to `physical_hash`, not `logical_id`
```
blobs/
  ab/
    cd/
      abcd1234...ef.webp
```
Two levels of two-hex-character sharding (the same technique Git's own object store and most content-addressable systems use) — keeps any single directory from accumulating an unmanageable number of entries as the blob count grows into the hundreds of thousands, a real filesystem-performance concern at scale that's cheap to avoid from day one rather than retrofit later.

### 4.3 Purely immutable, no embedded metadata — a considered-and-reversed decision worth preserving the reasoning for
File 03's own decisions log records a genuine design fork here: embedding vendor/amount/category into standard Windows-Explorer-recognized fields (Title/Tags/Comments via EXIF/XMP) was scoped, and a real fix for the obvious problem (tagging a file changes its bytes, which would change its hash) was even designed — an immutable hash-addressed original plus a separate regenerable "browsable copy" carrying the tags. **Reversed anyway**, in favor of keeping blobs purely immutable with zero embedded metadata, because browsing/sorting/filtering is fully handled by the webapp via Search/Query's structured SQLite data — simpler, and not limited to single-user/self-hosted mode the way an Explorer-only solution structurally would be. Worth preserving this reasoning rather than just the conclusion, since "we could make Explorer sortable" is a genuinely tempting idea that's worth having a ready answer for if it resurfaces.

### 4.4 Backup — Provider Registry, parallel targets, not one-at-a-time failover
B2 and Storj run **in parallel**, both genuinely active simultaneously — this project's Provider Registry pattern (rule #5) explicitly calls out blob backup targets as a named example of "more than one provider enabled at once... not a single config value swapped one-at-a-time." A blob write completes to the local store first, then fans out to every enabled `BackupTarget` — a write isn't considered durably backed up until enabled targets confirm, but local write success and remote backup confirmation are tracked as separate states, not conflated into one "saved" flag. **A real, previously-missing check now exists**: Disaster Recovery's own verification logic (its deep-dive §4) only ever ran during an actual restore — there was no ongoing, routine confirmation that these backup targets stayed genuinely retrievable in between. A weekly blob backup spot-verification job (Background Workers' own consolidated registry, `v3-deepdive-12-background-workers-api.md` §6.4) now pulls a small random sample and reuses that same per-blob check at routine scale, catching a silently-broken backup target long before an actual disaster would force the question.

---

## 5. Historian sub-package
**Full treatment in `v3-deepdive-29-historian.md`.** Scope significantly expanded beyond the original data-change-only design: Historian now owns two tracks — the original data-change audit trail below, plus a **narrative track** covering a receipt's entire processing lifetime (every OCR engine's confidence, corroboration outcome, matching/geocoding results, the LLM's own deliberation, any flag raised) at a quantized, human-readable resolution deliberately lighter than Logs API's full verbosity — and, critically, **displayable in the webapp**, unlike Logs which stays origin-server-only. This is what lets a user or moderator remotely see *why* a given scan was processed the way it was, not just what its final canonical values ended up being. Summary of the original data-change track below; see the full document for the narrative track's design.
Already fully reasoned through in file 03's own correction record (Historian was originally proposed as a standalone API with a parallel git-committed event log, then correctly retired once traced through: the live `.sqlite` file was never going to be git-tracked anyway, so a parallel git record bought none of git's actual benefits, and the real consumer — the webapp — queries through an API regardless of whether the underlying storage is git or SQL). Formalized here as a schema:
```python
@dataclass(frozen=True)
class HistorianEvent:
    event_id: str
    table_name: str
    row_id: str
    before: FrozenDict | None      # None for an INSERT
    after: FrozenDict | None        # None for a DELETE
    actor: str                       # "worker" | "llm" | "human:<user_id>"
    program_version: str
    occurred_at: datetime
```
Lives in the *same* database, same transaction boundary as the data write itself — both commit atomically together, a guarantee two separate services could never give. `before`/`after` use `FrozenDict` per the project-wide policy (Tool Call API deep-dive §6), consistent with every other contract in this batch that carries structured, dict-shaped data across an API boundary.

---

## 6. Reimport sub-API
**Full treatment, including the resolved conflict-resolution policy, in `v3-deepdive-30-reimport.md`.** Summary below.
Already scoped precisely in the Ingestion deep-dive's corrections session and reaffirmed there as staying under Persistence rather than moving to Ingestion, since diffing against canonical state and resolving conflicts is a Persistence-write concern. `diff.py` computes a field-level diff between the reimported file's contents and current canonical state; `conflict_resolution.py` handles the case where canonical state changed since the export was generated (a real, expected scenario given the export-then-edit-then-reimport round trip can span real time). **Resolved: every conflict flags for human review** — no automatic last-write-wins, no rejecting the whole reimport over one conflicting field. Full design in that document's own §6.

---

## 7. Export Framework
**Full treatment, including real BIR SLSP format research, in `v3-deepdive-31-export-framework.md`.** Summary below.
Provider Registry applied to exports (file 01) — each export type is a registered provider consuming the same canonical data, not a hardcoded one-off per format. `data_portability.py` is the provider Account Guardian's deep-dive (§6.2) already specified as reusing this exact mechanism rather than inventing a parallel data-dump path — confirmed here as the concrete file this document's package layout places it in.

---

## 8. Archive Sync sub-capability
**Full treatment in `v3-deepdive-32-archive-sync.md`.** Summary below.
The inverse of Ingestion — mirrors processed receipts *out* to an external drive provider, one-way (internal → external), the external copy never a second source of truth. Reuses Ingestion's own swappable Drive-credential-strategy pattern (its deep-dive §4.1) rather than building a separate credential mechanism, and where possible reuses the same connection a user already granted for Drive *ingestion* rather than asking them to authorize a second time for the *outbound* direction.

---

## 9. Disaster Recovery
**Full treatment (this section's first pass expanded further, including a more precise partial/single-user restore resolution) in `v3-deepdive-33-disaster-recovery.md`.** Summary below.
File 01 is explicit this has no V2 equivalent and needs its own deep-dive; this section is that pass, not a placeholder pointing further down the road again.

### 9.1 Scope: full-instance restore, not the smaller mechanisms already covered elsewhere
Distinct from three things it's easy to conflate with: the backup *mechanisms* (§4.4 — B2/Storj replication, already just "how a blob gets copied out," not a restore procedure); Reimport (§6 — single-user data reconciliation against canonical state, not instance-level restore); Historian (§5 — an audit trail of changes, not a mechanism for reconstructing a database from backups at all). Disaster Recovery is specifically: **given a catastrophic loss of the running instance's own disk, rebuild a working instance from the B2/Storj blob backups and the SQLite snapshot backups.**

### 9.2 Restore ordering — blobs before SQLite, and why
```python
async def restore_instance(target_dir: Path, snapshot_id: str) -> RestoreResult:
    """1. Restore the blob store first, fully, from backup targets.
       2. THEN restore the SQLite snapshot.
       3. Verify every BlobRef the restored SQLite data references
          actually exists in the restored blob store (§9.3) — this
          ordering makes that verification meaningful; verifying blob
          references against a not-yet-restored blob store would be
          checking against an empty directory and prove nothing."""
```
Restoring blobs first, then the database, is the only ordering that makes the verification step in §9.3 actually mean something — if the database were restored first, "does every referenced blob exist" would trivially fail against an empty blob store regardless of whether backups are actually intact.

### 9.3 Post-restore verification — a real, necessary step, not assumed automatic
A successful-looking restore isn't the same as a *correct* one — backup corruption, a partial/interrupted backup cycle, or a version mismatch between the SQLite snapshot's expected blob set and what actually made it to backup are all real failure modes a restore procedure needs to actively check for, not discover later when a user tries to view a receipt and the image is missing.
```python
async def verify_restore(restored_dir: Path) -> VerificationReport:
    """Walks every BlobRef referenced anywhere in the restored SQLite
    data, confirms the corresponding blob file exists AND its own
    SHA-256 matches the hash in its filename/path (catching silent
    backup corruption, not just missing files). Reports orphaned
    references (a BlobRef with no corresponding blob) as the
    restore's own explicit failure list — never silently accepted as
    'mostly worked.'"""
```

### 9.4 Partial or single-user restore — a genuine open question, not resolved by assumption
Whether a partial restore (one user's data, not the whole instance) is ever a supported operation short of a full-instance rebuild is a real design fork worth being honest is unresolved: a single-user restore sounds appealing (a user's own disk issue shouldn't require restoring everyone), but this project's SQLite-per-user-folder isolation model (Auth deep-dive §5.2's placement reasoning, applied structurally everywhere) means a single user's database genuinely *is* independently restorable in principle — the real question is whether cross-user consistency (e.g., a global vendor-contribution moderation queue in Architect's own database, referenced by many users) has any single-user-restore edge cases worth designing around now versus deferring until it's a real, requested capability. Flagged in §10 rather than guessed at.

---

## 10. Asyncio, free-threading, and profiling — a real gap found during a pre-development sweep, not present in the original document
**This section was genuinely missing**, despite the concurrency classification being a standing hygiene requirement every PR template in this project enforces (`docs/PRINCIPLES.md` §5, `v3-plan-02-architecture.md`'s own per-API table) — worth noting plainly rather than quietly backfilling, since a major Core API missing it is exactly the kind of thing that erodes a hygiene rule's credibility.

**Classification: async I/O throughout**, matching file 02's own table entry. SQLite reads/writes, blob-store puts/gets, and B2/Storj backup calls are all I/O-bound; nothing here is compute-bound pure Python. **Two real exceptions worth naming rather than glossing:**
- **Bulk correction propagation** (Reconciliation's own §3, executed against this API's data) is a genuine CPU-bound pure-Python case — but it's dispatched through Background Workers' `CPU_PROCESS` class by Reconciliation itself, never run inline on this API's own event loop.
- **Excel export generation** (Export Framework's own §3) can be genuinely heavy for a large workbook — same treatment, dispatched rather than run inline.

**Forward-Compatibility Hygiene, all four points, explicitly** (`docs/PRINCIPLES.md` §3.3-3.3.1): (a) every dict-typed contract field in this API uses `FrozenDict`, not plain `dict`; (b) concurrency bucket stated above; (c) this API's own dependencies (`sqlite3` stdlib, the B2/Storj SDKs) are tracked via Telemetrees like any other — the SDKs specifically, since `sqlite3` ships with the interpreter; (d) free-threading relevance: **genuinely low for this API specifically**, since its work is I/O-bound rather than GIL-contended — stated explicitly rather than silently omitted. Python 3.15/3.16 validation is recommended for the `FrozenDict` built-in branch per §3.3.1, same as everywhere else.

---

## 11. Testing hooks — also genuinely missing from the original document
- **Dual-write atomicity test**: confirms a canonical-table write and its paired Historian event either both land or neither does, under a simulated mid-transaction failure — the concrete validation of §5's entire "same transaction boundary" claim.
- **Blob content-addressing test**: confirms the same bytes uploaded twice produce one stored blob and two references, not two copies — the real idempotency guarantee §4 depends on.
- **Backup-target failover test**: confirms a write still reports durably-backed-up when exactly one of B2/Storj is reachable (§10's own one-of-two resolution), and correctly reports *not* fully-synced in that same case.
- **Restore-integrity test**: confirms a full restore from backup produces a canonical database whose own row-level content matches the pre-restore state, not just that the restore process exited cleanly.

---

## 12. Open questions for this deep-dive (logged, not guessed at)
- (Reimport conflict-resolution policy — resolved, no longer open. Every conflict flags for human review, no automatic resolution — full design in `v3-deepdive-30-reimport.md` §6.)
- **Partial/single-user Disaster Recovery, resolved: supported, but scoped strictly to that user's own isolated data.** A single-user restore never touches `GLOBAL`-layer data (Architect's shared moderation queue, temporal_learning's own promoted facts) — that data is inherently shared/system-wide and can't be meaningfully rolled back for one user without risking inconsistency with everyone else who might already reference it. A single-user restore is real and supported for exactly the data that's genuinely isolated to that user (their own receipts, their own `LOCAL`-layer contributions); anything `GLOBAL` stays out of scope for this operation entirely, by design, not by omission.
- **Backup confirmation semantics for parallel targets, resolved: one-of-two is sufficient for "durably backed up," both required for "fully synced."** B2 and Storj are deliberately redundant — either one alone already provides real durability, so requiring both to confirm before reporting a write as safe would trade real latency for redundancy the design doesn't actually need at that threshold. A separate, weaker "fully synced" status can still track both-confirmed for operators who want that visibility, but it's not what gates the write path.
- **SLSP export format and audit-package contents — genuinely researched, with a real and important finding: the exact byte-level specification is not publicly available, confirmed rather than assumed.** A Freedom-of-Information request filed with BIR this same month (June 2026) asking directly for the complete SLSP technical specification (RMC-24-2002's own Annexes A-F, the actual file-layout documents) was **denied** — real, dated, current evidence that this isn't a research gap on this document's own part, it's that the primary source genuinely isn't released to the public, even on direct request. **The realistic path forward isn't reading an official spec that doesn't exist publicly** — it's reverse-engineering the format from a real, valid sample DAT file (obtainable from an accountant with RELIEF Data Entry Module access, or a BIR-compliant commercial tool like the ones already surfaced researching this), which is genuinely different scope than "read the documentation," worth stating plainly rather than leaving the original open question's framing implying the spec just hadn't been looked up yet.
