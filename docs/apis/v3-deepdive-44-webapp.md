# V3 Deep Dive: Webapp

**Companion files:** `v3-deepdive-14-interface-api.md` §4 (framework/state-management resolution, owns this document by reference), `v3-deepdive-19-gateway-api.md` §4 (the build-and-serve mechanism this document's own build output plugs into), `v3-deepdive-43-tunnel-exposure.md` (how the deployment this webapp runs against gets reached at all).

**Status:** New dedicated document. A real, substantial gap: "React + TypeScript" was resolved as a framework choice, but nothing in this corpus designed the actual application — no page inventory, no routing, no component architecture — despite a dozen other documents each independently flagging their own piece of webapp UI as "not designed here, deferred to Interface API's future work." This document is where those all actually land.

---

## 1. Scope & boundary

The Webapp owns the browser-side application itself — routing, page/screen composition, component architecture, and how it consumes Gateway's REST/WebSocket surface. It does not:
- **own how it gets served** — that's Gateway's own build-and-serve mechanism (its deep-dive §4); this document owns what gets built, not how the right version reaches the right user.
- **own how the deployment gets reached from the public internet** — Tunnel Exposure (`v3-deepdive-43-tunnel-exposure.md`) is a separate concern this application doesn't need to know anything about.
- **contain business logic** — every screen is a thin presentation layer over Gateway's own REST/WebSocket translation of the gRPC core; a validation rule, a permission check, a computed value all live at the API layer the webapp calls, never duplicated in frontend code as a second source of truth.
- **decide state-management or framework choices** — already resolved in Interface API's own deep-dive (§4): React, TypeScript, Zustand for client state, TanStack Query for server state. This document builds on those decisions, doesn't re-litigate them.

---

## 2. Package layout

```
webapp/
  src/
    routes/                  # TanStack Router file-based routes — see §4
      __root.tsx
      _authenticated/            # everything requiring a session
        files/                     # My Files — see §5.1
        receipts/$receiptId/         # receipt detail — see §5.2
        groups/                        # Groups management — see §5.4
        vendors/                         # temporal_learning manual management — see §5.5
        settings/
        account/
      _staff/                     # staff/owner-only route group, its own auth guard
        review/                        # contribution + flag review queues — see §5.6
        billing/
        fleet/
      login.tsx
    components/                # shared, reusable UI — see §7
    stores/                   # Zustand stores — genuinely local/client state only
    queries/                  # TanStack Query hooks — one per Gateway REST/WS surface
    lib/
      config.ts                  # reads window.__RESIBO_CONFIG__, see Gateway deep-dive §4.3
      grpc-web-client.ts           # typed client generated from .proto, mirrors Gateway's own grpc_clients.py pairing
    App.tsx
  public/
  index.html                 # the injection target for Gateway's runtime config script tag
  vite.config.ts
  package.json
  tsconfig.json
```

---

## 3. Build tooling — Vite, the current standard for this stack
Vite, not Create React App (long deprecated) or a hand-rolled webpack config — the actively-maintained, fast-refresh, ESM-native standard for a React+TypeScript app in 2026, with first-class TanStack Router and Zustand support requiring no special configuration. `npm run build` produces the static `dist/` bundle that Gateway's own `build_webapp()` step (its deep-dive §4.1) invokes for every fresh release clone.

---

## 4. Routing — TanStack Router
**TanStack Router, not React Router.** Reasoning specific to this project, not a generic preference: it's from the same family as TanStack Query (already resolved as the server-state library, Interface deep-dive §4) — one ecosystem, one set of conventions, one less paradigm for a Claude Code session to hold in context when working across data-fetching and routing in the same session, which matters given this project's own LLM-assisted-development reasoning already drove the React and Zustand/TanStack Query choices for exactly this reason. Fully type-safe route params (a receipt ID in the URL is a typed string, not stringly-typed and re-parsed at every call site) and built-in route-level data loading that composes cleanly with TanStack Query's own cache.

**Route groups mirror the real authorization boundary, not just a folder convention**: `_authenticated/` requires a valid session (any role), `_staff/` requires `staff`/`owner` — enforced by a route-level loader checking Auth's own session claim before rendering anything, the same authorization check Gateway's own `session_auth.py` middleware already performs server-side (its deep-dive §2) — the frontend route guard is a UX convenience (redirect to login before wasting a render), never the actual security boundary, which stays entirely server-side where it belongs. **Full treatment of the login flow, session expiry handling, and route guards themselves in `v3-deepdive-47-frontend-auth-session.md`** — extracted given the real security implications and its own genuine state machine.

---

## 5. The screen inventory — every previously-scattered UI requirement, actually compiled in one place

Nine other documents each independently said some version of "the webapp needs a screen for this, not designed here." This section is where all of them actually get accounted for.

### 5.1 My Files — the primary client-facing screen
Browsing/searching a user's own receipts (Search/Query's own consumer, its deep-dive), filterable by date/vendor/flag status, with Group-scoped view switching for a group manager (`v3-deepdive-41-groups.md` §7's `search_group()` as the underlying query).

### 5.2 Receipt detail view
**Full treatment in `v3-deepdive-48-receipt-detail-screen.md`** — extracted given its real scope: the receipt image, extracted fields, and Historian's narrative track genuinely rendered (`v3-deepdive-29-historian.md` §6, "displayable in the webapp" was the entire point of that track's design, never actually realized until that document).

