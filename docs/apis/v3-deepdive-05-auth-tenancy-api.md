# V3 Deep Dive: Auth & Tenancy API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md` · `v3-deepdive-01-ocr-api.md` · `v3-deepdive-02-inference-api.md` · `v3-deepdive-03-preprocessing-api.md` · `v3-deepdive-04-ingestion-api.md`

**Status:** Fifth deep-dive session, first of the "user-related APIs" pair (Auth & Tenancy, then Account Guardian). No V2 lineage — file 00's audit confirmed V2 was single-user/self-hosted only with no auth code at all, so unlike the prior four deep-dives, there's no V2 failure mode to react to here; every decision below is derived fresh against current (2026) practice.

---

## 1. Scope & boundary

Auth & Tenancy owns **session/identity mechanics**: SSO/OIDC authentication, issuing and validating the server-side session that backs every authenticated request, the owner/staff/client role model, break-glass access grants, and the `tenancy_mode` (single/multi) config flag that makes this whole API a no-op in self-hosted single-user mode. It does not:
- **own the user-facing self-service surface** — device management, password reset, SSO provider changes all live in Account Guardian API instead (this API's own companion deep-dive), which consumes Auth's primitives rather than duplicating them.
- **own authorization *content*** — this API answers "who is this request from and what role do they hold," not "is this specific action allowed" for any given domain API's own business logic. A role claim riding on a session is a fact Auth publishes; what a given API does with that fact (Gateway enforcing owner/staff-only routes, Persistence enforcing folder isolation) is each consumer's own job.
- **own break-glass's *notification* or *approval workflow* UI** — Auth issues and tracks the grant itself (time-boxed, reason-tagged, logged); Notifications API surfaces it to the owner and affected client, Review/Flagging or a staff-facing screen is where a request actually gets approved. Auth is the ledger of grants, not the request form.

---

## 2. Package layout

```
core/auth/
  __init__.py
  contracts.py             # Session, User, Role, BreakGlassGrant, TwoFactorConfig, error types
  service.py                 # thin gRPC service implementation, delegates everything
  auth_methods/                # corrected from oidc/ — SSO was never meant to be the only method, see §4
    __init__.py
    base.py                       # AuthMethodProvider Protocol
    sso_provider.py                 # Authlib-based OIDC client (Google today)
    passkey_provider.py               # WebAuthn/FIDO2
    email_login_provider.py             # email OTP
    sms_login_provider.py                 # SMS OTP, reuses Notifications' own channel
    two_factor.py                           # a composable layer on top of any primary method, see §4.6
  session/
    __init__.py
    session_store.py           # server-side session persistence, see §5.2
    cookie.py                   # httpOnly cookie issuance/validation
  roles/
    __init__.py
    role_check.py               # role-claim verification helper, consumed by Gateway
  break_glass/
    __init__.py
    grant.py                     # time-boxed, reason-tagged grant lifecycle
  tenancy.py                   # tenancy_mode resolution — single-mode short-circuits most of this package
  errors.py
  metrics.py
```

`contracts.py` is the only file other APIs import from, same discipline as every prior deep-dive.

---

## 3. Data contracts (`contracts.py`)

```python
class Role(str, Enum):
    OWNER = "owner"
    STAFF = "staff"
    CLIENT = "client"

class TenancyMode(str, Enum):
    SINGLE = "single"   # self-hosted, one implicit user, no login — this whole API mostly short-circuits
    MULTI = "multi"

@dataclass(frozen=True)
class User:
    user_id: str
    role: Role
    email: str                     # near-universal identifier — required, used for display/contact and as the identifier for email-OTP login
    phone_number: str | None          # set only if SMS login is configured for this user
    sso_provider: str | None            # "google", set only if SSO is one of this user's configured methods
    sso_subject: str | None               # the IdP's stable subject identifier, see §4.2 — only meaningful if sso_provider is set
    created_at: datetime

@dataclass(frozen=True)
class PasskeyCredential:
    credential_id: str
    user_id: str
    public_key: bytes
    created_at: datetime

@dataclass(frozen=True)
class Session:
    session_id: str                # opaque, high-entropy — never derived from user_id or any guessable value
    user_id: str
    role: Role                     # captured at session-creation time — see §5.3 for why this matters
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime

@dataclass(frozen=True)
class BreakGlassGrant:
    grant_id: str
    staff_user_id: str
    target_client_user_id: str
    reason: str                    # required, non-empty — free text, optionally a real ticket ID from Support Ticketing API (v3-deepdive-52-support-ticketing.md), never required to be one
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

class AuthError(str, Enum):
    SESSION_EXPIRED = "session_expired"
    SESSION_INVALID = "session_invalid"
    OIDC_STATE_MISMATCH = "oidc_state_mismatch"     # CSRF/replay indicator, see §4.2
    ROLE_INSUFFICIENT = "role_insufficient"
    BREAK_GLASS_EXPIRED = "break_glass_expired"
```

Errors-as-data at the boundary is deliberately *not* the convention here, unlike the prior four deep-dives — auth failures are exactly the case where "fail loudly and stop" is correct, not "return a result with an error field and let the caller decide." A `SESSION_EXPIRED` or `ROLE_INSUFFICIENT` should propagate as a real gRPC error status Gateway translates into a 401/403, not a business-logic result a caller could accidentally ignore.

---

## 4. Authentication methods — SSO, passkeys, email, SMS, and 2FA, no local passwords ever

**Resolved with real direction, not left as SSO-only by default assumption**: this project's own authentication surface supports SSO, passkeys, email, and SMS as primary login methods, with 2FA available as a composable layer on any of them — and **no local password authentication exists anywhere in this design, under any circumstance.** Worth stating the actual reasoning behind that last constraint, not just the rule: password-gated features are a real, recurring anti-pattern this project deliberately avoids — a system that lets someone log in via SSO but still requires a password to unlock some other feature has quietly reintroduced the exact thing "passwordless" was supposed to eliminate. Every method designed here proves identity one of three ways — **delegated trust to a third party** (SSO), **cryptographic possession with no shared secret at all** (passkeys), or **proof of access to a communication channel** (email/SMS one-time codes) — and nothing in this system, including step-up re-authentication for sensitive actions (§4.7), ever falls back to a memorized secret as a special case.

### 4.1 `AuthMethodProvider` — a real Provider Registry, not four independent implementations
```python
class AuthMethodProvider(Protocol):
    async def initiate(self, identifier: str) -> AuthChallenge: ...
    async def verify(self, challenge_id: str, response: str) -> AuthResult: ...
    async def is_available(self) -> bool: ...   # e.g. SMS provider unreachable, degrades to unavailable rather than erroring the whole login screen
```
Four concrete providers (`sso_provider.py`, `passkey_provider.py`, `email_login_provider.py`, `sms_login_provider.py`) behind one interface — the same swappable-never-hardcoded discipline (`docs/PRINCIPLES.md` §1.2) already applied to every other pluggable capability in this project, not a special case just because it's authentication. A user picks which method(s) they've set up; the owner controls which methods are offered at all for a given install (a self-hosted operator might disable SMS entirely if they don't want to configure an SMS provider, the same "owner controls which sources are active" pattern Ingestion's own channels already follow).

### 4.2 SSO — the existing OIDC design, unchanged, now one provider among several
`pip install authlib httpx itsdangerous` — Authlib is the right choice here specifically: framework-agnostic OAuth2/OIDC client and server implementation with genuine async support (via `httpx`), well-maintained, and the same library keeps working if a second SSO provider is ever added (Microsoft/Azure AD, Okta) without a rewrite. `itsdangerous` backs Authlib's own state/nonce signing during the handshake.

**PKCE with S256** — current best practice, not optional. Per RFC 9700 (OAuth 2.0 Security Best Current Practice), PKCE with the S256 challenge method closes a real, non-hypothetical attack class (authorization code interception). Authlib handles this natively (`code_challenge_method="S256"`), no hand-rolled crypto needed. A signed, short-lived `state` parameter round-tripped through the redirect detects CSRF/replay on the callback.

**What gets stored, and why the subject (not email) is the real identity key**: Google's ID token yields `sub` (a stable, Google-internal subject identifier, never reused even if the account's email changes) and `email`. `sub` is the actual foreign key for `User.sso_subject`, not `email` — email addresses can change on the IdP side, and keying identity to something that can silently change out from under a user is a real, avoidable bug class. Email is stored for display/contact purposes only, always re-synced from the latest ID token on login.

