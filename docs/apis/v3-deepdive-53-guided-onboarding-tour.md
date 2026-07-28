# V3 Deep Dive: Guided Onboarding Tour (Webapp sub-API)

**Parent:** `v3-deepdive-44-webapp.md` (a new screen-adjacent capability, not previously in that document's own inventory).

**Companion files:** `v3-deepdive-45-design-system.md` (the tour overlay is a genuine shared UI primitive, reusable beyond first-time onboarding), `v3-deepdive-14-interface-api.md` §3.1 (the Settings entry that replays the tour, mirroring the same `MenuItemSpec` pattern the TUI's own settings already use).

**Status:** New dedicated document. Real, explicit direction: a full animated, visual tour with sound effects — skippable, replayable from Settings, and deliberately *not* a persistent nagging banner.

---

## 1. Scope & boundary

This document owns the first-time guided tour experience — step sequencing, animation, sound, skip/resume/replay behavior. It does not:
- **own tour content authorship** — which steps exist and what they say is product content, not a technical design question this document resolves; the *mechanism* for defining and playing a sequence of steps is what's designed here.
- **own the shared overlay/spotlight component itself** — the underlying "highlight this element, show a callout" primitive lives in the Design System (`v3-deepdive-45-design-system.md`), since it's genuinely reusable beyond first-time onboarding (a future feature announcement tour could reuse it); this document owns the *tour-specific* orchestration built on top of that primitive.

---

## 2. Package layout

```
webapp/src/features/onboarding-tour/
  __init__.ts
  tour-definitions.ts         # the actual step content for the first-time client tour
  TourPlayer.tsx                 # orchestration — see §4
  useTourProgress.ts                # the persisted-progress hook — see §5
  sfx/
    tour-sounds.ts                    # sound-cue playback — see §7
```

---

## 3. Data model

```typescript
interface TourStep {
  id: string;
  target: string;           // a stable selector/ref for the element this step highlights
  title: string;
  body: string;
  animation: 'fade-in' | 'slide-in' | 'pulse-highlight';   // a small, deliberately closed set — see §6
  sfx: string | null;         // a sound-cue identifier, or none
}

interface TourProgress {
  userId: string;
  tourId: string;               // "first-time-client-tour" today; the shape supports future tours
  currentStepIndex: number;
  completed: boolean;
  skippedAt: string | null;       // ISO timestamp — set on skip, distinct from completed
}
```
**`TourProgress` is stored server-side, in the user's own Persistence data, not just browser-local state** — a deliberate choice: a user starting the tour on one device and continuing on another shouldn't lose progress, and "replay from Settings" needs a durable record that survives a cleared browser cache. Read/written through the Client Data Layer's own query/mutation hooks (`v3-deepdive-46-client-data-layer.md`), the same pattern every other piece of user state in this webapp already follows.

---

## 4. Playback — skippable, no nagging banner, ever
`TourPlayer` renders on a new client-role user's first authenticated load (checked against `TourProgress.completed`/`skippedAt` both being unset) and **never again automatically** — skip or completion both permanently retire the automatic trigger. **A hard, explicit anti-pattern this design deliberately avoids**: no persistent "Complete your onboarding!" banner, badge, or reminder anywhere in the UI after a skip — skipping means skipping, genuinely, not "dismissed until the next nag." The *only* way the tour reappears is a user's own deliberate action.

---

## 5. Replay from Settings — the one, permanent re-entry point
A `MenuItemSpec` entry, "Replay Welcome Tour" — the same declarative menu-data pattern driving both the TUI and webapp settings screens (`v3-deepdive-14-interface-api.md` §3.1) — calls `useTourProgress`'s own `resetAndStart()`, which sets `currentStepIndex` back to 0 without touching `completed`'s own historical value (a user who's already completed the tour once and replays it isn't treated as a "first-time" user again for any other purpose that might key off `completed`).

---

## 6. Animation — Motion, the current standard, and real accessibility obligations
**Motion** (the actively-maintained, renamed Framer Motion — `motion/react`, ~30kB, the clear 2026 standard for exactly this kind of declarative UI animation, confirmed current rather than assumed) drives the highlight/callout transitions. **`prefers-reduced-motion` is a hard requirement, not a nice-to-have**: `useReducedMotion()` (Motion's own built-in hook) gates every animation — a user with this OS-level preference set still gets the tour's full informational content, just with animations swapped for instant transitions rather than motion, never a degraded or incomplete experience, only a differently-presented one. The deliberately small, closed set of animation types (§3) exists specifically so this reduced-motion fallback is simple and complete to implement, rather than an open-ended animation vocabulary where some exotic case gets missed.

---

## 7. Sound effects — native `Audio` API, with a real mute control
Short, one-shot sound cues (a step-advance chime, a completion flourish) via the browser's native `Audio` API — deliberately not a full audio-management library (Howler.js and similar) given the actual need here is simple, one-shot playback, not mixing, spatial audio, or complex state management; adding a dependency for capability this document doesn't need would be the wrong-sized tool, consistent with this project's own recurring "match the tool to the actual requirement" discipline. **A real, visible mute control is part of the tour UI itself** (not buried in a separate settings page) — sound is genuinely optional from the first moment a user encounters it, given autoplay-with-sound is exactly the kind of thing that can be actively unwelcome depending on where someone is when they open this. Respects the same "genuinely optional, not just quieter" principle `prefers-reduced-motion` handling (§6) already establishes for animation.

---

## 8. Asyncio/concurrency — not applicable in the Python sense
Same as every other webapp sub-API document in this corpus — browser-side TypeScript.

---

## 9. Testing hooks
- **No-nag regression test**: confirms that after a skip, no component anywhere in the tree renders any onboarding-reminder UI — the concrete enforcement of §4's explicit anti-pattern, not just a documented intention.
- **Cross-device resume test**: confirms `TourProgress` read on a second device correctly resumes from the server-persisted `currentStepIndex`, not from zero.
- **Reduced-motion completeness test**: confirms every tour step's full informational content is still reachable with `prefers-reduced-motion` set — a screen-reader-and-reduced-motion pass, not just "does it not crash."
- **Mute-respects-preference test**: confirms muting during the tour actually silences every subsequent cue, and confirms the mute state itself doesn't need to be re-set every single tour step.

---

## 10. Open questions for this deep-dive (logged, not guessed at)
- **Tour content itself** (§1) — the actual steps, copy, and which elements get highlighted for the first-time client tour aren't authored here, only the mechanism that would play them. Genuinely deferred product/copy work, not a technical design gap.
- **Future tours beyond the first-time one** — `TourProgress.tourId`'s shape already accommodates more than one named tour (a feature-announcement tour, say), but none beyond the first-time client tour are actually planned or designed here. Real, deliberately deferred future scope.
- **SFX asset sourcing, resolved: a licensed sound-effect pack, not custom-recorded audio.** Custom recording is real production work not justified for short UI cues — a licensed royalty-free pack is the standard, low-cost approach for exactly this need.
