# V3 Deep Dive: Account Guardian API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md` · `v3-deepdive-01-ocr-api.md` · `v3-deepdive-02-inference-api.md` · `v3-deepdive-03-preprocessing-api.md` · `v3-deepdive-04-ingestion-api.md` · `v3-deepdive-05-auth-tenancy-api.md`

**Status:** Sixth deep-dive session, second of the "user-related APIs" pair. No V2 lineage, same as Auth & Tenancy. This session resolves the local-password open question Auth's own deep-dive left hanging (§1) — **now confirmed: no local password authentication exists anywhere in this design, ever** (Auth deep-dive §4's own explicit direction). This document's "account recovery" framing (§5), chosen when the answer was still unconfirmed, turns out to be exactly right regardless of which of the four supported methods (SSO/passkey/email/SMS) a user's account is actually configured with — recovery in this system always means "help someone regain access to an authentication method they've lost control of," never a password-specific flow.

---

## 1. Scope & boundary

Account Guardian is the user-facing privacy and account security center — deliberately on the user's own side first, not the server owner's. It owns: device/session management, SSO provider changes, and data-subject-rights requests (export, deletion). It does not:
- **own session/identity mechanics** — it consumes Auth & Tenancy's `SessionStore` and `User` primitives (this API's own companion deep-dive) rather than duplicating them.
- **own break-glass notification surfacing** — resolving file 01's own flagged open question here: that stays with Notifications API, which already owns dual-notifying the owner and affected client on a grant (Auth deep-dive §6.3, file 03's decision). Account Guardian's scope is self-service actions the *user* initiates; break-glass notification is something that happens *to* them passively, a different shape of concern that belongs with the API already built for passive delivery, not duplicated here just because both touch "the affected user."

**Resolved, no longer just a finding**: "password reset" never applied to this design at all, now confirmed with real direction rather than inferred from the architecture's own shape. Auth & Tenancy supports four passwordless primary methods — SSO, passkeys, email one-time codes, SMS one-time codes — plus composable 2FA, and explicitly, permanently, no local password authentication under any circumstance (Auth deep-dive §4). Account Guardian owns *account recovery* — what happens when a user loses access to whichever authentication method(s) they'd configured (a compromised SSO-linked Google account, a lost passkey device, a changed phone number) — a genuinely different and harder problem than a password reset, closer to a support-escalation flow than a self-service one, regardless of which specific method is involved.

---

## 2. Package layout

```
core/account_guardian/
  __init__.py
  contracts.py              # DeviceSession, RecoveryRequest, DataExportRequest, DeletionRequest, error types
  service.py                  # thin gRPC service implementation, delegates everything
  devices.py                   # lists/revokes sessions — thin wrapper over Auth's SessionStore
  account_recovery.py          # SSO-account-lost recovery flow, see §4
  sso_linking.py                # future: linking a second SSO provider to one account
  privacy/
    __init__.py
    export_request.py           # data portability — built on Persistence's Export Framework
    deletion_request.py          # right to erasure, grace-period lifecycle, see §6
  errors.py
  metrics.py
```

`contracts.py` is the only file other APIs import from.

---

## 3. Data contracts (`contracts.py`)

```python
@dataclass(frozen=True)
class DeviceSession:
    session_id: str
    created_at: datetime
    last_seen_at: datetime
    user_agent_summary: str      # parsed, human-readable ("Chrome on Windows"), never the raw UA string verbatim to the user
    is_current: bool               # is this the session making the current request

@dataclass(frozen=True)
class DataExportRequest:
    request_id: str
    user_id: str
    requested_at: datetime
    status: Literal["pending", "processing", "ready", "delivered", "failed"]
    export_blob_ref: BlobRef | None = None

class DeletionStage(str, Enum):
    REQUESTED = "requested"
    GRACE_PERIOD = "grace_period"          # cancellable window, see §6.2
    BILLING_HOLD = "billing_hold"           # blocked on Billing resolving subscription state, see §6.3
    PROCESSING = "processing"                # irreversible past this point
    COMPLETE = "complete"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class DeletionRequest:
    request_id: str
    user_id: str
    requested_at: datetime
    stage: DeletionStage
    grace_period_ends_at: datetime | None = None
```