### 5.3 Upload flow
Direct upload (Gateway deep-dive §6) — drag-and-drop or file picker, streaming upload progress, handing off to Execution Core's own live-progress view once processing begins.

### 5.4 Groups management
Create/manage groups, add/remove members, toggle `is_group_manager`, view the group export — the exact requirement `v3-deepdive-41-groups.md` §11 flagged as needed and undesigned. A `staff`/`owner`-and-group-manager-gated screen, enforcing the same permission boundary Groups' own `ListGroupMembers` RPC already gates server-side (§4.1 there).

### 5.5 Vendor/corporation/branch/franchiser management
The exact requirement `v3-deepdive-40-temporal-learning.md` §8 specified precisely: browsing/searching the directory, adding a new local entry, the explicit share action, and — for staff — the review queue plus direct-to-global writes. Respects the same layer/sharing/staff-authority distinctions that document's own gRPC surface (§10 there) already enforces.

### 5.6 Staff review queues
Two genuinely distinct queues, not one generic "review stuff" screen: **contribution review** (temporal_learning's own moderation pipeline, §6 there) and **flag review** (Review/Flagging's own staff queue, its deep-dive) — different data shapes, different actions, worth keeping visibly separate the same way this project's own documents keep the underlying concepts separate rather than merging them into one blurred screen for convenience.

### 5.7 Run monitor / live progress
Consumes Execution Core's own streaming `GetRunStatus` RPC — the live view of an in-progress run, the actual reason server-streaming was part of the case for gRPC in the first place (`docs/PRINCIPLES.md` §1.7).

### 5.8 Settings
Mirrors Interface API's own menu-data-driven settings model (its deep-dive §3) on the client-facing side — the same `MenuItemSpec`/`find_setting` data structure drives both the TUI's settings screen and this one, not two independently-maintained settings UIs that could drift apart.

### 5.9 Account management
Account Guardian's own consumer — data export request, deletion request with the grace-period explanation shown plainly (its deep-dive §6.3's own state machine, made legible to the person actually requesting it).

### 5.10 Reimport
**Full treatment in `v3-deepdive-49-reimport-diff-ui.md`** — extracted given the real interaction complexity this section originally flagged as needing "real UX design attention beyond what this document specifies." The human-facing side of Persistence's own three-way diff (`v3-deepdive-30-reimport.md`).

### 5.11 Billing / tier management
Owner-only — Billing API's own consumer (its deep-dive), and for self-hosted `multi`-tenant owners specifically, the "run every tier free, or configure your own PSP" choice (`v3-deepdive-22-billing-subscription-api.md` §1's own corrected scope).

### 5.12 Fleet / Active Services (staff, mirrors the TUI's own screen)
The webapp equivalent of Interface's own TUI fleet screen — owner/staff visibility into service health, useful for a staff member who's on the webapp rather than sitting at the TUI console.

### 5.13 First-time guided onboarding tour
**Full treatment in `v3-deepdive-53-guided-onboarding-tour.md`** — extracted given its own persisted data model, real animation/accessibility/audio obligations, and cross-references from Design System and Settings. Summary: an animated, sound-enabled tour for a new client-role user's first login, skippable with no persistent nagging reminder afterward, replayable anytime from Settings.

