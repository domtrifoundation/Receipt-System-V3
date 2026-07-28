# V3 Deep Dive: Audit/Event Log API

**Companion files:** all prior deep-dives, especially `v3-deepdive-05-auth-tenancy-api.md` (break-glass grants are this API's primary writer) and file 01/03 (Historian and Logs API distinctions, restated precisely below since the three are easy to conflate).

**Status:** Eighth deep-dive session. Small, narrow-scoped API — deliberately so, per file 01's own framing ("deliberately scoped narrower... to avoid becoming a catch-all").

---

## 1. Scope & boundary — three logs, three distinct purposes, restated precisely
This project has three genuinely different logging mechanisms, and keeping them distinct rather than merging "for simplicity" is itself the design decision worth stating clearly:
- **Logs API** — operational trace (OCR timings, LLM prompts, worker activity, errors). High-volume, gitignored, rotated, retention-policy-driven. Answers "what did the system do."
- **Persistence's Historian sub-package** — data-change trail (table/row/before-after/actor for every logical write to a user's own receipt data). Lives inside each user's own Persistence database, atomic with the write itself. Answers "how did this receipt's data get to its current state."
- **Audit/Event Log API (this document)** — privileged, security-relevant *actions*, not data changes: break-glass access grants, global vendor contribution reviews (approve/reject), config/role changes, confirmed-malicious content verdicts (Content Security's staff resolution). Answers "who did something with real security/compliance weight, and when."

The distinguishing question for "does this belong in Audit" isn't volume or importance in some vague sense — it's **"would a security or compliance review need to see this specifically, distinct from ordinary data edits or routine operational noise."** A user correcting their own receipt's vendor name is Historian's job. A staff member gaining temporary access to that user's folder is Audit's job, even though both are technically "an action someone took."

---

## 2. Package layout

```
core/audit/
  __init__.py
  contracts.py        # AuditEvent, ActionType, error types
  service.py             # thin gRPC service implementation
  writer.py                # append-only write path — no update/delete ever exposed, see §3.2
  query.py                  # staff/owner-only read access, see §4
  errors.py
  metrics.py
```

---

## 3. Storage

### 3.1 Its own database, distinct from Auth's and Architect's — same reasoning as Auth's own placement decision
Audit events span every user and every staff/owner action — cross-tenancy infrastructure, not any single user's data, so it can't live inside a per-user Persistence folder any more than Auth's sessions could (Auth deep-dive §5.2's reasoning applies identically here). **Decision: its own small top-level SQLite database**, living alongside Auth's own database and Architect's moderation-queue database at the same outside-every-release-clone location Setup API already established — three deliberately separate databases with three deliberately non-overlapping scopes (identity/sessions, taxonomy moderation, privileged-action audit), not one shared catch-all schema just because they're all small. This placement is now also the explicit, general rule stated in `docs/PRINCIPLES.md` §1.6 (top-level directory discipline) — Audit's own database is a concrete instance of that rule, not a special case.

### 3.2 Genuinely append-only — enforced, not just conventionally followed
```python
# writer.py — sketch
class AuditWriter:
    async def record(self, event: AuditEvent) -> None:
        """INSERT only. No update_event(), no delete_event() exposed
        anywhere in this module's public surface — not because nobody
        would misuse it, but because the absence of the method is the
        actual guarantee. A correction to a prior audit entry is a NEW
        event referencing the original's event_id, never an edit to it."""
```
This matters specifically because Audit's whole value is being trustworthy evidence in exactly the scenario where someone might want to quietly alter it (an insider covering their own privileged-action trail) — "append-only" needs to be a structural property of the code's public surface, not a policy someone could bypass by writing a raw SQL `UPDATE` if the module happened to expose a connection object carelessly. Worth a concrete implementation detail: the database connection this module uses should be opened with only INSERT/SELECT grants at the SQLite level where practical, not relying on "the Python code just doesn't call UPDATE" as the only safeguard.

---

## 4. Data contracts and read access

