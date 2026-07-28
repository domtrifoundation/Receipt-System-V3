# V3 Deep Dive: Reimport Diff Review UI (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` §5.10 (which explicitly flagged this as "needing real UX design attention beyond what this document specifies" — this document is that attention).

**Companion files:** `v3-deepdive-30-reimport.md` (the three-way diff data model this screen visualizes), `v3-deepdive-45-design-system.md` §4 (the shared `DiffViewer` component this screen is built on, not a bespoke implementation).

**Status:** New dedicated document, extracted per `docs/PRINCIPLES.md` §1.8's threshold — genuinely one of the more interaction-complex screens in the application, explicitly self-flagged as needing this treatment rather than being padding for its own sake.

---

## 1. Scope & boundary

This document owns the screen a user reaches after uploading a corrected export back into the system — reviewing what Reimport's own three-way diff (its deep-dive) found, and resolving any genuine conflicts. It does not:
- **own the diff algorithm itself** — Reimport's own three-way comparison (export-snapshot vs. user's edited upload vs. current canonical state) is entirely server-side; this screen renders the result and collects the human's resolution choices.
- **own the merge/write** — once a user resolves every conflict, the actual write-back routes through Persistence's normal path exactly like any other correction; this screen's job ends at collecting a decision per field.

---

## 2. Layout — three-way, not two-way, and the UI has to make that legible
A naive two-column diff (old vs. new) doesn't actually represent what Reimport's own algorithm resolved — it has *three* states per field (the export snapshot, what the user changed it to, what the canonical value is *now*, which may have moved independently since the export was generated). The screen shows all three columns for any field that's part of a genuine conflict, and collapses to a simple single-value display for any field that resolved cleanly (only the user changed it, or only canonical state changed) — **not every field needs the full three-way view, only the ones Reimport's own algorithm actually flagged as conflicting** (`v3-deepdive-30-reimport.md`'s own conflict-detection logic, never re-derived client-side).

---

## 3. Built on the shared `DiffViewer`, not a bespoke implementation
Uses the Design System's own `DiffViewer` component (`v3-deepdive-45-design-system.md` §4) — the same component the staff moderation-review queues use — configured for this screen's own three-way data shape. Per-field resolution actions: accept the user's edit, keep the current canonical value, or manually enter a third value — each field resolved independently, a batch-submit only once every conflicting field has an explicit decision, never a silent "accept everything" shortcut that could paper over a conflict nobody actually looked at.

---

## 4. Progress and abandonment
A reimport with many conflicts is a real, potentially lengthy review task — the screen shows a clear count ("12 of 47 conflicts resolved") and supports leaving mid-review and resuming later, backed by the Client Data Layer's own optimistic-update-avoidance stance for anything touching unconfirmed state (`v3-deepdive-46-client-data-layer.md` §5) — a partially-resolved reimport session persists server-side, not held only in unsaved client state that a closed tab would silently lose.

---

## 5. Asyncio/concurrency — not applicable in the Python sense
Same as every other webapp sub-API document.

---

## 6. Testing hooks
- **Three-way legibility test**: confirms a genuine conflict actually renders all three values distinguishably, and confirms a cleanly-resolved field does *not* clutter the view with an unnecessary three-way display it doesn't need.
- **Resume-after-close test**: confirms a partially-resolved review session's progress survives closing and reopening the screen — direct validation of §4's persistence claim.
- **No-silent-batch-accept test**: confirms there's no code path that resolves a conflict without an explicit per-field decision having been made.

---

## 7. Open questions for this deep-dive (logged, not guessed at)
- **Bulk resolution for genuinely repetitive conflicts, resolved with a real design that preserves the no-silent-batch-accept guarantee.** A "resolve all like this one" affordance groups visually-similar conflicts for batch selection, but still requires one explicit confirmation covering that specific group — the human reviews the *grouping itself* before confirming, never a silent apply-to-everything-matching action that skips review entirely. This is the load-bearing distinction: batching the *review* is fine, batching away the *review itself* is exactly what §6's own test already guards against.
- **Conflict-review assignment for a `multi`-tenant/Groups context, resolved: yes, a group manager can review on behalf of a member.** Consistent with a group manager's existing aggregate visibility (Groups' own deep-dive §4.1) — but the resolution is clearly attributed in Historian's own log as "resolved by [manager], on behalf of [member]," never indistinguishable from the member having resolved it themselves.
