# How to Write Review Comments — Format Guide

This is the format for review comments on the V3 planning corpus. Following it precisely is what lets comments get parsed reliably and matched back to the exact document/section they're about — a comment that doesn't follow this structure risks being missed or misread entirely.

**Write comments in a separate file, never by editing the original documents directly.** One file per reviewer (e.g., `REVIEW_boss.md`, `REVIEW_domtri.md`) — this keeps a clean, attributable record of who said what, and means the original corpus stays untouched until changes are actually made in response.

---

## The exact structure

```markdown
# Review: [Your name]
Date: [date]

## FILE: v3-deepdive-05-auth-tenancy-api.md

### §4.6.1
[Q] Why does the 2FA floor apply to public_facing installs specifically —
what about a multi-tenant install that's internal but still large?

### §10
[FLAG] The session TTL of 7 days for public-facing installs feels short.
Reconsider?

### (general, no specific section)
[OK] Overall this document looks solid.

## FILE: v3-deepdive-22-billing-subscription-api.md

### §3.3
[CORRECTION] "GENEROUS_DEFERRED" — I actually meant the charge happens
after the CURRENT cycle ends, not after the next one. Re-read this section
and fix if it says otherwise.

[Q] Does PayMongo actually support this level of proration natively, or
does our own code have to calculate it?
```

---

## The four pieces every comment needs

1. **A `## FILE:` line** — the exact filename, copied exactly as it appears in the corpus (e.g., `v3-deepdive-05-auth-tenancy-api.md`, not "the auth doc" or "file 5"). Everything under a `## FILE:` line belongs to that document until the next `## FILE:` line appears. Get the filename exactly right — this is the single most important part of the whole format, since it's what makes automated matching possible at all.

2. **A `### §` line** — the section number the comment is about, copied from that document's own heading (e.g., `### §4.6.1`, matching the document's own `## 4. Authentication methods` → `### 4.6.1 Enforcement policy...` numbering). If a comment applies to the whole document rather than one section, use `### (general, no specific section)` instead of guessing a number.

3. **A type tag in square brackets, first thing in the comment**:
   - `[Q]` — a question, expecting an answer back before anything changes.
   - `[CORRECTION]` — something is factually wrong or doesn't match what you actually meant/intended; needs a fix.
   - `[FLAG]` — a concern or hesitation, not necessarily wrong, but worth a second look or a conversation.
   - `[IDEA]` — a suggestion or enhancement, not a problem with what's there now.
   - `[OK]` — explicit approval — genuinely useful to write down, not just silence, since it confirms a section was actually read and accepted rather than skipped.

4. **The comment itself** — plain language, as short or long as the point actually needs. No particular formatting required beyond the type tag at the start.

---

## Multiple reviewers on the same section

If DOMTRI and the user both comment on the same file/section, that's fine — each reviewer's own file keeps their comments separate, and both get read and cross-referenced when responding. No need to coordinate or merge comments before sending them back; two `[Q]` tags on the same section asking different things is normal and expected.

## Multiple comments on the same section

Stack them under the same `### §` heading, each on its own `[TYPE]` line, rather than starting a new section heading for each one:

```markdown
### §3.3
[Q] Does the owner get a warning before a proration policy change applies
to already-active subscriptions?
[FLAG] "immediate_charge" as the config default — should this actually
default to the friendlier option instead?
```

## If you don't know the section number

Better to guess at the nearest one and note it's a guess than to skip the section number entirely:

```markdown
### §3 (approximate — this might be in 3.2 or 3.3, not sure which)
[Q] ...
```

A `### (general, no specific section)` comment still gets read, but a comment with a specific (even approximate) section number is faster to act on, since it doesn't require re-reading the whole document to find what it's about.

---

## What NOT to do

- Don't paste large chunks of the original document text into your comment file "for context" — the filename and section number are enough context; repeating the original text just makes the comment file longer without adding anything.
- Don't edit the original `v3-*.md` files directly and send those back — always use a separate comment file per the structure above.
- Don't skip the type tag — a comment with no `[Q]`/`[CORRECTION]`/`[FLAG]`/`[IDEA]`/`[OK]` tag is genuinely harder to triage quickly, since the tag is what signals whether something needs a reply, a fix, or was just a note.