```python
class ActionType(str, Enum):
    BREAK_GLASS_GRANTED = "break_glass_granted"
    BREAK_GLASS_REVOKED = "break_glass_revoked"
    VENDOR_CONTRIBUTION_APPROVED = "vendor_contribution_approved"
    VENDOR_CONTRIBUTION_REJECTED = "vendor_contribution_rejected"
    CONFIG_CHANGED = "config_changed"
    ROLE_CHANGED = "role_changed"
    CONTENT_CONFIRMED_MALICIOUS = "content_confirmed_malicious"      # Content Security's staff verdict, file 01 #26
    ACCOUNT_RECOVERY_APPROVED = "account_recovery_approved"           # Account Guardian's staff-mediated flow, its deep-dive §5

@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    action_type: ActionType
    actor_user_id: str              # who performed the action
    target_user_id: str | None       # who it was performed on/against, when applicable (break-glass, role change)
    reason: str | None                # required for break-glass (Auth's own requirement), optional elsewhere
    details: FrozenDict               # action-specific payload, e.g. old_role/new_role for a role change — FrozenDict per Tool Call API's project-wide policy (its deep-dive §6): an append-only audit record with a mutable dict field would be a real, ironic gap for exactly this API to leave open
    occurred_at: datetime
```

**Read access is staff/owner only, never client role** — this is privileged-action visibility by definition, not general-purpose data a client-role user has any claim to, even about themselves (a client seeing "staff member X accessed my folder on date Y for reason Z" is exactly what Notifications already surfaces to them directly per Auth's break-glass design — Audit's own query interface doesn't need to serve that same information a second way to the affected user).

---

## 5. Retention — resolved, with real citation and owner control
**Default: 10 years, matching BIR's RR No. 17-2013 (amended by RR 5-2014) accounting-record retention requirement** — researched, not guessed at (`v3-deepdive-06-account-guardian-api.md` §7's own companion finding confirms the same regulation independently). Owner-configurable to a longer fixed period, or to `indefinite` (no auto-deletion at all) — never configurable *shorter* than the default without an explicit, deliberate override, since defaulting downward from a researched legal baseline is exactly the kind of quiet drift this project's own hygiene discipline exists to prevent.
```
audit:
  retention_days: 3650          # 10 years — see §5's own citation
  retention_mode: fixed           # fixed | indefinite — owner can disable auto-deletion entirely
```
**The actual regulation is shown in the TUI itself, not just a bare number in a config screen** — the settings entry for this value carries a real `docs_ref`/tooltip (the same `MenuItemSpec` fields Interface API's own menu-data already provides for exactly this purpose, `v3-deepdive-14-interface-api.md` §2) citing RR No. 17-2013/RR 5-2014 by name, so an owner changing this value is making an informed choice against the actual legal context, not adjusting an unexplained number.

---

## 6. Asyncio, free-threading, and profiling
A genuine gap in an earlier version of this document — every API's own deep-dive is required to state its concurrency classification explicitly (`docs/PRINCIPLES.md` §5), and this one simply never did. Corrected here: `AuditWriter.record()` and `AuditQuery`'s lookups are local SQLite I/O, using the same async wrapper convention as every other SQLite-backed API in this batch (Auth, Persistence) — genuinely async I/O, no compute-bound work of its own, no free-threading relevance beyond tracking `authlib`/`cryptography`-adjacent dependencies the way Auth's own deep-dive already does (this API shares no native dependency of its own that isn't already covered by Auth's tracking). Volume is low relative to Logs or Historian (privileged actions are rare by definition), so this API's own hot-path concerns are negligible — worth stating plainly rather than implying by silence.

---

## 7. Testing hooks — a real gap found during a pre-development sweep
- **Append-only enforcement test**: confirms `set_authorizer()` genuinely denies `SQLITE_UPDATE`/`SQLITE_DELETE` on the audit table at the connection level (§3.2's own resolved mechanism), not just that application code politely avoids issuing them.
- **Privileged-action coverage test**: confirms every action this project classifies as privileged (break-glass grants, `ForceWake`, `PinServiceVersion`, agent-token issuance, `is_group_manager` toggles) actually produces an audit entry — a structural check against the list, not per-action trust.
- **Retention-boundary test**: confirms the 10-year default genuinely retains a record at 9 years 11 months and that `indefinite` mode never purges.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- (Retention period — resolved, no longer open. Approved: 10-year default matching BIR's RR No. 17-2013/RR 5-2014, owner-configurable to longer or indefinite, cited in the TUI itself — full design in §5.)
- **Whether `AuditWriter`'s INSERT-only DB grant is practical with SQLite's actual permission model, resolved.** Correct concern — SQLite genuinely has no client-server-style statement-level GRANT system. The real mechanism: Python's own `sqlite3.Connection.set_authorizer()`, which lets a connection register a callback that can deny specific SQL operation types (UPDATE, DELETE) at the connection level before they execute — genuine, real statement-level enforcement without needing a different database engine. `AuditWriter`'s own connection registers an authorizer denying `SQLITE_UPDATE`/`SQLITE_DELETE` outright, so the "INSERT-only" framing translates to something concretely real at the SQLite layer, not just a comment describing an intention.
