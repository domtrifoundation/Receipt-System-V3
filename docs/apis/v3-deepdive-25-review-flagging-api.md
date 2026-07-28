# V3 Deep Dive: Review/Flagging API

**Companion files:** `v3-deepdive-17-reconciliation-api.md` (the primary producer of flags), `v3-deepdive-26-architect-api.md` (owns the flag taxonomy this API only manages the lifecycle of), `v3-deepdive-18-logs-api.md` (powers the per-receipt audit screen), `v3-deepdive-09-notifications-inbox-api.md` §1 (new-flag creation as a real, now-confirmed-bidirectional notification trigger).

**Status:** Twenty-fifth deep-dive session.

---

## 1. Scope & boundary

Review/Flagging owns the **flag lifecycle** — creation, assignment, resolution, dismissal — for every flag type Architect's registry has defined. It does not:
- **own the flag taxonomy itself** — VAT math mismatch, malformed TIN, implausible date, and the rest of the real inventory (Reconciliation deep-dive §4) are defined in Architect's registry; this API manages instances of those types, never invents a new type inline.
- **run the checks that produce flags** — Reconciliation's own domain logic (its deep-dive) is the primary producer; this API is where a flag lives once created, not what creates it.
- **redesign Logs API** — the per-receipt audit screen (§3) pulls a readable slice of Logs' own data; this API is a workflow layer on top of Logs, not a competing log store.

---

## 2. Package layout

```
core/review_flagging/
  __init__.py
  contracts.py            # Flag, FlagStatus, error types
  lifecycle.py                # create/assign/resolve/dismiss
  audit_screen.py                # pulls Logs API data into a per-receipt readable view — see §3
  edit_entry_point.py              # deep-link to an edit form, writes through Persistence — see §4
  errors.py
  metrics.py
```

---

## 3. The per-receipt audit screen — a workflow layer over Logs, not a new store
```python
async def build_audit_view(receipt_id: str) -> AuditView:
    """Pulls the relevant slice of Logs API data (how a receipt was
    scanned, the different OCR engine readings, what Inference
    concluded and why it flagged something) into a readable, structured
    view. Never re-implements or duplicates Logs' own storage — this
    function is purely a query + presentation layer."""
```
This is also, per file 01, **the system's general in-browser edit entry point** — a flag or a Notifications quick-action button deep-links directly into an edit form for the specific field/row it concerns, writing through Persistence's normal write path immediately. No separate "inline-edit grid" feature exists or is needed — every edit path in this system converges on the same Persistence write path regardless of which screen initiated it.

---

## 4. Flag lifecycle
```python
class FlagStatus(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"      # a false positive, distinct from resolved (an actual fix was applied)

@dataclass(frozen=True)
class Flag:
    flag_id: str
    flag_type: str            # a type Architect's registry has defined — never invented here
    receipt_id: str
    status: FlagStatus
    created_by: str              # "reconciliation" | "content_security" | ...
    assigned_to: str | None
    resolved_at: datetime | None
```
Resolution routes through the same edit-entry-point mechanism (§3) when it involves a data change, or a simple status transition when it's a pure dismissal — either way, a Historian-logged event via Persistence's normal write path, never a special-cased bypass.

---

## 5. Asyncio
DB reads/writes plus notification triggering (a new flag creation surfaces via Notifications, its own deep-dive) — file 02's own table already classifies this API as async I/O throughout, no compute-bound work of its own.

---

## 6. gRPC surface

```protobuf
service ReviewFlaggingService {
  rpc CreateFlag(CreateFlagRequest) returns (FlagResponse);
  rpc ResolveFlag(ResolveFlagRequest) returns (FlagResponse);
  rpc DismissFlag(DismissFlagRequest) returns (FlagResponse);
  rpc GetAuditView(AuditViewRequest) returns (AuditViewResponse);
  rpc ListFlags(ListFlagsRequest) returns (ListFlagsResponse);
}
```

---

## 7. Testing hooks
- **Dismissal vs. resolution distinction test**: confirms a dismissed flag never gets counted the same as a resolved one in any staff-facing metrics/queue view — a real, easy-to-blur distinction worth explicit coverage.
- **Edit-entry-point write-path test**: confirms an edit made through this API's deep-link genuinely goes through Persistence's normal write path (Historian-logged), not a shortcut that bypasses it.

---

## 8. Open questions for this deep-dive (logged, not guessed at)
- **Flag assignment/routing policy, resolved: a shared open queue, self-assign — the same shape as Support Ticketing's own identical question.** An unassigned flag is visible to any staff member, any staff member can self-assign, an owner can reassign — consistent with `v3-deepdive-52-support-ticketing.md` §4's own resolution for the structurally identical problem, avoiding two different routing philosophies for what's the same underlying "staff queue" shape in both places.
- **Flag-to-notification mapping, resolved with a concrete severity split.** High-stakes flag types get an immediate Notifications alert — malicious/unsafe content (a real security concern, `CONTENT_CONFIRMED_MALICIOUS`) and ATP validity/BIR-compliance flags (real regulatory exposure if missed) specifically. Routine flags — semantic duplicates, minor account/category mismatches — appear in the staff queue without an immediate push, since these are exactly the kind of thing a staff member reviewing the queue on their own normal cadence handles fine, and an immediate alert for every one of them would just be noise that trains people to ignore the channel.
