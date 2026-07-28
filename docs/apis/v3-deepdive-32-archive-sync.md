# V3 Deep Dive: Archive Sync (Persistence sub-capability)

**Parent API:** `v3-deepdive-13-persistence-api.md` §8. **Companion files:** `v3-deepdive-04-ingestion-api.md` §4.1 (the credential strategy this reuses).

**Status:** Sub-capability deep-dive, full treatment.

---

## 1. Scope & boundary

Archive Sync owns **one-way mirroring** of a user's processed/archived receipts out to an external drive provider. It does not:
- **serve as the default browsing experience** — the webapp's "My Files" screen (Interface API, built on Search/Query + Persistence) is that; Archive Sync is strictly additional for users who specifically want their archive visible in their own external Drive too.
- **become a second source of truth** — the external copy is a convenience mirror; if it's ever missing, deleted externally, or out of sync, Persistence's own blob store remains authoritative, full stop.

---

## 2. Package layout

```
core/persistence/archive_sync/
  __init__.py
  contracts.py           # SyncTarget, SyncJob, error types
  sync.py                   # the actual mirror job orchestration
  providers/
    __init__.py
    base.py                     # SyncTargetProvider protocol — Provider Registry, docs/PRINCIPLES.md §1.2
    google_drive_provider.py       # the default, reusing Ingestion's own credential (§3)
  credential_reuse.py               # reuses Ingestion's Drive credential, see §3
  errors.py
```
**Corrected during a principles-compliance audit**: this layout previously had sync logic in a single `sync.py` with no provider abstraction, despite `SyncTarget` existing as a contract type implying more than one kind of target — a real `docs/PRINCIPLES.md` §1.3 violation ("external dependencies are always swappable, never hardcoded — at every granularity"). Google Drive is the only implemented provider today and that's fine; what wasn't fine was the *structure* making a second one a refactor rather than a drop-in:
```python
class SyncTargetProvider(Protocol):
    async def mirror(self, blob_ref: str, target_path: str) -> SyncResult: ...
    async def is_reachable(self) -> bool: ...     # §7's own notify-then-pause behavior depends on this being a real, checkable state
```

---

## 3. Credential reuse — one authorization, not two
Reuses the same swappable Drive-credential-strategy pattern Ingestion's own deep-dive designed (§4.1 there) — where a user already granted Drive access for *ingestion*, Archive Sync reuses that same connection for the *outbound* direction rather than asking for a second authorization. This only works cleanly when the granted scope already covers write access to the target folder; a read-only ingestion-scoped grant would need its own separate authorization for the outbound direction, worth checking explicitly rather than assuming the existing grant is sufficient.

---

## 4. Sync mechanism — a Background Worker job, not a live filesystem watch
```python
async def sync_new_archives(user_id: str) -> SyncJob:
    """Registered as a Background Workers job (idle-time class, since
    this is a convenience feature with no urgency) — finds
    archived/processed receipts not yet mirrored (tracked via a
    per-user sync-cursor, not a full re-scan every run), uploads each
    to the external target, and advances the cursor only after a
    confirmed successful upload."""
```
**Naming collisions in the external folder are a real, worth-designing-for case**: two receipts that happen to produce the same generated filename (unlikely but not impossible given content-addressable internal naming doesn't map directly to a human-friendly external filename) get resolved by including enough distinguishing detail (date + a short hash suffix) in the external filename scheme from the start, rather than discovering a collision in production and needing a retroactive rename scheme.

---

## 5. Asyncio
Network upload calls to the external Drive provider — genuine I/O, same shape as every other outbound-API-call case in this project. No compute-bound work of its own.

---

## 6. gRPC surface

```protobuf
service ArchiveSyncService {
  rpc EnableSync(EnableSyncRequest) returns (SyncStatusResponse);
  rpc GetSyncStatus(SyncStatusRequest) returns (SyncStatusResponse);
}
```

---

## 7. Testing hooks
- **Cursor-resume test**: a sync job interrupted mid-run correctly resumes from its last confirmed cursor position, not re-uploading everything or silently skipping unmirrored items.
- **Filename-collision test**: two receipts engineered to produce a naming collision under the external scheme, confirming the distinguishing-suffix approach actually prevents an overwrite.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **Behavior when the external target folder is deleted or access is revoked externally, resolved: notify, then pause — never silently continue, never auto-recreate.** A missing/inaccessible target surfaces as a real Notifications alert (the user needs to know their own external mirror stopped working), and sync pauses until the user explicitly re-confirms or reconfigures the target — auto-recreating the folder risks silently doing something the user didn't actually ask for (they may have deleted it on purpose), and silently continuing to retry forever risks masking a real problem from the person who needs to know about it.
- **Retention parity, resolved: no automatic parity by default — the external mirror is independent.** A purged internal blob does not automatically get removed from the external target; the external copy is the user's own, explicitly outside this project's own retention decisions, since a user syncing to their own Drive folder likely wants that copy to persist as their own independent backup regardless of what this system's own internal retention policy later decides. An explicit "keep the external mirror in sync with internal deletions too" toggle remains a real, addressable future option if genuinely wanted, but it's not the default.
