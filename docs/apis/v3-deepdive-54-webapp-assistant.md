# V3 Deep Dive: Webapp Assistant

**Companion files:** `v3-plan-03-decisions.md` (the original "V3 has no AI Mode" correction this document is the actual, deliberate reintroduction of — as a genuinely different, much narrower feature, not a reversal), `v3-deepdive-14-interface-api.md` §3.1 (`find_setting`, the existing fuzzy-search this enhances rather than replaces), `v3-deepdive-52-support-ticketing.md` (the support-box integration point).

**Status:** New, narrowly-scoped feature. V2 had an "AI Mode" tightly coupled to the per-receipt reconciliation pipeline — genuinely impractical once this project became a real multi-user system rather than V2's single-user-hosting design, and confirmed removed for real (Inference API's `StreamGenerate`, Tool Call's `ai_mode_chat` context — both retired, `v3-deepdive-02-inference-api.md` §9, `v3-deepdive-07-tool-call-api.md` §8). **Revised again, immediately, to a much narrower scope than the first version of this document proposed**: no persistent chat widget, no data access of any kind, no tool-calling loop — natural-language help embedded directly into two existing UI surfaces (the settings search box, the support-ticket flow), backed by Cloudflare Workers AI.

---

## 1. Scope & boundary

The Webapp Assistant owns exactly two things: helping a user find the right setting or menu item using natural language, and offering common-troubleshooting suggestions in the support-ticket flow. It does not:
- **access any user data, of any kind, ever.** Not receipts, not spend history, not account details — a hard, explicit boundary, not just "mostly read-only." The only inputs this feature ever sees are the user's typed query text and this project's own static content (the menu structure, a troubleshooting knowledge base) — never anything from Persistence, Search/Query, or any other data-holding API.
- **exist as its own persistent chat surface.** No floating widget, no standalone conversation UI. It's an enhancement mode on two surfaces that already exist for other reasons — the settings search box and the support-ticket creation flow — not a new place in the app.
- **touch the receipt-processing pipeline in any way** — the exact coupling that made V2's AI Mode impractical for a real multi-user system.
- **call any tool, or run any multi-round loop.** Given zero data access, there's nothing for a tool-calling round-trip to fetch — this is a single request/response shape, not an agentic loop.
- **run on this project's own local Inference API** — Cloudflare Workers AI stays the deliberate, separate backend choice from the original version of this document, still correct here: a lightweight, always-available surface shouldn't compete with the local Inference API's own hardware/tier-scoped resources.

---

## 2. Architecture — genuinely simpler than the first version of this document, because there's nothing live to fetch
```
cloudflare-workers/
  assistant/
    index.ts                # the Worker entrypoint — receives a query, returns a result
    static_context.ts          # bundled menu structure + troubleshooting KB, embedded at build/deploy time
    wrangler.toml                 # Cloudflare's own Worker config/deployment
```
The Worker receives the user's typed query, bundles it with the relevant static context (the current menu-data structure for settings search, or the troubleshooting KB for the support-box case), calls Cloudflare Workers AI once, and returns the result. **No `tool_bridge.ts`, no authenticated call back into Gateway, no round-trip to this project's own backend at all** — the first version of this document included a tool bridge specifically because data-query tools needed live access; with that access removed entirely, the Worker has nothing left to fetch mid-conversation. This is a real, meaningful simplification, not just a smaller feature description — the whole reason a tool-calling loop existed in the first draft is gone.

### 2.1 Where the static context comes from
The menu structure is the same `MenuItemSpec` data `find_setting` already indexes (`v3-deepdive-14-interface-api.md` §3.1) — exported at build time into `static_context.ts`, never a live query against this project's own backend. The troubleshooting KB is authored content (§8's own open question — not written here), bundled the same way. Both are non-user-specific, safe to embed directly in a Worker that has no other access to anything about the person using it.

---