### 4.3 Passkeys — cryptographic possession, zero shared secret
WebAuthn/FIDO2 via a standard Python server-side library (`webauthn` or `py_webauthn`, both mature, already-tracked-category dependencies). A passkey is registered once (the browser/OS generates a public/private keypair, the private key never leaves the user's own device/authenticator), and every subsequent login is a cryptographic challenge-response proving possession of the private key — genuinely no secret is ever transmitted, stored, or guessable, which is a real security property SSO and OTP-based methods don't share (both of those still ultimately depend on a third party or a channel being trustworthy at the moment of use; a passkey doesn't depend on anything external at all). Registration and login both route through `passkey_provider.py`'s own WebAuthn ceremony, storing the public key and a credential ID against the user's own record.

### 4.4 Email and SMS — one-time codes, not magic links
Both implemented as the same underlying shape: a short-lived, single-use numeric code sent via the channel, entered back into the login form — deliberately not a magic link, since link-based flows have a real, recurring failure mode (email security scanners and link-preview bots pre-fetching the link, silently invalidating a single-use token before the actual user ever clicks it) that a typed code doesn't share. **SMS delivery reuses Notifications API's own SMS channel infrastructure** (its deep-dive, Semaphore/PhilSMS/Twilio already named as candidate providers there) rather than this API standing up a second, independent SMS-sending capability — the same "don't duplicate a capability that already exists elsewhere in the system" discipline this project applies consistently. Email delivery similarly reuses Notifications' own email channel.

### 4.5 Step-up re-authentication for sensitive actions — the same passwordless methods, never a password fallback
A sensitive action (changing the linked SSO account, disabling 2FA, initiating account deletion) requires a fresh re-authentication challenge before proceeding — but that challenge is always one of the same four methods above, never a "confirm with your password" prompt, since no password exists to confirm with. Concretely: a re-auth challenge re-runs whichever method(s) the user has configured (a fresh passkey ceremony, a fresh OTP), the same `AuthMethodProvider` interface, just invoked as a step-up gate rather than a fresh login. This is the concrete mechanism that actually delivers the "no password-gated features, anywhere, ever" principle stated in this section's own opening — a design that got this right for login but reintroduced a password for step-up confirmation would have missed the point.

### 4.6 Two-factor authentication — a composable layer, not a fifth primary method
```python
@dataclass(frozen=True)
class TwoFactorConfig:
    user_id: str
    enabled: bool
    method: Literal["totp", "sms", "email"] | None
```
2FA sits on top of whichever primary method a user authenticated with — a user who logs in via email OTP can additionally require a TOTP authenticator-app code before a session is actually issued, the same way a user who logs in via SSO can require an SMS code as a second factor. **Deliberately modeled as orthogonal to the primary method, not as a fifth item in the `AuthMethodProvider` list** — 2FA is a property of *how strict* a given login needs to be, not a separate way of proving identity in its own right; TOTP itself (a standard `pyotp`-backed implementation) is the one genuinely new primary-verification mechanism this introduces, reused as the default second-factor option precisely because it doesn't depend on email/SMS delivery succeeding a second time in the same login attempt.

### 4.6.1 Enforcement policy — install-type-dependent, resolved with real direction
**Whether 2FA is ever required (not just available) genuinely depends on the install's own real-world risk profile, not a single project-wide default** — a real, nuanced call, not a simple yes/no: a closed, internal company deployment and a public-facing multi-tenant service carry meaningfully different stakes for the same "should staff/owner be forced into 2FA" question.
```python
class TwoFactorPolicy(str, Enum):
    OPTIONAL = "optional"                       # available to every role, never required
    REQUIRED_FOR_ELEVATED = "required_for_elevated"   # mandatory for staff/owner, optional for client
    REQUIRED_FOR_ALL = "required_for_all"               # mandatory for every role
```
**Default resolution, not a single hardcoded value**:
- `tenancy_mode: single` → `OPTIONAL`. An implicit, sole owner with no other users on the install has little real benefit from being forced into a second factor against themselves.
- `tenancy_mode: multi`, **not publicly exposed** (`public_facing: false` — an internal company deployment reachable only inside a private network, or self-hosted with no Tunnel Exposure configured, `v3-deepdive-43-tunnel-exposure.md`) → `OPTIONAL` by default, owner-configurable up to either stricter tier. The reasoning directly reflects the real-world case: an owner running this for their own trusted internal team already has a meaningfully different risk profile than a service exposed to the public internet.
- `tenancy_mode: multi`, **publicly exposed** (`public_facing: true` — Tunnel Exposure configured, or DOMTRI's own hosted service) → `REQUIRED_FOR_ELEVATED` **by default, not just available**. A compromised staff or owner account on a public-facing install is a real, elevated risk to every user's own financial data, not just the account holder's own — the default reflects that stakes difference directly rather than treating every install the same. Still owner-configurable up to `REQUIRED_FOR_ALL` if wanted, though not downward below `REQUIRED_FOR_ELEVATED` while `public_facing` stays true — a deliberate floor, not a suggestion, given what's actually at stake once other people's data is involved.

`public_facing` itself is a real, explicit top-level config flag — set during Setup's own first-run wizard when Tunnel Exposure is configured (`v3-deepdive-11-setup-api.md` §7.2), or adjustable directly later — read once from config rather than Auth making a live cross-API call to Tunnel Exposure on every login, keeping the hot authentication path free of an unnecessary dependency.

### 4.7 Google's verification tier — restated precisely, since it's referenced elsewhere and worth being exact about
This project's Google OAuth usage (SSO specifically, §4.2) spans two genuinely different scope tiers, already distinguished in file 01 but worth restating together here since they're easy to conflate:
- **Login (this API's own scope)**: `email profile openid` — Google's *non-sensitive* scope tier. This qualifies for the lightweight verification path (no CASA security audit, review measured in weeks not months) — DOMTRI's hosted service uses one verified OAuth client for this, removing the unverified-app Testing-mode 100-user cap and 7-day token expiry entirely. Self-hosted installs can stay in unverified Testing mode indefinitely without issue, since a single-user/small-team install sits well under that cap regardless.
- **Drive access (Ingestion API's scope, not this one)**: a sensitive/restricted scope tier requiring full CASA audit-gated verification before real users can be onboarded via per-user OAuth — this is *why* Ingestion's Drive credential strategy defaults to service-account access today (Ingestion deep-dive §4.1.1), a completely separate verification track from this API's login scope. **Auth & Tenancy's own OAuth verification is not blocked on anything** — it's already at the achievable tier; only Ingestion's Drive-scope OAuth is waiting on the harder verification track.

---

## 5. Session management

### 5.1 The already-settled shape, restated with reasoning
File 03 already decided: server-side session + httpOnly secure cookie, not a JWT handed to the browser, specifically because owner/staff remote-control access needs *instant* revocation — a compromised owner session, a staff member's access needing to be pulled immediately, can't wait for a stateless JWT's expiry window without a blocklist (which is just a server-side session store wearing a JWT costume, at that point). Worth being precise about what "instant" means here: revocation is a single row delete/flag flip in the session store, visible on the very next request — no propagation delay, no distributed cache invalidation to coordinate, which a JWT-plus-blocklist design would still need to solve correctly.

### 5.2 Where the session store lives — a real architectural question this API surfaces, not assumed
Sessions and user accounts are **cross-user infrastructure**, not any single user's data — they can't live inside a per-user Persistence folder/repo (Persistence's own isolation model is structural, one SQLite DB per user's folder, and a login session inherently spans "which user is this" before that folder is even known). **Decision: Auth & Tenancy owns its own small, separate SQLite database** (`users`, `sessions`, `break_glass_grants` tables), living at the top level alongside Setup API's other cross-release infrastructure (config, `start.bat`/`start.sh`, models) — outside every release clone, exactly the same placement reasoning Setup API already established for exactly this kind of shared-not-per-user state. This is a genuinely new database, distinct from any user's own canonical Persistence database, and distinct from the global vendor-contribution moderation-queue table Architect API owns — three separate SQLite files/databases with three separate, deliberately non-overlapping scopes, not one shared free-for-all schema.

```python
# session/session_store.py — sketch
class SessionStore:
    async def create(self, user_id: str, role: Role) -> Session: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def touch(self, session_id: str) -> None: ...      # updates last_seen_at
    async def revoke(self, session_id: str) -> None: ...       # the instant-revocation path
    async def revoke_all_for_user(self, user_id: str) -> None: ...  # break-glass revocation, password reset, "log out everywhere"
```
No Redis, no separate cache service — consistent with this project's repeated preference elsewhere (no separate worker-server process, no Temporal server, no standalone Historian service) for not adding operational infrastructure a solo-dev project would then have to run and maintain, when a properly-indexed SQLite table serves the actual read/write volume this API sees. Session validation is a hot path (checked on effectively every authenticated request), so `session_id` needs a real index and the lookup needs to stay a single indexed row read, not a table scan — worth confirming with a bench pass (§10) rather than assumed fine by design alone, same discipline as every prior deep-dive's "reasoned, then measured" pattern.

### 5.3 Role captured at session-creation time — a real, specific security decision worth stating explicitly
`Session.role` is a snapshot taken when the session is created, not a live join against the `users` table on every request. This is a deliberate tradeoff: it makes role checks a pure session-store lookup (fast, no second query), but it means **a role change (promotion, demotion, or a staff member's access being pulled) doesn't take effect for that user's *existing* sessions until they re-authenticate, unless the role change explicitly also revokes their current sessions.** So role-management operations (Account Guardian or an owner-facing admin action) must call `revoke_all_for_user()` as part of *any* role change, not as an afterthought — worth stating as a hard requirement on every caller that touches a user's role, not something to discover from a bug report later.

### 5.4 CSRF protection for the session cookie
`SameSite=Lax` is sufficient given Gateway's own same-origin design (webapp and API share one origin per file 01's Gateway entry, eliminating the cross-origin case that would otherwise need `SameSite=None; Secure` and its own browser-compatibility quirks) — but `SameSite` alone isn't a complete CSRF defense for state-changing requests (a same-site top-level navigation can still trigger a simple GET with cookies attached in some browser configurations, and `SameSite=Lax`'s protection has known nuances around top-level navigations specifically). **A synchronizer-token pattern for state-changing requests (POST/PUT/DELETE) is still warranted as defense-in-depth** — a per-session CSRF token issued alongside the session cookie, checked on mutating requests, not relied on for read-only GETs. Worth implementing rather than assuming `SameSite=Lax` alone is sufficient, given this system's actual mutating actions include things like break-glass grants and role changes where a forged request has real consequences.

---

## 6. Roles, tenancy, and break-glass

### 6.1 Role enforcement point
File 03 already places role enforcement at the Gateway layer, before requests reach the gRPC core — Gateway checks the session's role claim and rejects owner/staff-only routes for a client-role session before any downstream API ever sees the request. This API's job is producing a trustworthy role claim on the session (§5.3); Gateway's job is acting on it. Client role's actual data-isolation guarantee is structural, not a permission check at all — it's Persistence's per-user folder/repo boundary (file 03's Save API decision), which a client-role user literally cannot reach outside of regardless of any bug in a permission check, a defense-in-depth property worth stating explicitly since it means a role-check bug in Gateway is a real problem but not a catastrophic one for client-role data specifically.

### 6.2 Tenancy mode as a genuine short-circuit, not just a config flag
`tenancy_mode: single` doesn't just change *behavior* — it changes how much of this API's own code path even executes. A self-hosted single-user install has exactly one implicit user, no login screen, no session cookie negotiation, no OIDC handshake — Setup API's first-run wizard creates the one owner account locally and every subsequent request is trivially "authenticated" as that owner. Worth designing `tenancy.py`'s resolution so `multi`-mode code (OIDC flow, session cookie issuance, role enforcement) is structurally skipped in `single` mode, not merely defaulted to always-owner — a self-hosted user should never see OIDC machinery attempt to run at all, not see it silently succeed with a hardcoded identity.

### 6.3 Break-glass grant lifecycle
```python
# break_glass/grant.py — sketch
async def request_grant(staff_user_id: str, target_client_user_id: str, reason: str, duration_minutes: int) -> BreakGlassGrant:
    """reason is required and non-empty — enforced here, not left to caller discipline."""

async def check_access(staff_user_id: str, target_client_user_id: str) -> bool:
    """Called by Persistence/Search-Query before granting staff read access
    to a client's folder — returns True only for an active, unexpired,
    unrevoked grant covering exactly this staff/client pair."""
```
Every grant is logged via the Audit API (file 01 #14) — a privileged, security-relevant action, distinct from this API's own operational logging. Notifications API is the consumer that surfaces the grant to both the owner and the affected client (file 03's decision — dual notification, not just an audit trail); Auth doesn't send notifications itself, it's the source of truth the Notifications API reads from. Grant expiry is enforced at `check_access()` time (an expired grant simply returns `False`), not by a background sweep that revokes on a timer — the sweep still exists for cleanliness (marking visibly-expired rows), but the actual security boundary never depends on the sweep having run recently. **This sweep, and the equivalent expired-session cleanup job, are now both actually registered** in Background Workers' own consolidated job registry (`v3-deepdive-12-background-workers-api.md` §6.4) — previously described here in principle but never connected to a real scheduled job.

---

## 7. Groups
**Extracted to its own dedicated document, `v3-deepdive-41-groups.md`** — cross-cutting across four APIs (this one, Persistence, Search/Query, Export Framework) with its own data model and six gRPC RPCs, past the point where it belonged as a subsection here (`docs/PRINCIPLES.md` §1.8's threshold). Summary: lets an owner or a designated group manager organize users into teams whose receipts get automatically pooled for aggregate, labeled reporting — a genuine third access-control shape, deliberately distinct from both plain per-user isolation and break-glass. Membership data still lives in this API's own top-level database (§5.2's placement reasoning), consumed by the dedicated document's own package.

---

## 8. Asyncio, free-threading, and profiling

### 8.1 Where asyncio is load-bearing
Every OIDC handshake step (redirect construction, token exchange, userinfo fetch) is a network call via Authlib's `httpx`-backed async client — this API's hot paths are I/O-bound end to end, the same shape as Ingestion's own conclusion in its deep-dive (§7 there). Session-store reads/writes are local SQLite I/O, async-wrapped the same way Persistence's own SQLite access would be (not yet its own deep-dive, but the same technique applies here without needing to wait for it). **The new auth methods (§4) don't change this shape**: passkey verification is a fast, native cryptographic operation (elliptic-curve signature verification, sub-millisecond, not worth its own async-dispatch discussion at this scale), and email/SMS OTP delivery is I/O — a call into Notifications' own already-async channel infrastructure — not a new concurrency category.

### 8.2 Free-threading
Minimal relevance for the same reason as Ingestion's own conclusion — no compute-bound pure-Python hot path exists in this API's scope to begin with. The native dependencies worth tracking: whatever cryptographic library Authlib/`itsdangerous` lean on underneath (typically `cryptography`, itself backed by OpenSSL bindings), and now also the WebAuthn library (`webauthn`/`py_webauthn`, §4.3's own open question) once a choice is made. **Telemetrees ownership, consistent with every prior deep-dive**: track `authlib`, `cryptography`, and the eventual WebAuthn library's free-threading-support status as Dependencies Warden entries rather than asserted as a fixed fact here.

### 8.3 Profiling
Given the I/O-bound shape, the more relevant operational signal for this API is OIDC/passkey/OTP round-trip latency and session-store lookup latency under load, which is Health API's live-diagnostic territory more than a `py-spy`/Tachyon bench-suite concern — consistent with Ingestion's own conclusion that not every API needs the GIL-contention profiling story the compute-heavy APIs (OCR, Inference, Preprocessing) needed front-and-center.

---

## 9. gRPC surface (`.proto` sketch)

```protobuf
service AuthService {
  rpc InitiateOIDCLogin(InitiateLoginRequest) returns (InitiateLoginResponse);   // returns the redirect URL + state
  rpc CompleteOIDCLogin(CompleteLoginRequest) returns (SessionResponse);         // the callback handler
  rpc RegisterPasskey(RegisterPasskeyRequest) returns (RegisterPasskeyResponse);       // §4.3 — the WebAuthn registration ceremony
  rpc InitiatePasskeyLogin(PasskeyLoginRequest) returns (PasskeyChallengeResponse);
  rpc CompletePasskeyLogin(PasskeyAssertionRequest) returns (SessionResponse);
  rpc InitiateEmailLogin(EmailLoginRequest) returns (OtpSentResponse);                 // §4.4
  rpc VerifyEmailLogin(OtpVerifyRequest) returns (SessionResponse);
  rpc InitiateSmsLogin(SmsLoginRequest) returns (OtpSentResponse);
  rpc VerifySmsLogin(OtpVerifyRequest) returns (SessionResponse);
  rpc ConfigureTwoFactor(TwoFactorConfigRequest) returns (TwoFactorConfigResponse);      // §4.6
  rpc InitiateStepUpReauth(StepUpRequest) returns (StepUpChallengeResponse);               // §4.5
  rpc ValidateSession(ValidateSessionRequest) returns (SessionResponse);          // Gateway's per-request check
  rpc RevokeSession(RevokeSessionRequest) returns (RevokeResponse);
  rpc RequestBreakGlassGrant(BreakGlassRequest) returns (BreakGlassResponse);
  rpc CheckBreakGlassAccess(BreakGlassCheckRequest) returns (BreakGlassCheckResponse);
}
(Group management RPCs — `CreateGroup`, `AddGroupMember`, etc. — moved to `GroupsService`, `v3-deepdive-41-groups.md` §9, since Groups is no longer a subsection of this API.)

message SessionResponse {
  string session_id = 1;
  string user_id = 2;
  string role = 3;
  int64 expires_at_unix = 4;
  string error_code = 5;
}
```
`ValidateSession` is the highest-volume call by far (effectively every Gateway request) — worth keeping its response shape minimal and its server-side path as close to a single indexed lookup as possible (§5.2), since anything added here is paid on every request in the system.

---

## 10. Config surface

```
auth:
  tenancy_mode: multi                    # single | multi — see §6.2
  methods_enabled: [sso, passkey, email, sms]   # owner controls which are offered at all, §4.1
  oidc:
    providers_enabled: [google]           # Provider Registry — future providers added here, not code changes elsewhere
    google:
      client_id: ""
      client_secret: ""
  passkey:
    rp_id: ""                                # the WebAuthn relying party ID, set per-deployment
  otp:
    code_length: 6
    ttl_seconds: 300
  two_factor:
    totp_issuer_name: "DOMTRI"                 # shown in the user's authenticator app
    policy: auto                                 # auto | optional | required_for_elevated | required_for_all — "auto" resolves per §4.6.1's own install-type logic; an explicit value overrides it
  public_facing: false                             # set by Setup's wizard when Tunnel Exposure is configured, §4.6.1's own enforcement-floor signal
  session:
    ttl_hours: auto                          # auto resolves to 720 (30 days) unless public_facing: true, then 168 (7 days) — see §12's resolution; explicit override always wins
    csrf_protection: synchronizer_token     # see §5.4
  break_glass:
    default_duration_minutes: 60
    max_duration_minutes: 480
```

---

## 11. Testing hooks

- `tests/unit/core/auth/` — OIDC flow mocked at Authlib's client boundary (no real Google round-trip in unit tests); a dedicated test asserting `sub`, not `email`, is what a session's identity actually keys on (§4.2), since this is exactly the kind of assumption that silently breaks without a regression test catching it.
- **Role-change revocation test** (§5.3): a role change that doesn't call `revoke_all_for_user()` should fail a lint/test check, not just be a documented convention — worth a concrete enforcement mechanism (a decorator or a required parameter on the role-change function itself) rather than trusting every future caller to remember.
- **No-password-fallback-anywhere test**: a static/lint check across the entire codebase for any code path resembling password hashing, a password input field, or a "confirm with your password" prompt — the concrete enforcement of §4's own opening principle, not just a documented intention. Given how easy "just add a password field" is to slip in later as a quick fix for some future edge case, this deserves an actual automated check, not just a reviewer remembering the rule.
- **Step-up re-auth bypass test** (§4.5): confirms a sensitive action genuinely cannot proceed without a fresh challenge-response, not just a UI-level prompt that a direct API call could skip.
- **Provider degradation test**: confirms `AuthMethodProvider.is_available()` returning `False` for one method (e.g. the SMS provider being down) correctly hides only that option from the login screen rather than breaking login entirely — the same graceful-degradation discipline (`docs/PRINCIPLES.md` §4.4) applied to authentication itself.
- **Session-store lookup bench case**: confirm `ValidateSession`'s hot path stays a single indexed SQLite read under realistic concurrent load, not degrading into a scan — the concrete measurement behind §5.2's "worth confirming, not assumed" note.
- **Break-glass expiry bench case**: a grant created with a short duration, confirming `check_access()` correctly returns `False` the instant it expires, without depending on a background sweep having run.
- Failure-injection: a CSRF-token-missing mutating request, confirming it's rejected rather than silently accepted under `SameSite=Lax` alone.

---

## 12. Open questions for this deep-dive (logged, not guessed at)

- (Whether local password-based auth exists — resolved, no longer open. **Explicit direction: no local passwords, ever, under any circumstance.** SSO, passkeys, email, and SMS one-time codes are the four supported primary methods, with 2FA available as a composable layer on any of them — full design in §4. Account Guardian's own file 01 entry listing "password reset" as an owned capability is now confirmed stale and should be corrected to reflect account recovery instead, which Account Guardian's own deep-dive already does correctly — its own §5 already uses the "account recovery" framing, not "password reset," so this correction is really just file 01's own summary catching up to what the actual deep-dive already says.)
- **Session TTL, resolved: 30 days for `single`-tenant and non-public-facing `multi`-tenant, 7 days for `public_facing: true` installs.** Mirrors the same install-type-dependent reasoning §4.6.1 already established for 2FA — a public-facing install carries genuinely higher exposure risk per session, worth a real, shorter default rather than one TTL for every risk profile. Both values are config, not hardcoded, and an owner can tune either.
- **Passkey library, resolved: `py_webauthn`.** Duo Security's own library, actively maintained, the more commonly recommended of the two viable options for exactly this use case — a reasonable, low-stakes implementation choice, not worth further deliberation.
- (2FA enforcement policy — resolved, no longer open. Install-type-dependent, not a single project-wide default: `single`-tenant stays optional, `multi`-tenant not publicly exposed stays optional-but-configurable, `multi`-tenant publicly exposed defaults to mandatory for staff/owner with a real floor that can't be configured back down while `public_facing: true` — full design in §4.6.1.)
- **Passkey as the sole method with no recovery path** — still genuinely coupled to Account Guardian's own unresolved recovery-verification-criteria question (its deep-dive §12); not independently resolvable here, correctly left open until that document's own question resolves.
- **Multiple SSO providers beyond Google** — a real future-roadmap/business question (which provider, when), not a technical gap; this deep-dive's Provider Registry design already accommodates it structurally (§4.1) whenever that decision gets made.
- **Session store bench numbers** — a required pre-launch verification task, not a design gap: the testing hooks above already specify the exact bench case (§11), it just hasn't been run yet against real load.
- (Group-related open questions — multi-group membership, group-manager assignment UX, webapp/TUI surfaces — moved to `v3-deepdive-41-groups.md` §11, since Groups is no longer a subsection of this API.)