### 5.14 Webapp Assistant — natural-language settings search and support-box troubleshooting
**Full treatment in `v3-deepdive-54-webapp-assistant.md`** — extracted given its own external dependency (Cloudflare Workers AI) and its own Cloudflare Worker component outside the main Python backend. Summary: not a chat widget — natural-language help embedded directly into the existing settings search box and support-ticket flow, backed by Cloudflare Workers AI. Zero data access of any kind and no tool-calling loop, a deliberately much narrower design than an early draft of this feature considered — the replacement for V2's tightly-coupled "AI Mode," scoped down hard once that coupling was confirmed impractical for a real multi-user system.

---

## 6. Client Data Layer, and the frontend's own version of the immutability pledge
**Full treatment in `v3-deepdive-46-client-data-layer.md`** — extracted given its own real interface (typed query/mutation hooks), its role resolving Gateway's own previously-open WebSocket reconnection question, and its use across every screen in the application. Summary: `docs/PRINCIPLES.md` §2.1 requires `FrozenDict`/frozen dataclasses at every backend API boundary; this codebase is TypeScript, not Python, so the literal mechanism doesn't carry over — but the underlying principle does. TanStack Query's own cache is treated as read-only from every component's perspective, Zustand stores use the `set((state) => ({...}))` pattern exclusively — the frontend's own enforcement of the same "don't reach in and mutate shared state directly" discipline `FrozenDict` enforces at the Python layer.

---

## 7. Design System / Component Library
**Full treatment in `v3-deepdive-45-design-system.md`** — extracted given real component contracts, use across every screen, and a genuine theming/swappability question of its own. Summary: a shared `components/` library (buttons, form controls, the diff-viewer used by both Reimport and the moderation-review screens, since both are fundamentally "show a proposed change, let a human accept/reject/edit it") — built once, reused, never copy-pasted per screen. Consistent with `docs/PRINCIPLES.md` §1.4's "no hardcoded TUI" principle applied to its actual frontend equivalent.

---

## 8. Asyncio/concurrency — not applicable in the Python sense, stated explicitly rather than silently skipped
This document's own scope is entirely browser-side JavaScript/TypeScript — `docs/PRINCIPLES.md` §5's concurrency-bucket classification and the Python 3.15/3.16/Tachyon/free-threading forward-compatibility pledge are Python-interpreter concerns that genuinely don't apply to this codebase at all, worth stating plainly rather than leaving the absence ambiguous. The closest real equivalent, worth naming: React's own concurrent rendering features (already standard in the React version this project targets) and TanStack Query's own request deduplication/background-refetch behavior — both handled by their respective libraries, not something this document needs to design.

---

## 9. Testing hooks
- **Route-guard test**: confirms an unauthenticated request to any `_authenticated/` or `_staff/` route redirects to login rather than rendering, and confirms a `client`-role session can't reach `_staff/` routes even by direct URL entry.
- **Runtime-config injection test**: cross-referenced from Gateway's own deep-dive §11 — confirms the webapp's bootstrap code correctly reads `window.__RESIBO_CONFIG__` rather than any build-time-baked value.
- **Shared-component reuse test**: a lint rule (not just a convention) flagging a new table/diff-viewer implementation that doesn't use the shared component from §7, catching the "just copy-pasted a similar screen" failure mode before it ships.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- (Reimport's diff-visualization UX — resolved, no longer open here. Full design in `v3-deepdive-49-reimport-diff-ui.md`.)
- **Mobile/responsive scope, resolved: desktop-oriented, with one explicit, real exception.** The general webapp experience prioritizes desktop; mobile is a lesser concern there. But the scanner-capture flow specifically (Ingestion's own in-browser scanner, `v3-deepdive-04-ingestion-api.md` §4.3) needs to genuinely work on a mobile browser, since that's exactly where someone would realistically use it — a phone's own camera, not a desktop webcam. Two different bars for two genuinely different use cases within the same webapp, not one uniform responsive-design commitment applied everywhere equally.
- (Design system/component library starting point — moved to `v3-deepdive-45-design-system.md` §9, its own open question now.)
- (Offline/degraded-connectivity behavior — resolved for the WebSocket-reconnection case specifically, see `v3-deepdive-46-client-data-layer.md` §3.1. Genuine offline mutation-queueing remains open, tracked in that document's own open questions.)
