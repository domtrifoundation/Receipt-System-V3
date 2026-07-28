# CLAUDE.md Authoring Guide

This is the guide for what goes in a `CLAUDE.md` file at each level of this repo. It's a guide, not a template to copy-paste blindly — every real `CLAUDE.md` gets written once real code exists in that folder, by whoever (or whatever Claude Code session) is working there, following the conventions below rather than inventing new ones per-folder.

**Why this matters specifically for this project**: this repo will be developed substantially through Claude Code sessions, often starting fresh with no memory of prior sessions. A good `CLAUDE.md` in the right folder is the difference between a new session immediately understanding what it's looking at versus re-deriving context that already exists in 54 deep-dive documents it has no reason to re-read in full every time.

---

## 1. The core principle: proximity and altitude

A `CLAUDE.md` answers "what do I need to know to work *in this folder specifically*," at the altitude appropriate to that folder — not a copy of the project-wide principles, not a restatement of the full technical deep-dive. Three real altitudes exist in this repo, and each gets a different kind of `CLAUDE.md`:

- **Repo root** — project-wide orientation. What this project is, where the real documentation lives, the hygiene rules that apply everywhere.
- **Each Core API's own top-level folder** (`core/ocr/`, `core/auth/`, `services/gateway/`, etc.) — what this specific API owns, what it explicitly doesn't, and where its own deep-dive document lives for the full detail.
- **A sub-API's own folder**, where one exists as a real subdirectory (`core/architect/temporal_learning/`, `core/auth/groups/` if broken out that way, etc.) — the same shape as a Core API's own `CLAUDE.md`, one level deeper.

**Never write a `CLAUDE.md` that duplicates its own deep-dive document's content.** A `CLAUDE.md` points at the deep-dive and pulls out only what's needed to start working in that folder specifically — line numbers or section references are fine, full paragraphs copy-pasted from the deep-dive are not. If the deep-dive changes, a `CLAUDE.md` that quoted it at length is now two places that can drift apart; one that just points at it can't.

---

## 2. Repo-root `CLAUDE.md` — required sections

```markdown
# [Project name]

One paragraph: what this project is, in plain terms.

## Where the real documentation lives
- `docs/PRINCIPLES.md` — the cross-cutting rules every API follows (modularity,
  immutability, hygiene, transparency). Read this before touching anything.
- `docs/PROCESS_TOPOLOGY.md` — the actual process map: what runs where, what
  talks to what.
- Each Core API's own deep-dive (referenced from its own folder's CLAUDE.md).

## Hard rules that apply everywhere in this repo
- [The load-bearing ones from PRINCIPLES.md that a session working ANYWHERE
  in the repo needs to know before making a change — FrozenDict discipline,
  the Provider Registry pattern, the "no direct cross-package imports except
  through contracts.py" rule, the Forward-Compatibility Hygiene checklist.]
- **The Forward-Compatibility Pattern (`docs/PRINCIPLES.md` §3.3-3.3.1) applies
  everywhere in this repo, not just in folders that happen to touch a
  version-sensitive dependency directly.** Any code with a `FrozenDict`-typed
  field, any code with an assumption baked in about the GIL, any code that
  could plausibly interact with `asyncio` behavior that's changed across
  Python versions — checked against this policy, not assumed exempt because
  the folder's own `CLAUDE.md` didn't happen to mention it.

## Before you commit
- [Point at docs/templates/ — which template applies to which kind of change,
  and that the PR checklist is actually enforced, not advisory — see
  docs/MAINTENANCE.md §7.]
```

---

## 2.1 A real, load-bearing fact that changes what "required" means below: deep-dives are temporary, `CLAUDE.md` files are permanent
**The `v3-deepdive-*.md` planning corpus does not ship with the program.** It's real, load-bearing material during development, and it will not be present in the repo once x03.00.00 Zircon ships — `CLAUDE.md` files are the artifact that survives that removal and becomes the actual, ongoing development reference from that point forward. This has one concrete, mandatory consequence for every template below: **a `CLAUDE.md`'s own "full design" pointer must stop referencing its deep-dive before that deep-dive is removed, not after.** A `CLAUDE.md` still pointing at `v3-deepdive-01-ocr-api.md` after that file no longer exists in the repo is a broken reference in the single document every future session depends on most.