---

## 4. Device/session management

A thin, user-facing view over Auth's own `SessionStore` (Auth deep-dive §5.2) — this API never maintains its own copy of session state, just presents and acts on Auth's.
```python
# devices.py — sketch
async def list_sessions(user_id: str) -> tuple[DeviceSession, ...]:
    """Reads from Auth's SessionStore, marks whichever session_id matches
    the current request as is_current=True so the UI can visually
    distinguish 'this device' from others, same convention most
    account-security screens use."""

async def revoke_session(user_id: str, session_id: str) -> None:
    """A user revoking someone else's session — or their own, from
    another device's view — calls Auth's SessionStore.revoke() directly.
    No local state to keep in sync, since none is kept."""
```
`user_agent_summary` is a parsed, human-readable form — never surfacing the raw User-Agent string, which can leak more granular fingerprinting detail than a user needs to see to recognize "is this my phone or something I don't recognize."

---

## 5. Account recovery — confirmed as the correct framing, no local password ever existed to reset (see §1)

Since there's no local password, "recovery" means: a user has lost access to whichever authentication method(s) they'd configured — their SSO-linked Google account (compromised, deactivated, they no longer control the recovery email), their only registered passkey (device lost or wiped), or the phone number/email address their SMS/email-OTP login depends on (number changed, inbox compromised). **This is not a self-service flow** — verifying someone is who they claim to be, absent a still-working authentication method, is inherently a manual, staff-mediated process (identity verification against account metadata, a support ticket, a time-boxed review), not something safe to fully automate. `account_recovery.py`'s job is the *request intake and staff-facing case queue*, not an automated account-transfer mechanism — the actual decision to relink an account to a new SSO identity, register a replacement passkey, or update the phone/email an OTP method depends on is a privileged action, logged via the Audit API the same way a break-glass grant is, given the security stakes are comparable (both are "grant access to an account that isn't cryptographically provable as the same person" scenarios) — regardless of which of the four methods is actually involved in a given case.

---

## 6. Data-privacy requests — export and deletion

### 6.1 Legal grounding, stated precisely rather than assumed
RA 10173 (the Philippine Data Privacy Act) grants data subjects the right to access, rectification, erasure/blocking, and **data portability** (obtaining personal data in an electronic/structured format, transferable to another controller) — the portability right is directly what `export_request.py` implements, not just a nice-to-have. Two details worth being precise about rather than assuming GDPR's numbers apply directly:
- **No hard statutory response deadline** the way GDPR's 30-day rule is codified — the IRR doesn't prescribe a strict number of days, but NPC guidance treats **30 days as the practical benchmark for "reasonable time."** Worth adopting 30 days as this system's own internal SLA target for the same reason GDPR installs use it: a concrete, defensible number beats "reasonable" left undefined, even where the law itself doesn't mandate it.
- **Erasure must be processed promptly and at no cost to the data subject** — explicit in NPC guidance, worth stating as a hard constraint on this API's design (no paywalling deletion behind a subscription-cancellation flow that delays it unreasonably, no fee).
- **A real compliance trigger worth flagging as a business fact, not just a technical one**: mandatory NPC registration (and a designated Data Protection Officer) applies once an organization processes sensitive personal information of 1,000+ individuals — and TINs (government-issued unique identifiers, explicitly named as sensitive personal information under RA 10173) are core data this system processes for every user. **DOMTRI's hosted multi-tenant service will almost certainly cross this threshold at any real scale**, meaning NPC registration and a DPO aren't optional future nice-to-haves once the user base grows — worth surfacing to the business side now rather than discovering it retroactively during an audit.

