# V3 Deep Dive: Frontend Auth & Session Flow (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` §4 (route guards, briefly mentioned there, fully designed here).

**Companion files:** `v3-deepdive-05-auth-tenancy-api.md` §4 (the OIDC flow this document's redirect handling is the client-side half of), `v3-deepdive-19-gateway-api.md` §2-§3 (the session-cookie/single-origin design this flow depends on).

**Status:** New dedicated document, extracted per `docs/PRINCIPLES.md` §1.8's threshold — real security implications, its own genuine state machine (login → redirect → callback → session-established), and gates every protected route in the application.

---

## 1. Scope & boundary

This document owns the browser-side half of authentication — initiating the OIDC redirect, handling the callback, and route-level session/role guarding. It does not:
- **own the actual security boundary** — every enforcement point that matters is server-side (Auth's own session validation, Gateway's `session_auth.py` middleware). Everything in this document is UX — redirecting before wasting a render, showing the right screen — never the thing actually preventing unauthorized access.
- **own session storage mechanics** — the session cookie itself is `httpOnly`, set by Gateway (its deep-dive §2), genuinely inaccessible to this document's own JavaScript by design; this document only reacts to session state via API responses, never reads or manages the cookie directly.
- **implement its own single-tenant bypass** — for `tenancy_mode: single` installs, Auth's own implicit-owner path (its deep-dive §6.2) means this flow's login screen simply never renders at all; not a separate code path here, a consequence of what the server-side session check returns.

---

## 2. The login flow, concretely

```
1. User hits a protected route with no valid session.
2. Route guard (§4) redirects to /login.
3. /login calls Gateway's InitiateOIDCLogin REST endpoint, gets a
   redirect URL + state, browser navigates to Google's own consent
   screen — nothing here touches Google credentials directly, this
   is purely bouncing the browser through Gateway to Auth's own
   already-designed OIDC flow (its deep-dive §4).
4. Google redirects back to Gateway's own callback route (not this
   webapp's own route — the callback lands server-side first).
5. Gateway completes the OIDC exchange, sets the httpOnly session
   cookie, redirects the browser to the webapp's own post-login
   landing route.
6. This webapp's own bootstrap code makes one call (a lightweight
   "who am I" query) to confirm the session is valid and get the
   current user's role — this is what the Client Data Layer's own
   query cache seeds with, everything downstream reads from there.
```

---

## 3. Session expiry and refresh — reacting, not managing
This webapp never proactively refreshes a session or tracks its own expiry countdown — Auth's own session TTL (its deep-dive §10) is the actual authority. A request that comes back with an expired-session error is the trigger: the Client Data Layer's own error handling (its deep-dive §5) catches this specific error shape globally and redirects to `/login`, rather than every individual query hook needing its own expired-session handling. One place, one behavior, consistent across the whole application.

---

## 4. Route guards — UX convenience, restated precisely
```typescript
// routes/_authenticated/route.tsx — sketch
export const Route = createFileRoute('/_authenticated')({
  beforeLoad: ({ context }) => {
    if (!context.session) {
      throw redirect({ to: '/login' });
    }
  },
});
```
`_staff` route group layers an additional role check on top of the same pattern. **Worth restating from §1 rather than assumed understood**: this `beforeLoad` check exists so a `client`-role user doesn't even see a staff screen begin to render before being redirected — a UX nicety. The actual data those staff screens would have shown is never sent to a `client`-role session in the first place, because Gateway's own server-side check (its deep-dive §2) already refuses the underlying API calls regardless of what the frontend route guard does or doesn't catch.

---

## 5. Asyncio/concurrency — not applicable in the Python sense
Same as the parent document and its siblings — browser-side TypeScript, no Python-interpreter concerns.

---

## 6. Testing hooks
- **Guard bypass attempt**: confirms direct URL entry to a `_staff` route by a `client`-role session redirects correctly *and* confirms the underlying data call still fails server-side even if the frontend guard were somehow bypassed — never trusting the frontend check as the real boundary, tested accordingly.
- **Expired-session global handling test**: confirms an expired-session response from any query hook (not just one specific one) triggers the same redirect-to-login behavior, catching a hook that implements its own inconsistent handling.
- **Single-tenant bypass test**: confirms `tenancy_mode: single` installs never render a login screen at all, consistent with §1's stated behavior.

---

## 7. Open questions for this deep-dive (logged, not guessed at)
- **Multi-tab session behavior, resolved: every tab reacts immediately, via a real cross-tab mechanism.** The browser's own `BroadcastChannel` API (or a `localStorage` event listener as the older-browser fallback) notifies every open tab the moment a session expires or is revoked — a standard, well-established pattern for exactly this problem, not something requiring a bespoke mechanism.
- **"Remember where I was" post-login redirect, resolved: yes.** A user redirected to `/login` from a deep link lands back on that original page after successful login — the expected, standard UX; a default landing page only applies when there was no specific page being requested in the first place (e.g., navigating to the bare root URL while unauthenticated).
