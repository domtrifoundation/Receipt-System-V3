# V3 Plan (5/5: V2 REFERENCE — failure modes + a desired-feature wishlist for future deep-dives)

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md`

**Scope boundary — read before editing this file:** V2 is analyzed for two things only: (1) what broke and why, so V3 independently avoids it, and (2) which *behaviors/features* Francis wants in V3 too, noted here purely as a temporary reminder so they aren't forgotten before each API's deep-dive session. **Neither of these is "V2's code/implementation is correct, reuse it."** Nothing in this file is a spec. The wishlist entries below get resolved, redesigned from scratch, and deleted from this file as each API's real deep-dive happens — this file is scratch memory for the planning team, not a permanent part of the design.

## Resolved (factual clarifications only — what a V2 term meant, not an endorsement of it)
- **"AI mode" = `ai_agent.py`** — an agentic tool-calling system: per-context toolsets, a mutating-action whitelist, a propose-then-confirm pattern for settings changes, dispatch that returns `{"error": ...}` instead of crashing.
- **llama.cpp/ONNX discrepancy — `bench.py` was simply stale.** V2's dev docs state llama-cpp-python was `[deprecated]` in favor of ONNX; the leftover llama.cpp references in `bench.py` just weren't updated.
- **V2 had no schema-version field anywhere in `config.py`.** Its "migration" handling (`migrate.py`, `sheet_migrate.py`) was two one-time, hand-written, user-confirmed scripts, not a general mechanism.
- **The menu system (`menus.py`/`menu_system.py`, 2,383 + 986 lines) was declarative-in-code**, not literally hardcoded strings — a typed-item system (`ActionItem`, `SubmenuItem`, `JumpToSettingItem`, `BoolItem`, `ToggleListItem`, `NumberItem`, `TextItem`, `ChoiceItem`, `PathItem`, `Separator`, `BackItem`), just declared in 2,383 lines of Python rather than as data.
- **`llm_fixer`** = un-garbling OCR noise via local JSON extraction, fully in-process — the exact in-process design the postmortem flags as a root cause of V2's GIL-freeze bug.
- **Google Drive ingestion was OAuth + folder-ID polling only** — no push notifications existed.
- **Multithreaded-run stalling root cause** = `LLM_CALL_LOCK`, a single loaded model's non-reentrant generation state (a hard constraint of that architecture, not a fixable bug in isolation) — every receipt needing the LLM queued on one lock.
- **Content-addressable blob storage eliminates a bug class that existed because V2 sorted files into vendor-named folders** — two decoupled workers correcting vendor identity from different evidence would "fight each other forever" over folder placement. This isn't "V2's folder system had a flaw to patch" — it's confirmation that folder-based sorting itself was the wrong approach, independently replaced in V3's design.
- **The real financial-data-in-source-git-history incident happened** because V2's setup wizard defaulted data paths inside the program's own directory — confirms why V3 keeps data paths structurally outside the code tree, a V3 design decision made on its own merits, not something V2 did well.

## V2 Feature Wishlist — remaining items only (all 32 APIs now have their own deep-dive; every item below survived that process as a genuine remaining gap, not an oversight)

*Format: what V2 did, stated neutrally as "this existed" — never as "do it this way." Each surviving entry is a real, confirmed gap in its API's own deep-dive document, cross-referenced there.*

**Tool Call API / Inference API — capped tool-call conversation history:** V2 bounded tool-call conversation history rather than letting it grow unbounded. Neither `v3-deepdive-02-inference-api.md` nor `v3-deepdive-07-tool-call-api.md` designed an equivalent bound during their own sessions — a genuine gap, not resolved by either document's own scope. Needs a real value/mechanism decided at whichever API ends up owning the orchestration loop's own history (likely wherever Reconciliation's or Execution Core's tool-calling loop actually lives, not yet pinned down precisely).

**Background Workers API — permanently-failing job retry guard:** V2 had a specific failure mode where a permanently-failing job could retry forever. `v3-deepdive-12-background-workers-api.md` designed the job-classification/routing mechanism but did not design a retry cap for a *registered background job itself* (distinct from Execution Core's own per-stage bounded retry with escalation, which only covers pipeline stages, not arbitrary registered Background Workers jobs) — a real, confirmed gap, not just an unstated assumption.

**Matching API — fuzzy-matching pitfalls checklist:** V2 had hard-learned lessons (case sensitivity, over-eager collapsing of distinct names, generic words causing false positives, needing multiple sightings before trusting a correction). `v3-deepdive-15-matching-api.md` designed the scorer and the two-way match mechanism but did not design safeguards against any of these specific failure modes — worth a real pass incorporating them as design *risks to guard against*, not specific thresholds to copy, still not done.

**Interface API — "jump to a moved setting":** V2's menu system had this specific navigation behavior (a setting that moved location in a menu reorganization still being findable from its old reference). `v3-deepdive-14-interface-api.md` designed the menu-data schema and the `find_setting` fuzzy-search carryover, but not this specific behavior — a real, narrower remaining gap.

**Execution Core / Reconciliation API — Rescue-vs-flag-immediately ordering:** V2's "Rescue" idle-worker made one more LLM-assisted attempt at quarantined/failed receipts before requiring human review — still genuinely unresolved: (a) rescue-first, escalate to human review only after N failures, or (b) flag immediately as designed, with rescue as an idle-time fallback for flags a human hasn't reached yet. Neither Execution Core's nor Reconciliation's own deep-dive picked one — (b) keeps full transparency to the human reviewer, (a) doesn't, still worth weighing deliberately rather than defaulting to either. ("Curate" — resolved, no longer open; full self-cleaning mechanism designed in `v3-deepdive-40-temporal-learning.md` §6, distinct from ordinary contribution moderation as originally worried it might not be.)

**Reconciliation API — ATP (Authority to Print) validity checking:** an expired ATP on a vendor's receipt is a real BIR audit red flag, raised fresh (not from V2) in this file's own earlier pass. `v3-deepdive-17-reconciliation-api.md`'s check inventory (§4.1-4.9) does not include this check — a real, confirmed gap in an otherwise fairly complete inventory, worth adding as a tenth check alongside the existing nine.

**Persistence API — SLSP export format and audit-package contents:** both resolved as a *home* (Persistence's Export Framework, `slsp_summary.py`/`audit_package.py` now exist as named provider files in `v3-deepdive-13-persistence-api.md`'s package layout) but the actual field-level format of either export was never designed — the home is right, the content isn't specified yet.

## Fully resolved during the 28-API deep-dive pass — deleted per this file's own stated rule
*(kept as a one-line record of what was resolved and where, not restored as wishlist entries)*
- OCR corroboration model (LLM-arbitrated vs. deterministic vs. hybrid) → tiered deterministic-first-then-escalate, OCR deep-dive §7.
- Preprocessing variant set shape (fixed vs. parametric) → fixed named set + extension point, Preprocessing deep-dive §4.7.
- Tool dispatch error handling → errors-as-data (`ToolResult.error`), Tool Call deep-dive §5.
- Backend-vs-app tool-loop conflict → structurally resolved by V3's architecture, not just designed around: Inference API never runs an autonomous loop of its own (one-shot constrained generation per call, Inference deep-dive §5), so there's only ever one loop — the caller's — not two competing ones.
- Geo/Address multi-candidate concept → the two-axis design (multi-provider + multi-candidate), Geo/Address deep-dive §3, with a per-run call budget addressing V2's own measured cost warning.
- Matching vendor seed data → Architect's Wikidata bootstrap, Architect deep-dive §3.
- Single-source-of-truth registry for optional receipt fields → Persistence's reference-identifier typed system, already resolved in file 01, reaffirmed in Persistence deep-dive §1.
- Conditional/tiered vs. always-parallel variant generation and second-opinion escalation (both Preprocessing/OCR entries) → resolved by the scope boundary itself: neither OCR nor Preprocessing decides this, the calling orchestrator does (OCR deep-dive §1, Preprocessing deep-dive §1) — genuinely tiered/conditional by construction, not always-parallel.
- Reconciliation's long check list → twelve real checks now have concrete V3 logic, Reconciliation deep-dive §4, complete — ATP validity checking, the last remaining gap, closed out in the same pass.
- One-time migrations requiring explicit confirmation → deliberately not carried forward as a UX pattern: V3's migrations are automated, chained, and write through Persistence's own path (Migration deep-dive §3), meaning every migration is atomic and Historian-revertable, removing the specific risk manual confirmation was originally guarding against.
- Inference vision/multimodal → fully designed fresh, Inference deep-dive §7.
- Receipt type distinction, SLSP/audit-package *home*, BIR completeness flag → all already marked resolved before this pass; BIR completeness additionally now has concrete check logic, Reconciliation deep-dive §4.7.
