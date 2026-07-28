# Documentation Placement: Repo vs. GitHub Wiki

The decision: outward-facing documentation moves to the GitHub Wiki; developer documentation and tooling stays in-repo under `docs/`. This document is the actual policy plus a current-state assessment — not a one-time migration list, since most of what will eventually be outward-facing content doesn't exist yet.

---

## 1. The actual rule, stated plainly

**Stays in-repo (`docs/`):**
- Anything a contributor needs while writing code — architecture, principles, hygiene rules, PR templates, `CLAUDE.md` conventions.
- Anything that needs to version alongside the code it describes — a deep-dive document is only correct for the version of the code it was written against, and belongs in the same commit history as that code, not a separately-versioned Wiki page that could drift out of sync unnoticed.
- Internal, non-public material regardless of audience — see §3 on `LEGAL_REVIEW_NEEDED.md` specifically.

**Moves to the Wiki:**
- Anything a *user or operator* needs, that doesn't need to version tightly with a specific commit — setup guides, FAQs, troubleshooting, "how do I configure X" walkthroughs.
- Content that benefits from the Wiki's own easier non-developer editing (a support person fixing a confusing FAQ answer shouldn't need to open a pull request).

---

## 2. Current-state assessment — what actually exists today

**Honest finding**: at this stage of the project, almost everything that currently exists under `docs/` is developer-facing by the rule above, not because the policy is wrong, but because this has been a planning and architecture phase — the genuinely outward-facing content (a real end-user guide, FAQ, troubleshooting docs) mostly doesn't exist yet, since there's no shipped product yet for it to document.

**The one real candidate that exists today:**
- `docs/SELF_HOSTED_NOMINATIM.md` — a genuine operator-facing setup guide, not developer documentation. Move this to the Wiki once the Wiki exists, and leave a short stub in `docs/` pointing to the Wiki page (so a developer who stumbles on the old path isn't left with a dead end).

**Stays in-repo, confirmed, not migration candidates:**
- `PRINCIPLES.md`, `PROCESS_TOPOLOGY.md`, `MAINTENANCE.md`, `CLAUDE_MD_GUIDE.md`, `REVIEW_COMMENT_FORMAT.md`, `MAKING_README.md`, `docs/templates/*`, `docs/testing/TOOLKIT.md` — all developer/contributor-facing by the rule above.
- Every `v3-deepdive-*.md` and `v3-plan-*.md` — these are the actual technical source of truth for the system's own design, tightly coupled to the code they describe. This is developer documentation in the fullest sense, never Wiki content.
- `PRE_STABLE_BENCH_VALIDATION.md` — a developer/testing-process document.

**`SETUP_WIZARD_SCRIPT.md` — a real, worth-noting edge case, not a clean yes/no.** This document is closer to *implementation content* than documentation — it's the literal script the wizard uses, not a description of it. It stays in-repo, since it needs to version with the actual wizard code it drives. **Once the software actually ships, a genuinely separate, Wiki-appropriate "Setting Up Your Instance" page — written *for* end users, derived from this script but not identical to it — would be real, valuable Wiki content.** That page doesn't exist yet and isn't this document; noted here so it's on the list for whoever writes user-facing content later, not confused with the script itself.

**`DAY_ZERO_COMPATIBILITY_PROMISE.md` — the same shape of edge case.** Also implementation-adjacent source material rather than finished user-facing copy — it stays in-repo since it needs to track the real, current tracked-dependency inventory alongside the code it describes, but a genuinely separate, marketing-appropriate version of its own §3 ("why this matters") belongs in the eventual README and possibly its own Wiki page once real users would care about it. Same rule as `SETUP_WIZARD_SCRIPT.md`: don't confuse the source document with the future public-facing copy derived from it.

---

## 3. A real, separate question worth flagging: should `LEGAL_REVIEW_NEEDED.md` even be in the public repo at all?
This isn't really a repo-vs-Wiki question — it's a repo-vs-private-location question, and worth raising here since it's adjacent. `LEGAL_REVIEW_NEEDED.md` is a formal compliance memorandum discussing real penalty exposure, registration timelines, and unresolved legal risk. If this repository is or becomes public, that document being publicly readable is a genuinely different consideration than "is this developer or user content" — it's "should this be visible outside DOMTRI at all." **Recommendation: keep this document in a private location** (a private repo, an internal drive, wherever DOMTRI keeps genuinely sensitive internal material) **rather than the public-facing planning repo, once that repo's own public/private status is decided** — flagged here rather than assumed resolved by this document's own placement in the current corpus.

---

## 4. What to actually do, in order

1. When the GitHub Wiki is set up, move `SELF_HOSTED_NOMINATIM.md` to it, leave a stub redirect in `docs/`.
2. Confirm `LEGAL_REVIEW_NEEDED.md`'s own placement (§3) as a real decision, separate from the Wiki question.
3. As real user-facing content gets written going forward (a setup walkthrough derived from `SETUP_WIZARD_SCRIPT.md`, an FAQ, troubleshooting docs), it goes straight to the Wiki — never staged in `docs/` first and migrated later, since there's no version-coupling reason for it to live in-repo even temporarily.
4. Revisit this document itself once the Wiki actually has content in it, since its own "current-state assessment" (§2) will be stale the moment that happens — the same "update in the same PR as the change it describes" discipline every other doc in this corpus follows.
