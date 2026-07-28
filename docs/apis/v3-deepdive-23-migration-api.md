# V3 Deep Dive: Migration API

**Companion files:** `v3-deepdive-13-persistence-api.md` §3.2 (migrations write through Persistence's own path), `v3-deepdive-12-background-workers-api.md` (bulk migration batches route through its `CPU_PROCESS` class).

**Status:** Twenty-third deep-dive session.

---

## 1. Scope & boundary

Migration owns the **schema-version chain** — every persisted structure (config, vendor/branch data, database schema) carries a `schema_version`; this API owns the registry of N→N+1 migration steps and the logic that walks a structure from its current version to the target. It does not:
- **own rollback machinery separately** — migrations write through Persistence's normal path (its deep-dive §3.2), meaning every migration is automatically an atomic, Historian-logged, revertable event with no separate rollback mechanism needed here.
- **jump versions directly** — N→N+2 is always N→N+1→N+2, chained, never a shortcut migration written to skip a step, since that would mean two different code paths could produce the same end state, a real correctness risk.

---

## 2. Package layout

```
core/migration/
  __init__.py
  contracts.py            # MigrationStep, SchemaVersion, error types
  registry.py                # the N→N+1 chain, one step per version bump
  runner.py                    # walks a structure from current to target version
  steps/
    __init__.py
    v1_to_v2.py               # one file per migration step, never a monolith
  errors.py
  metrics.py
```

---

## 3. Chained, never direct
```python
async def migrate(structure_id: str, current_version: int, target_version: int) -> MigrationResult:
    for v in range(current_version, target_version):
        step = registry.get_step(v, v + 1)
        await step.apply(structure_id)   # writes through Persistence — atomic, Historian-logged automatically
```
Each step is small and independently testable (one file per version bump, `steps/`), rather than one large function handling every possible version transition — a real, deliberate constraint given how much easier a small, focused diff is to review and reason about correctness for than a sprawling multi-version conditional.

---

## 4. Bulk migration and the no-GIL candidate
File 02's own table names this explicitly: migration functions are typically pure-Python row transforms, and a multi-tenant batch migration (walking every user's database through a schema change at once) is a genuine no-GIL/multiprocessing win — dispatched through Background Workers' `CPU_PROCESS` class (its own deep-dive §3) rather than this API building its own parallel-dispatch mechanism, consistent with every other API in this batch that has bulk CPU-bound work.

---

## 5. gRPC `.proto` versioning — a distinct, adjacent concern
File 01 also assigns this API the gRPC contract versioning discipline: **only add fields, never remove or renumber** — protobuf's own backward-compatible evolution rules, applied consistently across every `.proto` surface in this entire plan (every deep-dive's own gRPC section). This is a *code*-versioning discipline, distinct from the *data*-versioning `schema_version` chain above, but grouped in the same API since both are fundamentally "how does this system evolve its own shape over time without breaking what's already deployed."

---

## 6. Asyncio and profiling
Individual migration steps are typically fast, pure-Python row transforms — the bulk-batch case (§4) is where real CPU-bound parallelism matters, already routed through Background Workers rather than this API's own concern. No native/GIL-released compute here worth its own free-threading discussion.

---

## 7. gRPC surface

```protobuf
service MigrationService {
  rpc RunMigration(MigrationRequest) returns (MigrationResult);
  rpc GetCurrentVersion(VersionRequest) returns (VersionResponse);
}
```

---

## 8. Testing hooks
- **Chain-integrity test**: confirms every registered version has exactly one N→N+1 step defined, no gaps — a missing step should fail CI, not be discovered mid-migration on a live system.
- **Idempotency test**: re-running an already-applied migration step is a safe no-op, not a duplicate application — worth explicit coverage given migrations sometimes need to be re-run after an interrupted batch.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Cross-user migration ordering/rollout, resolved: per-channel, tied directly to that channel's own code rollout, never simultaneous-for-everyone.** A schema-version bump ships as part of a specific release, and migrates a given user's database exactly when their own channel cuts over to that release (Update API's own multi-channel rollout model, `v3-deepdive-24-update-deployment-api.md`) — the same reasoning that already governs everything else about per-channel rollout: new code and the schema it expects arrive together, never one ahead of the other. A Beta-channel user's database migrates when Beta cuts over; a Stable-channel user's database stays on the old schema until Stable does the same.