### 6.2 Export — built on Persistence's Export Framework, not a separate mechanism
```python
# privacy/export_request.py — sketch
async def request_export(user_id: str) -> DataExportRequest:
    """Registers a new export provider (Persistence's Export Framework,
    file 01 — the same Provider Registry pattern already serving Excel/
    SLSP/audit-package exports) covering the full data-portability scope:
    every table touching this user's own data, not just receipts. Runs
    as a Background Worker (idle-time class), not synchronously in the
    request — a full-account export is real work, not an instant call."""
```
Reuses the Export Framework rather than inventing a parallel data-dump mechanism — a data-portability export is structurally just another export provider, differing from the Excel/SLSP exports only in *scope* (everything, not a curated business view) and *audience* (the data subject themselves, not an accountant). Delivered via the same in-app inbox/download mechanism Notifications already uses for other completed-work signals.

### 6.3 Deletion — a grace period, resolving file 01's flagged open question
File 01 explicitly left "immediate vs. grace period" open. **Proposed resolution: a grace period (default 30 days, config-adjustable), not immediate deletion** — reasoning: erasure is irreversible past the processing stage, and every other irreversible-consequence action already documented across this project's deep-dives (Persistence's blob immutability, break-glass's logged-not-silent design) leans toward giving a cancellable window rather than acting instantly on a single request, since "I clicked delete and immediately regretted it" is a real, common failure mode a grace period cheaply protects against. **This also directly resolves the flagged Billing interaction** (file 01: "an account can't be deleted mid-subscription without resolving billing state first") — the grace period *is* the window where that resolution happens: a deletion request immediately stops new charges and enters `DeletionStage.GRACE_PERIOD`; if an active subscription still needs resolving (final invoice, proration, refund per Billing's own policy) when the grace period would otherwise elapse, the request transitions to `DeletionStage.BILLING_HOLD` instead of proceeding, resuming toward `PROCESSING` only once Billing confirms clean resolution — never silently stuck, never silently overriding Billing's own state.
```python
# privacy/deletion_request.py — sketch
async def request_deletion(user_id: str) -> DeletionRequest:
    """Immediately stops new charges (calls Billing) and enters
    GRACE_PERIOD. A user can cancel from Account Guardian's own UI
    at any point before PROCESSING starts — cancellation ability is
    the entire point of the grace period, not a bolted-on afterthought."""

async def cancel_deletion(user_id: str, request_id: str) -> None:
    """Only valid while stage is REQUESTED, GRACE_PERIOD, or BILLING_HOLD —
    once PROCESSING has begun, it's genuinely irreversible and this call
    correctly fails rather than pretending to succeed."""
```
Actual deletion, once `PROCESSING` begins, routes through Persistence's normal write path (a real Historian-logged event — "account deleted" is exactly the kind of privileged, auditable action the Historian sub-package already exists for) rather than a special-cased bypass of the audit trail just because the target is disappearing. **What actually checks whether a grace period has elapsed and advances a request to `PROCESSING` in the first place is now a real, registered job** — Background Workers' own consolidated registry (`v3-deepdive-12-background-workers-api.md` §6.4), previously unspecified here, which would have left a deletion request sitting in `GRACE_PERIOD` forever with nothing ever checking on it.

---

## 7. Consent tracking — Terms of Service / Privacy Policy, a real gap surfaced by a corpus-wide sweep

**A genuine blind spot, worth stating precisely what it is and isn't**: this project never designed a way to track whether a user has actually accepted the Terms of Service or Privacy Policy, nor which version they accepted. **Drafting the actual legal text is explicitly out of scope for this document and this project's own planning process** — that needs a lawyer, not a design session — but the *technical surface* around consent (tracking, versioning, re-consent on material change) is a real, missing piece this document owns closing.

