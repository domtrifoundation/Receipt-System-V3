# V3 Deep Dive: Gateway API

**Companion files:** all prior deep-dives — this is the one API every browser request passes through before reaching any of them.

**Status:** Nineteenth deep-dive session. Already substantially specified in file 01 (single-origin correction, webapp-serving decision) — this session formalizes it into the standard package/contract shape.

---

## 1. Scope & boundary

Gateway is the FastAPI REST/WebSocket layer in front of the gRPC core, exposed via Cloudflare Tunnel. It owns: translating browser HTTP/WebSocket calls into internal gRPC calls, serving the webapp's static build, session-cookie authentication at the edge, and request-layer defense-in-depth (rate limiting, input validation). Like Interface API, Gateway is a detachable client of the core process, not part of it — `docs/PRINCIPLES.md` §1.7's process-separation-via-gRPC principle applies here identically, which is exactly why the third bullet below is possible at all. It does not:
- **contain business logic** — every route is a thin translation to a gRPC call; Gateway doesn't decide what a request means, only authenticates it and forwards it.
- **own file-content scanning** — that's Content Security's job; Gateway's job is the network/request layer, not payload inspection.
- **run in self-hosted single-user installs that don't need it** — since all real logic lives in the gRPC core, a self-hosted single-user install can skip running Gateway entirely and talk to the core directly if it has no need for the webapp.

---

## 2. Package layout

```
services/gateway/
  __init__.py
  app.py                  # FastAPI app instantiation
  routes/
    __init__.py
    auth_routes.py            # OIDC redirect/callback, session cookie issuance
    upload_routes.py            # direct upload — see §5
    webhook_routes.py             # Drive webhook callback passthrough to Ingestion
    static.py                      # webapp bundle serving, per-channel — see §4
  middleware/
    __init__.py
    rate_limit.py                 # see §6
    session_auth.py                 # role-claim check before requests reach gRPC core
  grpc_clients.py           # typed gRPC client stubs for every core API
  errors.py
```

---