## 3. Integration point 1 — settings search, natural-language mode
When a user's query in the settings search box doesn't cleanly resolve via `find_setting`'s own fuzzy-match (its deep-dive §3.1 — `rapidfuzz`-based, works well for near-exact terms but not a genuinely conversational phrasing like "how do I stop getting emails about flagged receipts"), the search box offers to ask the assistant instead. The Worker maps the natural-language query against the bundled menu structure and returns its best guess at the matching setting(s) — the UI then does exactly what a successful `find_setting` match already does (jump to that setting), the assistant is purely a smarter front-end onto an existing, already-designed navigation mechanism, not a new one.

---

## 4. Integration point 2 — support-box troubleshooting
Before a user finishes filing a support ticket (`v3-deepdive-52-support-ticketing.md`), the support box offers troubleshooting suggestions drawn from the bundled KB, matched against what they've typed so far — "this looks like it might be about a flagged receipt, here's what that means" style guidance. If it doesn't resolve their question, they file the ticket normally; nothing about the ticket-filing flow itself changes. This is a genuine, real opportunity to reduce ticket volume for common questions, not a replacement for the ticket system Support Ticketing already owns.

---

## 5. Data-handling — resolved, not just lighter than before
The first version of this document flagged a real, unresolved Privacy Policy disclosure question, since a data-query tool would have meant financial-data-derived answers flowing through a third-party API. **With data access removed entirely, that concern is resolved, not just reduced**: the only things that ever reach Cloudflare are the user's own typed query text and this project's own static, non-user-specific content. Worth confirming this explicitly with whoever reviews the actual Privacy Policy text (`v3-deepdive-06-account-guardian-api.md` §7) rather than assumed — but the technical design itself no longer has the shape that made the earlier version's concern real.

---

## 6. Cost
Still a genuine per-request cost against Cloudflare Workers AI, but a much lighter one than the first version's design — a single request per query, no multi-round tool-calling loop inflating usage. Whether this is available to every tier unconditionally or rate-limited isn't decided here, but the stakes are meaningfully lower than the original design's open question given the actual usage shape.

---

## 7. Asyncio/concurrency
The Worker runs on Cloudflare's own V8-isolate runtime, not this project's own asyncio-based concurrency model — the same "not applicable in the Python sense" carve-out already stated for the rest of the webapp's own sub-APIs, even simpler here given there's no call back into this project's own backend at all.

---

## 8. Testing hooks
- **No-data-access test**: a static check confirming `static_context.ts` never imports or bundles anything from Persistence, Search/Query, or any other data-holding API — direct enforcement of §1's hard boundary, not just a documented intention.
- **No-tool-bridge test**: confirms the Worker makes no outbound call to this project's own Gateway at all — the concrete validation that §2's simplification is real, not aspirational.
- **Fallback test**: confirms a user whose query the assistant can't resolve cleanly falls back gracefully — to `find_setting`'s own existing fuzzy-match results (§3), or to a normal ticket submission with no suggestions (§4) — never a dead end.

---

## 9. Open questions for this deep-dive (logged, not guessed at)
- **Which specific Cloudflare Workers AI model, resolved: Llama.** Meta's own widely-used, well-documented model among Cloudflare's catalog — a defensible, low-stakes default given this feature's own scope (lightweight navigation/troubleshooting help, not a task requiring the most powerful model available).
- **Cost/tier gating, resolved: available to every tier unconditionally.** The narrowed design (§2 — single request per query, no tool-calling loop) already has meaningfully lower per-use cost than the original wider draft; the stakes aren't high enough to justify gating a genuinely low-cost, helpful feature behind a tier wall.
- **Troubleshooting KB authorship** (§2.1) — the actual content isn't written here, only the mechanism that would serve it. Genuinely deferred product/content work, not a technical gap.
- **How "doesn't cleanly resolve" gets decided for §3, resolved with a concrete threshold.** `find_setting`'s own fuzzy-match score (already a real, existing value from its `rapidfuzz`-based scoring, `v3-deepdive-14-interface-api.md` §3.1) below 70% hands off to the assistant rather than showing a low-confidence best guess; at or above that threshold, `find_setting`'s own result stands on its own, no handoff needed.