**The concrete fix, as a required final step before x03.00.00 ships**: every Core API and sub-API `CLAUDE.md`'s own "Full design" section gets rewritten from "read the deep-dive" to a genuinely self-contained summary — the real scope, the real "does not own" list, the real current API version (`docs/MAINTENANCE.md` §1's own `aXX.XX.XX` scheme) — plus a pointer to the *actual implementation code* (`contracts.py`, `service.py`) as the living source of truth from that point forward, since code that exists is a better "full design" reference than a planning document that doesn't anymore. This isn't optional polish; a `CLAUDE.md` that still assumes the deep-dive corpus exists after that corpus is gone has failed at the one job this whole guide exists for.

---

## 3. Each Core API folder's `CLAUDE.md` — required sections

```markdown
# [API name]

One paragraph: what this API owns. Copy the "Scope & boundary" section's
own opening line from the deep-dive — don't rewrite it, don't expand it.

## Full design
**During development (deep-dive corpus still present)**: `v3-deepdive-NN-[name]-api.md`
— read this before making any non-trivial change. This file is a working
summary, not a replacement for it.
**Before x03.00.00 ships (§2.1 above)**: this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the
living source of truth — the deep-dive reference above stops being valid
the moment that corpus is removed, not before.

## What this API explicitly does NOT own
[The bulleted "It does not" list from the deep-dive's own §1, verbatim or
near-verbatim — this is the single most valuable thing a CLAUDE.md can
carry forward, since "what looks like it should live here but doesn't" is
exactly the kind of thing a fresh session gets wrong without being told.]

## Forward-Compatibility Pattern applicability
[Required, not optional — even if the answer is "not applicable." One line:
does this folder's own code have any FrozenDict-typed field, any assumption
about GIL-protected state, or anything touching asyncio behavior that's
changed across Python versions? If yes, point at the specific file/pattern.
If no, say so explicitly (`docs/PRINCIPLES.md` §3.3.1) — never silently
omit this the way a swallowed section elsewhere in this project's own
history has been the recurring, avoidable mistake.]

## Real gotchas specific to this folder
[Only include this section if there's something real and specific beyond
the Forward-Compatibility line above — a known-tricky async pattern, a file
that looks like it should be edited directly but is actually generated.
Don't pad this section out for the sake of having content in it.]
```

---

## 4. Sub-API folder `CLAUDE.md` — same shape, one level deeper

Identical structure to §3, but scoped to the sub-API specifically, and its own "full design" pointer goes to its own dedicated deep-dive document (not the parent API's). Cross-reference the parent explicitly: a sub-API's `CLAUDE.md` should say which Core API it belongs under, the same way the deep-dive itself states this in its own header.

---

## 5. What never goes in a `CLAUDE.md`

- **Open questions.** Those live in the deep-dive's own "Open questions" section, which is the actual tracked, authoritative location for them. A `CLAUDE.md` that also lists open questions is a second place they can drift from the real one.
- **The full data model.** Point at `contracts.py` directly — it's the actual source of truth, and a `CLAUDE.md` that also lists every field risks going stale the moment the code changes without the `CLAUDE.md` being updated in the same commit.
- **Decisions-log-style history.** That's `v3-plan-03-decisions.md`'s own job. A `CLAUDE.md` describes the current state, not how it got there.
- **Anything that duplicates `docs/PRINCIPLES.md`.** If a rule applies everywhere, it's stated once, at the root. Repeating it in every folder's own `CLAUDE.md` is exactly the kind of multi-source-of-truth problem this whole project's own hygiene discipline exists to prevent.

---

## 6. Keeping these current

A `CLAUDE.md`'s own "what this API does NOT own" section is the part most likely to go stale as a real correction happens (the same kind of correction this project's own planning phase made repeatedly — a capability moving from one API to another, a sub-API getting extracted). **Update the relevant `CLAUDE.md` files in the same PR that makes the change**, the same "documentation updated in the same commit as what it describes" discipline `docs/MAINTENANCE.md` §6 already requires for the deep-dives themselves, extended here to cover `CLAUDE.md` files too. **The Forward-Compatibility applicability line (§3) needs the same discipline specifically whenever a version-sensitive dependency is added, removed, or its own Day-0 support status changes** — a `CLAUDE.md` that said "not applicable" and stays saying that after the folder's own code actually started touching `FrozenDict` is exactly the kind of drift this whole section exists to prevent, not a hypothetical risk.