### 7.1 The document text itself is per-instance, owner-configurable content — not hardcoded DOMTRI legal text
A real, easy-to-miss design point: **a self-hosted operator needs their own Terms of Service and Privacy Policy, not DOMTRI's** — different jurisdiction, different business terms, potentially a different legal entity entirely. The document text lives as owner-configurable content in the top-level config directory (`docs/PRINCIPLES.md` §1.6's own discipline — genuinely shared, persistent, deployment-specific, never tied to any one release clone) — DOMTRI's own hosted instance ships with DOMTRI's own default text; a self-hosted install can replace it with the operator's own.

### 7.2 Versioned consent, tied to a real record
```python
@dataclass(frozen=True)
class ConsentRecord:
    user_id: str
    document_type: Literal["terms_of_service", "privacy_policy"]
    document_version: str        # a version identifier the owner sets when publishing a revision
    accepted_at: datetime
    ip_address: str | None         # evidentiary value for the hosted service specifically; not collected for self-hosted single-tenant installs where it adds no real value
```
A user's acceptance is tied to a *specific* version, not just "has this user ever accepted something." Publishing a new document version doesn't retroactively count as every existing user having accepted it.

### 7.3 Re-consent on material change — an owner judgment call, not an algorithm
A new document version carries an owner-set `requires_reconsent: bool` — whether a revision is substantive enough to require every existing user to explicitly re-accept before continuing, or minor enough (a typo fix, a formatting change) that it doesn't. **Deliberately not automated** — no algorithm reliably judges "material" vs. "cosmetic" legal-text changes, and getting this wrong in either direction has real consequences (annoying every user with an unnecessary re-consent prompt, or failing to actually re-consent them when it mattered). A human decision, made once per revision, not inferred from a diff.

### 7.4 Enforcement
A session with no `ConsentRecord` for the current `requires_reconsent`-flagged version is blocked from any action beyond viewing and accepting the policy — the same route-guard shape Frontend Auth & Session already uses for authentication generally (`v3-deepdive-47-frontend-auth-session.md` §4), applied to a different gate.

---

## 8. Asyncio, free-threading, and profiling

### 7.1 Where asyncio is load-bearing
Every operation here is either a thin async call into Auth's `SessionStore` (§4) or a call into Persistence's Export Framework/Background Workers (§6.2-6.3) — this API has no compute-bound work of its own at all, the same I/O-bound shape as Ingestion (§7 there) and Auth & Tenancy (§7 there). No native dependency of its own to speak of — it's a thin orchestration layer over other APIs' primitives, which is itself worth naming as the reason this section is short: there's nothing here to profile that isn't better profiled at the API actually doing the work (Auth's session lookups, Persistence's export generation).

### 7.2 Free-threading and profiling
Genuinely nothing project-specific to add beyond Auth & Tenancy's own conclusion (§7.2-7.3 there) — this API inherits the same "I/O-bound, no compute-heavy hot path, Health API's live-diagnostic layer is the more relevant signal than bench-suite GIL profiling" shape, and repeating that reasoning a third time in near-identical words wouldn't add anything a cross-reference doesn't already say.

---

## 9. gRPC surface (`.proto` sketch)

```protobuf
service AccountGuardianService {
  rpc ListSessions(ListSessionsRequest) returns (ListSessionsResponse);
  rpc RevokeSession(RevokeSessionRequest) returns (RevokeResponse);
  rpc RequestAccountRecovery(RecoveryRequest) returns (RecoveryResponse);       // enters the staff-mediated queue, not automated
  rpc RequestDataExport(ExportRequest) returns (ExportResponse);
  rpc RequestDeletion(DeletionRequestMsg) returns (DeletionResponse);
  rpc CancelDeletion(CancelDeletionRequest) returns (DeletionResponse);
  rpc GetDeletionStatus(DeletionStatusRequest) returns (DeletionResponse);
  rpc GetCurrentPolicyVersion(PolicyRequest) returns (PolicyVersionResponse);      // §7 — what version is currently active, and whether the caller has a valid ConsentRecord for it
  rpc RecordConsent(ConsentRequest) returns (ConsentResponse);
}

message DeletionResponse {
  string request_id = 1;
  string stage = 2;              // requested | grace_period | billing_hold | processing | complete | cancelled
  int64 grace_period_ends_at_unix = 3;
}
```