## 3. Single-origin design — a real simplification, not just tidiness
Webapp and API share one process/origin (file 01's correction from an earlier `api.` subdomain plan) — the webapp calls API routes as relative same-origin paths, never a cross-origin URL. This eliminates CORS configuration entirely and simplifies the session cookie: `SameSite=Lax` is sufficient same-origin (Auth deep-dive §5.4 already relies on exactly this), where a cross-origin design would have needed `SameSite=None; Secure` and its own browser-compatibility quirks. Any rate-limit differentiation between static assets and API calls is path-based routing, not a subdomain split.

---

## 4. Per-channel frontend/backend pairing — the real bug this design prevents, and the mechanism that actually delivers it
**Gateway serves the webapp's static build in every deployment mode, not just self-hosted** — a corrected decision, not the original plan. The original idea (Cloudflare Pages serving the frontend separately) doesn't cleanly support per-user channel selection (Beta/Stable/Alpha, Update API's own deep-dive territory), since Pages' single/branch-deployment model has no clean way to serve different frontend versions to different users based on an individually-chosen channel. Having frontend-version-routing (Pages) and backend-version-routing (Gateway/Supervisor) as two independent mechanisms risks them silently disagreeing — a real, nasty bug class (a Beta-channel backend paired with a Stable-channel frontend), not hypothetical. **Reusing Gateway's own per-user-channel routing to also serve the matching frontend bundle guarantees the pairing stays consistent by construction** — there's structurally no way for them to drift apart, since one routing decision determines both.

### 4.1 The build mechanism — every release clone builds its own webapp bundle
**Previously stated as a principle only — this is the actual mechanism, corrected after a direct challenge asked how this genuinely works given the multi-clone reality this project's own architecture already established.** Every release clone contains the full repo at that commit, webapp source included (`v3-deepdive-webapp.md` §2). A new step, `build_webapp()`, runs as part of the *same* finalize routine that already handles `strip_development_content()` and `dev_fixtures` seeding (Setup deep-dive §4.1) — for every fresh clone, whether the very first one or any subsequent Update API clone, not a separately-scheduled or optional step:
```python
async def build_webapp(clone_dir: Path) -> None:
    """Runs the production build (Vite, v3-deepdive-webapp.md §3) inside
    clone_dir/webapp/, producing a static bundle at
    clone_dir/webapp/dist/. Runs unconditionally for every clone — dev
    mode still needs a working webapp to develop against, it just also
    keeps the dev server available alongside the production build."""
```
This is what actually makes §4's "consistent by construction" claim true: the webapp bundle a given release serves was compiled from *that exact commit's* frontend source, never a separately-versioned artifact that could drift from the backend it ships alongside.

### 4.2 The serving mechanism — reusing channel resolution, not reimplementing it
```python
# routes/static.py
async def resolve_webapp_bundle(session_channel: str) -> Path:
    """Resolves the requesting session's channel against Supervisor's
    own ActiveRelease record (v3-deepdive-38-supervisor.md §3.1) — the
    exact same lookup Gateway's own grpc_clients.py already performs
    to route API calls to the correct backend release — then serves
    static files from that same release clone's own webapp/dist/.
    One routing decision, reused for both static assets and API
    calls, which is the actual mechanism behind this section's whole
    'structurally impossible to drift apart' claim, not just a stated
    intention."""
```

### 4.3 No hardcoding at build time — deployment-specific config is injected at serve time, not baked in
**A real consequence of one compiled bundle potentially serving many different deployments**: the same webapp build (for a given channel/commit) might be served by DOMTRI's own hosted instance *and* by any number of self-hosted installs, each with its own Cloudflare Tunnel hostname, its own branding, its own feature availability (self-hosted's Groups/tier autonomy, `v3-deepdive-41-groups.md`, being a clear example of something that varies per-deployment). None of that can be baked into the build at compile time without either building a separate bundle per deployment (defeating the whole point of §4.1's one-build-per-clone model) or accepting configuration drift. **Resolved: Gateway injects deployment-specific runtime config into `index.html` at serve time** — a small `window.__RESIBO_CONFIG__` script tag populated from that instance's own top-level config (API base path, branding, enabled-feature flags), read by the webapp's own bootstrap code before rendering anything. The compiled JS/CSS bundle itself stays genuinely deployment-agnostic; only this one small injected object varies per instance, consistent with `docs/PRINCIPLES.md` §1.3's swappable-never-hardcoded discipline applied to the frontend specifically.

---

## 5. Tunnel Exposure — Cloudflare Tunnel as the default swappable provider
**Full treatment in `v3-deepdive-43-tunnel-exposure.md`** — a real sub-API, not just a vendor mentioned in passing. "Exposed via Cloudflare Tunnel" was previously stated as a fact throughout this corpus with zero actual design behind it — no config/credential management, no swappable-provider treatment despite this project's own modularity pledge, no health monitoring of the tunnel itself. Corrected there: a `TunnelProvider` Protocol with Cloudflare Tunnel as the default concrete provider, structurally-accommodated alternatives for self-hosted operators who want a different exposure mechanism, and the tunnel's own health folded into Health API's live diagnostic layer.

---

## 6. Direct upload flow
```python
# routes/upload_routes.py — sketch
@router.post("/api/v1/upload")
async def direct_upload(file: UploadFile, session: Session = Depends(require_session)):
    """Browser POSTs the file → Gateway authenticates via the session
    cookie (middleware/session_auth.py) → forwards over internal gRPC to
    Ingestion API, which routes it through Content Security before
    hashing/storing the blob and emitting a trigger event for Execution
    Core's debounce-coalescing window."""
```
Mechanically the simplest of Ingestion's three channels (its own deep-dive §4.2) — no push/poll uncertainty, no third-party reliability question; the upload arriving *is* the trigger.

---

## 7. Defense-in-depth — not solely delegated to Cloudflare
Cloudflare's Tunnel provides real network-edge DDoS protection, but Gateway still owns its own request rate-limiting and input validation — never relying on one vendor as the single point of protection, stated explicitly in file 01 as a deliberate posture, not an oversight. Concretely: a per-session and per-IP token-bucket rate limiter (`middleware/rate_limit.py`), applied per-route-group (auth endpoints stricter than general API calls, matching Auth deep-dive §4's own note about rate-limiting the OIDC validation path), and standard request-body validation (size limits, content-type checks) before anything reaches gRPC — catching malformed/oversized requests at the edge rather than letting them consume a gRPC core worker's time.

---

## 8. Asyncio
FastAPI is asyncio-native by design — file 02's own table calls this "the textbook case." Every route here is `async def`, every gRPC client call `await`ed, no blocking work anywhere in this API's own scope.

---

## 9. gRPC clients, not a new gRPC surface
Gateway doesn't define its own `.proto` service — it's a *client* of every other API's gRPC surface, translating REST/WebSocket calls into the appropriate typed client stub call. `grpc_clients.py` holds one typed client per core API, generated from each API's own `.proto` definitions rather than hand-written per route.

---

## 10. Config

```
gateway:
  rate_limit:
    per_ip_requests_per_minute: 60
    per_session_requests_per_minute: 120
    auth_routes_requests_per_minute: 10   # stricter — see §6
  max_upload_size_mb: 25
```

---

## 11. Testing hooks
- **Channel-pairing consistency test**: a request from a Beta-channel session confirms *both* the gRPC backend calls route to the Beta release *and* the static bundle served is the Beta frontend build — direct validation of §4's core claim, not just trusted from the design reasoning.
- **Rate-limit bypass attempt**: confirms a burst past the configured threshold is actually rejected, not just logged.
- **Runtime config injection test**: confirms the same compiled bundle, served against two differently-configured instances, actually renders with each instance's own branding/API base path — direct validation of §4.3's "genuinely deployment-agnostic build" claim.

---

## 12. Open questions for this deep-dive (logged, not guessed at)
- **Exact rate-limit thresholds, locked in as reasonable starting placeholders.** Real traffic analysis can tune the specific numbers later; the mechanism and its config-driven shape are what matter for shipping, not the precise threshold values.
- (WebSocket reconnection/backoff policy — resolved, no longer open. Full design in `v3-deepdive-46-client-data-layer.md` §3: exponential backoff starting at 1s capped at 30s, a visible-but-unobtrusive "Reconnecting…" UI state, and full-state resync on reconnect rather than delta-gap-filling.)
