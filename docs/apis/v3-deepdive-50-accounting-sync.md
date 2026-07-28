# V3 Deep Dive: Accounting Sync API

**Companion files:** `v3-deepdive-31-export-framework.md` (the export-only tier lives there, not here — see §1), `v3-deepdive-40-temporal-learning.md` (the vendor/corporation model this API's own mapping logic reads from), `docs/templates/new_provider.md` (the pattern `QuickBooksProvider`/`XeroProvider` follow).

**Status:** New Core API (#29), surfaced as a genuine blind spot during a corpus-wide sweep — never mentioned anywhere in this project's prior planning.

---

## 1. Scope & boundary

Accounting Sync owns **live, ongoing integration** with a user's own QuickBooks or Xero account — pushing processed receipts as expense/bill records automatically, not a one-time file export. It does not:
- **own one-time export generation** — QuickBooks' IIF format and Xero's CSV import format are both genuinely simple, file-based, no-OAuth-needed exports; these live as two new Export Framework providers (`quickbooks_export.py`, `xero_export.py`, `v3-deepdive-31-export-framework.md`'s own package) rather than duplicating Export Framework's own well-established pattern here. This API only owns the *live*, credentialed, ongoing sync case.
- **own the vendor/corporation data model** — reads from temporal_learning's own Corporation/Branch/Franchiser structure (`v3-deepdive-40-temporal-learning.md` §4) to map a receipt to an accounting-software-side vendor record; never maintains a second, parallel vendor concept of its own.
- **attempt full bidirectional sync in this version** — see §4's explicit scoping decision.

---

## 2. Package layout

```
core/accounting_sync/
  __init__.py
  contracts.py             # SyncConnection, SyncedRecord, error types
  providers/
    __init__.py
    base.py                     # AccountingSyncProvider Protocol
    quickbooks.py                  # OAuth2, QuickBooks Online API
    xero.py                          # OAuth2, Xero API
  mapping.py                         # receipt → accounting-software expense/bill record
  sync_engine.py                       # push scheduling, retry, per-user sync state
  errors.py
```

---

## 3. `AccountingSyncProvider` — a real Provider Registry, per-user credentials

```python
class AccountingSyncProvider(Protocol):
    async def authenticate(self, user_id: str) -> AuthUrl: ...          # returns the OAuth consent URL
    async def complete_auth(self, user_id: str, callback_params: FrozenDict) -> SyncConnection: ...
    async def push_record(self, connection: SyncConnection, receipt: MappedRecord) -> SyncedRecord: ...
    async def is_connected(self, user_id: str) -> bool: ...

@dataclass(frozen=True)
class SyncConnection:
    user_id: str
    provider: Literal["quickbooks", "xero"]
    connected_at: datetime
    # OAuth tokens themselves never live in this dataclass or anywhere in
    # Persistence's own queryable tables — see §5
```
**This is genuinely per-user, not system-wide** — unlike most Provider Registry entries in this project (OCR engines, backup targets), which the *owner* enables system-wide, each individual user connects (or doesn't) their own QuickBooks/Xero account independently. A group context (`v3-deepdive-41-groups.md`) doesn't share one connection across members — each member who wants sync connects their own account, consistent with Groups' own design never creating a shared data store, only a visibility grant.

---

## 4. Scope decision: one-way push, not bidirectional sync
**A receipt processed in this system pushes to QuickBooks/Xero as a new expense/bill record. Nothing flows back.** Real bidirectional sync (a change made in QuickBooks reflecting back here) is explicitly out of scope for this version — it would require a genuine three-way conflict-resolution model comparable to Reimport's own (`v3-deepdive-30-reimport.md`), against an *external* system this project doesn't control the schema or change-notification model of, which is a substantially harder problem than anything else this integration needs to solve to deliver real value. One-way push already covers the actual use case (get processed receipts into the user's books without manual re-entry) without that complexity. Flagged explicitly in §9 as a real, deliberately deferred scope boundary, not an oversight.

---

## 5. Credential storage — the same discipline as every other OAuth integration in this project
Access/refresh tokens live encrypted, associated with the user's own record, never in a plain queryable table alongside business data — the same posture Auth's own OIDC tokens already require (its deep-dive §4). `SyncConnection` itself (§3) deliberately carries no token material, only connection metadata — a design choice worth stating explicitly, matching the "don't let a broadly-queried table also be where secrets live" instinct already established elsewhere in this project.

---

## 6. Push triggering and retry
A receipt becomes push-eligible once it's fully processed and un-flagged (a flagged receipt shouldn't push a possibly-wrong record into someone's books) — registered as a Background Workers job (its deep-dive §6.1's own registry), `SCHEDULED_ONLY`-shaped in Supervisor's sleep/wake sense (`v3-deepdive-38-supervisor.md` §6.2) since push events are genuinely sparse per user, not a constant stream. A failed push (the accounting API down, a rate limit) retries with backoff; a push that fails repeatedly surfaces as a real notification to the user (Notifications API), never silently drops.

---

## 7. Asyncio, free-threading, and profiling
Entirely I/O-bound — OAuth token exchange, HTTP calls to QuickBooks'/Xero's own APIs — the same thin-orchestration shape as every other external-service-integration API in this corpus (Tool Call, Billing). **Forward-compatibility check, explicit rather than assumed**: no new native/C-extension dependency — this is HTTP-client-and-OAuth-library work, already-tracked dependency categories, nothing requiring a new Telemetrees entry beyond noting `quickbooks-online` / `xero-python` (or equivalent, whichever official/community SDKs are chosen) as genuinely new tracked dependencies with their own Day-0 support status to monitor going forward.

---

## 8. gRPC surface

```protobuf
service AccountingSyncService {
  rpc InitiateAuth(AuthRequest) returns (AuthUrlResponse);
  rpc CompleteAuth(AuthCallbackRequest) returns (SyncConnectionResponse);
  rpc GetSyncStatus(SyncStatusRequest) returns (SyncStatusResponse);
  rpc Disconnect(DisconnectRequest) returns (DisconnectResponse);
}
```

---

## 9. Testing hooks
- **One-way boundary test**: confirms no code path ever attempts to read changes back from QuickBooks/Xero — the concrete enforcement of §4's scope decision, not just a documented intention.
- **Flagged-receipt exclusion test**: confirms a receipt with an active Review/Flagging flag never becomes push-eligible.
- **Credential isolation test**: confirms `SyncConnection` and anything derived from it, as returned over gRPC, never includes raw token material.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Which SDK/library for each provider, resolved: official SDKs where they exist and are actively maintained, hand-rolled only as a fallback.** Consistent with this project's own "don't reinvent what already exists well" discipline — reduces custom-code burden and stays current with each platform's own API changes automatically, rather than this project maintaining its own thin HTTP client against a moving target.
- **Bidirectional sync** (§4) — stays explicitly, deliberately deferred; not designed, a real future scope expansion if it's ever warranted, not a gap in the current design.
- **Group-level sync, resolved: not in v1, strictly per-user.** A shared accounting connection across group members raises real credential-management and consent questions (whose OAuth token, whose responsibility if it breaks) not worth solving speculatively before there's a real, specific need — consistent with Billing's own per-user tier model, not a new exception to it.
- **Field mapping completeness** — genuinely needs real research against each platform's own current, actual schema, not something resolvable by reasoning alone; stays open as real pre-implementation research, not a design gap.