---

## 10. Config surface

```
account_guardian:
  deletion:
    grace_period_days: 30            # see §6.3
  export:
    delivery_method: in_app_download   # only option today — email delivery would need Notifications' own future outbound-channel work
  compliance:
    npc_registration_threshold_individuals: 1000   # tracked, not enforced in code — a business/ops trigger, see §6.1
```

---

## 11. Testing hooks

- `tests/unit/core/account_guardian/` — deletion-stage transitions tested as a state machine (every valid/invalid transition explicitly asserted, e.g. confirming `cancel_deletion` correctly fails once `PROCESSING` has started rather than silently no-op'ing).
- **Billing-hold interaction test**: a deletion request against a user with an active subscription correctly enters `BILLING_HOLD` rather than proceeding, and correctly resumes once Billing reports clean resolution — the concrete validation of §6.3's cross-API contract, not just trusted from the design description.
- **Export completeness check**: a bench/regression case confirming a data-portability export genuinely covers every table touching a user's data, not just the obviously-relevant ones — the kind of gap that's easy to introduce silently when a new table gets added elsewhere in the system without anyone remembering to add it to the export scope too.
- Failure-injection: a session revocation call during Auth's `SessionStore` being briefly unavailable — confirming a clean error surfaces rather than a silent no-op that leaves the user believing a device was logged out when it wasn't.
- **Re-consent enforcement test**: confirms a session with no `ConsentRecord` for a `requires_reconsent: true` document version is actually blocked from every action except viewing/accepting the policy — direct validation of §7.4's enforcement claim.

---

## 12. Open questions for this deep-dive (logged, not guessed at)

- (The local-password finding from §1 — resolved, no longer open. Confirmed: no local password auth, ever. File 01's own entries for both this API and Auth & Tenancy corrected accordingly in the same pass — see `v3-plan-01-core-apis.md`.)
- **Grace period, locked in: 30 days.** The reasoning already given (analogy to the export SLA and GDPR-adjacent convention) is a real, defensible basis, not a placeholder needing further deliberation — worth treating as settled rather than reopened without new information.
- **Account recovery's actual staff workflow, resolved with a real verification checklist, not left implicit.** A structured set of checks, not a single test: (1) knowledge of account-specific detail not publicly guessable — a recent receipt's own vendor/amount, or the account's own creation date; (2) access to a previously-registered recovery contact distinct from the now-lost primary method, if one was ever set (worth adding as a real, optional profile field precisely for this case, a real new scope item); (3) for a `multi`-tenant company deployment specifically, confirmation from another already-verified staff/owner at the same install, since a colleague vouching for a coworker is real signal a solo consumer account doesn't have available. No single check is treated as sufficient alone — staff judgment combines what's actually available for a given case, consistent with this being a genuinely staff-mediated process rather than an algorithmic pass/fail.
- **NPC registration and DPO designation** (§6.1): a business/legal action item, correctly outside this engineering plan's own scope — not resolved here, flagged for explicit owner follow-up.
- **The actual Terms of Service / Privacy Policy legal text** (§7): explicitly not this process's job — needs a lawyer. The technical consent-tracking surface is designed; the text itself stays a real, outstanding action item.
- **Whether the hosted service's own default document requires review before any real signup happens — resolved: yes, unconditionally, treated as a hard pre-launch gate.** This doesn't need further deliberation: no real customer signup happens against unreviewed legal text, full stop. Stated plainly here so it can't be quietly assumed resolved just because the technical tracking mechanism exists.
