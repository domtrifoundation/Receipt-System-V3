# Making the README

There is no real `README.md` yet — this planning corpus describes what will exist, not what does. This document is instructions for whoever (very likely a Claude Code session) writes the actual `README.md` once real code exists to describe. Do not write the real README from this planning corpus directly; write it from the actual shipped code, using this document for structure and tone.

## Why this needs its own instructions
A README written from a plan describes intentions. A README written from real code describes what's actually true. This project's own `docs/PRINCIPLES.md` §0 (the V2 Rule) exists because designing from an existing artifact "because it's there" is a real failure mode — the same discipline applies here in miniature: **write the README from the real, current, shipped feature set, not from this planning corpus's aspirations.** If a deep-dive document describes a capability that isn't actually implemented yet, it does not belong in the README. Check `git log` and the actual package layout, not `v3-deepdive-*.md`.

## Required sections, in order
1. **One-line description** — what this is, in plain language, no jargon. Not "a receipt-processing pipeline API," something a non-technical BIR-facing small business owner would understand in one read.
2. **Install / Getting Started** — points to the GitHub Releases page and the installer, **explicitly states cloning the repo directly will not produce a working install** (see `docs/MAINTENANCE.md` §5 for the exact reasoning and the correct step-by-step — link to it or adapt its language, don't restate it differently). This is the single most important thing to get right in the whole README, since it's the first thing anyone hits when they try to use this.
3. **What it actually does** — a real, current feature list derived from which core APIs are actually implemented and working, not the full 32-API aspirational plan. If only 6 of 32 APIs are real at time of writing, the README describes 6, not 32 with a footnote. **A real, worth-including differentiator once there's something concrete to point at**: the day-0 compatibility discipline (`docs/DAY_ZERO_COMPATIBILITY_PROMISE.md` is the actual, verified source material for this — don't invent new marketing language, adapt what's already there and keep it honest about what's currently tracked versus adopted).
4. **Screenshots/GIF** — of the actual running TUI or webapp, once either exists. Never a mockup.
5. **License** — matches the actual `LICENSE` file at repo root.
6. **Contributing** — one or two lines, pointing to `CONTRIBUTING.md`, not restating it.
7. **Links** — `docs/index.md` for the full documentation set.

## Tone
Direct, not marketing copy. This project's own established voice throughout its planning corpus is "state the thing, then the reason, briefly" — the README should read the same way, not shift into a different, more promotional register just because it's the front door.

## What never belongs in the README
- Aspirational features not yet built (link to `docs/` for the design/roadmap instead, clearly labeled as design docs, not shipped features).
- Anything from the V2 postmortem or the planning corpus's own internal reasoning — that's `docs/` material, not front-door material.
- Installation instructions that mention `git clone` as a way to get a *running* instance. `git clone` is correct advice only in the context of "I want to read/contribute to the source," immediately followed by "for a working development environment, see `docs/MAINTENANCE.md` §5" — never presented as sufficient on its own.

## Keeping it current
The README describes the current Stable channel's actual feature set. When a new API or major capability ships to Stable, updating the README's feature list is part of that PR, not a follow-up — the same discipline `docs/MAINTENANCE.md` §6 already states for `docs/PRINCIPLES.md` itself.
