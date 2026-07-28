# V3 Deep Dive: Disaster Recovery (Persistence sub-API)

**Parent API:** `v3-deepdive-13-persistence-api.md` §9 (the first design pass this document expands into full treatment). **Companion files:** `v3-deepdive-29-historian.md` (a distinct concern, not this API's job), `v3-deepdive-30-reimport.md` (also distinct — single-user reconciliation, not instance-level restore).

**Status:** Sub-API deep-dive, full treatment. Genuinely new territory, no V2 equivalent.

---

## 1. Scope & boundary

Disaster Recovery owns **full-instance restore** — rebuilding a working instance from the B2/Storj blob backups and SQLite snapshot backups after catastrophic disk loss. Restated precisely from the parent document, since these three are easy to conflate: distinct from the backup *mechanisms* (Persistence §4.4 — replication, not restore), distinct from Reimport (single-user data reconciliation against canonical state, not instance-level rebuild), distinct from Historian (an audit trail, not a restore procedure).

---

## 2. Package layout

```
core/persistence/disaster_recovery/
  __init__.py
  contracts.py            # RestoreJob, VerificationReport, error types
  restore.py                  # blob-then-SQLite ordering — see §3
  verify.py                     # post-restore hash verification — see §4
  errors.py
```

---

## 3. Restore ordering — blobs before SQLite, restated with the concrete mechanism
```python
async def restore_instance(target_dir: Path, snapshot_id: str) -> RestoreJob:
    job = RestoreJob(job_id=..., stage="restoring_blobs")
    await _restore_blob_store(target_dir, snapshot_id)          # from B2/Storj, full store
    job = job.with_stage("restoring_database")
    await _restore_sqlite_snapshot(target_dir, snapshot_id)      # the day-rotated checkpoint
    job = job.with_stage("verifying")
    report = await verify_restore(target_dir)                     # §4
    return job.with_stage("complete" if report.clean else "complete_with_issues")
```
Restoring blobs first is the only ordering that makes verification meaningful — checking "does every referenced blob exist" against a database restored before its blobs would trivially fail regardless of whether backups are actually intact, telling you nothing real.

---

## 4. Post-restore verification — the real, necessary step — corrected to verify the right hash
```python
async def verify_restore(restored_dir: Path) -> VerificationReport:
    """Walks every BlobLocation referenced anywhere in the restored
    SQLite data (Persistence deep-dive §3.3) — NOT logical_id directly,
    a real correction from an earlier version of this design that would
    have checked a stored file's bytes against the hash of bytes that
    were never what's actually on disk (the original, pre-re-encode
    upload) rather than what's genuinely stored (the re-encoded
    archival copy). For each BlobLocation: confirms the file exists at
    its expected sharded path keyed by physical_hash (blob store's own
    §4.2 layout), AND recomputes its SHA-256 to confirm it matches
    physical_hash — this now genuinely catches silent backup corruption
    (a bit-flipped file that still exists but no longer matches its own
    claimed content), because physical_hash is defined as a hash of
    whatever is actually stored, always self-consistent by
    construction. Separately confirms every logical_id referenced by a
    receipt row has a corresponding BlobLocation at all — a missing
    mapping entry is its own distinct failure mode from a missing or
    corrupted physical file, worth reporting separately since they
    imply different repair actions."""

@dataclass(frozen=True)
class VerificationReport:
    total_refs_checked: int
    orphaned_logical_ids: tuple[str, ...]     # a receipt references a logical_id with no BlobLocation mapping at all
    orphaned_physical_files: tuple[str, ...]    # a BlobLocation points at a physical_hash with no corresponding file
    hash_mismatches: tuple[str, ...]             # file exists but content doesn't match its own physical_hash — real corruption
    clean: bool                                    # True only if all three lists are empty
```

---

## 5. Partial/single-user restore — the genuine open question, worked through further here
The parent document flagged this as unresolved rather than guessed at; worth actually working through the specifics now that this has its own dedicated session. Auth's own per-user database placement reasoning (its deep-dive §5.2) means a single user's canonical SQLite database genuinely *is* structurally independent — restoring just that one file, plus that user's own blob subset, is technically coherent on its own. **The real complication is cross-user references, not the per-user data itself**: Architect's shared moderation queue and vendor directory are referenced *by* every user's own data but live in a separate database entirely — a single-user restore doesn't touch that shared database at all, meaning a restored user's data references vendor/taxonomy entries exactly as they existed at backup time, which is fine (Architect's own database isn't being restored, just referenced) *unless* the single-user restore is happening because of data corruption that also affected shared-database integrity, a genuinely different failure scenario a full-instance restore already handles but a single-user restore explicitly wouldn't. **Conclusion: single-user restore is technically supportable for the common case (one user's own disk/data issue, shared infrastructure unaffected), but should be explicitly scoped as NOT a substitute for full-instance restore when the underlying cause might have touched shared state** — a real, now-more-precise design boundary rather than a flat "not sure if this is ever supported."

---

## 6. Asyncio
Restore and verification are I/O-heavy (large blob transfers, many small file/hash checks) — genuinely worth `asyncio.gather`-based concurrency for the verification pass specifically (checking many blob references in parallel rather than sequentially), the same "don't repeat Geo/Address's V2 sequential-loop bug" discipline already established elsewhere in this project (Geo/Address deep-dive §5).

---

## 7. gRPC surface

```protobuf
service DisasterRecoveryService {
  rpc StartRestore(RestoreRequest) returns (RestoreJobResponse);
  rpc GetRestoreStatus(RestoreStatusRequest) returns (RestoreJobResponse);
  rpc VerifyIntegrity(VerifyRequest) returns (VerificationReportResponse);   // callable standalone, not just post-restore — a periodic integrity check on a healthy instance
}
```

---

## 8. Testing hooks
- **Ordering-violation test**: attempting to verify against a not-yet-blob-restored state confirms the system either refuses or correctly reports every reference as orphaned (not a false "clean" result) — validates §3's ordering claim actually matters, not just asserted.
- **Corruption-detection test**: a deliberately bit-flipped backed-up blob is caught by hash verification (§4), not just existence-checking.
- **Single-user restore boundary test**: confirms a single-user restore genuinely doesn't touch or require Architect's shared database, validating §5's scoping conclusion.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Standalone periodic integrity checks, resolved with a real design.** A genuine Background Workers idle-time job (weekly cadence, the same rhythm as blob backup spot-verification given they're closely related concerns) runs `VerifyIntegrity` against a small random sample on an otherwise-healthy instance, not just post-restore. A detected-but-not-yet-disaster-level issue (a single corrupted blob, say, rather than wholesale data loss) surfaces as an `ATTENTION`-level Logs entry and a Review/Flagging-adjacent notification to staff, never silently auto-triggering a full disaster-recovery workflow for what might be a genuinely isolated, small problem — the same proportional-response discipline this project applies to every other severity-tiered finding.
- **Restore time/bandwidth estimates, remains a genuine pre-launch bench task, not a design gap.** No real numbers exist because no real backup data exists yet to test against — the mechanism is fully designed; the numbers are an empirical fact waiting on real data, not a decision this document can make by reasoning alone.
