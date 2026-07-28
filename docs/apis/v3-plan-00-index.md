# DOMTRI Foundation Receipt System V3 — Development Plan (1/5: INDEX)

**Companion files (read all 5 for the full plan):** `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md`

**All 32 core APIs now have their own full deep-dive document** — the original 28 (`v3-deepdive-01-ocr-api.md` through `v3-deepdive-28-telemetrees-api.md`) plus four added later during corpus-wide sweeps (Accounting Sync #29, Status Page #30, Support Ticketing #31, Agent Control #32; see file 01's own numbered list, which is authoritative) — package layout, data contracts, dependencies, hardware/concurrency, gRPC surface, config, testing hooks, and open questions for each. **9 sub-APIs/sub-capabilities that live inside a parent API's own package also got their own full deep-dive documents** (`v3-deepdive-29-historian.md` through `v3-deepdive-37-dependencies-warden.md`) rather than being folded into their already-large parent documents — Historian, Reimport, Export Framework, Archive Sync, and Disaster Recovery under Persistence; Watchdog under Health; Webhook Subscription Manager under Ingestion; Proving Grounds under Update; Dependencies Warden under Telemetrees. Each parent document's own section for that sub-API carries a pointer to the full version. These 5 index/plan files remain the high-level record of decisions and cross-API rules; the deep-dive documents are where each API's actual implementation-level design lives. Where this file's Per-API Comparison Checklist below says "RESOLVED," it's referring to the corresponding deep-dive having settled the question — check that document for the real detail, not just this summary line.

**Status:** Living document. Pre-development. No code until systems are mapped.
**Prime directive:** Function over form. Every feature that was bolted on in V2 becomes a core API from line one. Plumbing, immutability, and repo hygiene come before UI polish.

---

## Postmortem: what V2 got wrong (for reference, so we don't repeat it)

- **Runtime**: started on llama.cpp, migrated to ONNX — both broken at different points; migration was reactive, not planned.
- **Terminal interface**: hijacked the main CMD to suppress/replace output, while *also* running a separate child CMD for logs — fighting itself.
- **In-process AI runtimes**: ran inference in-process before migrating to separate server processes, way too late.
- **GUI**: hard-coded directly in Python, no menu/nav framework — unmaintainable, undocumented.
- **Interface portability**: the entire interactive keyboard control layer was Windows-only — the input handler no-oped on non-Windows entirely, and console mode was configured via raw ctypes/kernel32 calls. Not just "hardcoded, no framework" as originally characterized — genuinely non-portable, a separate failure worth naming.
- **OCR**: multi-engine corroboration was an addon, not the core.
- **Preprocessing**: single "best" B&W contrast preset was the whole strategy; multi-spectral variant was an addon instead of a generation pipeline.
- **LLM integration**: fought the programmatic scoring/value-selection system instead of having a defined role; no real runtime/hardware settings.
- **Background workers**: added late, uncoordinated, broke things.
- **Excel writing**: fragile → atomic writes + git backups bolted on later, which itself broke live batch writing/display.
- **Everything ran single-item instead of batched**, despite the workload being embarrassingly parallel.

The rule for V3: if it was an addon in V2, it's a **core API with a defined contract** in V3, designed before its first consumer exists.

---

## Instructions for a Claude Code Audit Pass (read this if you're auditing this doc against the real repo)

Francis uploaded the full V2 repo (`Receipt-System.7z`) mid-planning, and everything that used to require repo access has already been resolved by directly reading V2's actual source, docs, and complete 256-commit history — see `v3-plan-04-v2-audit-findings.md` (file 5/5).

**Scope boundary — read this before touching V2's code at all:** V2 is analyzed for exactly one reason: to identify what broke, why, and what risk V3 must independently design around. **V2 is never a source of code to port, patterns to adopt, data to reuse, or "good practices" to carry forward.** It was deprecated because the combination of everything in it made stable development impossible — that verdict stands, full stop. Every V3 design decision — down to individual thresholds, recipes, and config values — gets derived independently on its own merits at that API's future deep-dive, even where a V2 number happens to exist. File 5 is a record of *failure modes to avoid*, not a shopping list of things to reuse. If anything in file 5 reads like an endorsement of V2 or a recommendation to carry something over, that's a drafting error to fix, not an instruction to follow.

If you're a Claude Code session with the real repo in front of you:
1. **Don't re-investigate anything in file 5's "Resolved" section** — those are settled facts about what a term meant or what caused a bug, re-deriving them again wastes a pass.
2. **Work through "Per-API V2 Comparison Checklist" below** for anything not yet covered by file 5 — each entry has a specific question grounded in what's already known (a module name, a config key, a described behavior) — the goal is always "what failure mode does this reveal," never "is this worth keeping."
3. Report new findings back **in file 5**, either as a factual "Resolved" clarification, or — if it's a behavior Francis wants discussed for V3 — under "V2 Feature Wishlist," framed as a reminder to redesign from scratch at that API's deep-dive, never as an implementation to adopt.
4. Add anything else that looks like a gap or risk — this plan is explicitly living and incomplete by design.

## Flagged V2 References — retired (fully resolved, see file 5)

*(This section previously tracked unverifiable items. All were resolved once the repo was uploaded — see `v3-plan-04-v2-audit-findings.md`. Nothing left to track here.)*

## Per-API V2 Comparison Checklist

*(Grounded in known `bench.py` module/config names where possible. "V2 equivalent?" means: does V2 have this even as a janky addon, and what can its actual implementation teach V3 before building the "proper" version.)*

1. **OCR API** — RESOLVED into wishlist, see file 04 ("OCR API" entry).
2. **Preprocessing API** — RESOLVED into wishlist, see file 04 ("Preprocessing API" entry).
3. **Inference (LLM) API** — RESOLVED: llama.cpp/ONNX discrepancy explained (see Claude Code Audit Findings). Also RESOLVED: root-caused V2's multithreaded-run stalling to `llm_fixer.LLM_CALL_LOCK` (single loaded model, non-reentrant generation) — fixed in V3 design via async non-blocking `await` on Inference API calls rather than blocking threads (see Decisions Log).
4. **Background Workers API** — RESOLVED: no dedicated module, was ad hoc threading; V2's idle-worker pattern (backfill/auto-fix jobs yielding to active scans) is the one real reusable concept, folded into the Background Workers API's execution classes.
5. **Persistence API** — RESOLVED: `excel_batch_write`/`archive.archive_root` etc. confirmed as the exact area of V2's worst bug; content-addressable blob storage structurally eliminates the underlying failure mode (see Claude Code Audit Findings above). Also surfaced V2's live-formula Transactions-sheet technique and file-open-tolerance requirement, both folded into the Excel export generator design.
6. **Interface API** — RESOLVED into postmortem, see "Interface portability" in the postmortem list above.
7. **Matching API** — RESOLVED: `vendors.py` is a rich existing module (884 lines) — layered builtin/extended vendor maps, Wikidata-seeded bulk names, `garbage_score()` OCR-noise filtering, generic-word stripping, fuzzy lookup with caching. Fully folded into the new Vendor Directory sub-package design (see Core APIs list).
8. **Geo/Address API** — RESOLVED into wishlist, see file 04 ("Geo/Address API" entry).
9. **Reconciliation API** — RESOLVED: V2's second page is a live-formula summary/print sheet pulling from the raw data sheet (see Persistence API's Excel export generator notes). The API itself has since had its full design pass — see `v3-deepdive-17-reconciliation-api.md` (twelve checks designed, complete — ATP validity checking, the last remaining gap, closed out in the same pass that finished this inventory).
10. **Notifications/Inbox API** — RESOLVED: confirmed no V2 notification mechanism existed at all, not even a primitive one — genuinely new territory, designed fresh in `v3-deepdive-09-notifications-inbox-api.md`.
11. **Tool Call API** — RESOLVED: the "AI mode" tie-in surfaced a real correction during Tool Call's own deep-dive — V2's live-user-confirmation pattern doesn't carry forward, since V3 has no AI Mode interactive chat surface and automated processing runs unattended. See `v3-deepdive-07-tool-call-api.md` §4.
12. **Auth & Tenancy API** — RESOLVED: confirmed via Auth's own deep-dive intro — no existing V2 auth code, genuinely new territory. See `v3-deepdive-05-auth-tenancy-api.md`.
13. **Logs API** — RESOLVED: confirmed via full commit history — V2 also had a real "full traceback vs. str(e)" bug, now an explicit requirement (see Core APIs list, formalized further in `v3-deepdive-18-logs-api.md` §3.3).
14. **Audit/Event Log API** — RESOLVED: confirmed genuinely new, no V2 evidence — see `v3-deepdive-08-audit-event-log-api.md`.
15. **Ingestion API** — RESOLVED: V2's Drive ingestion was OAuth + folder-ID polling only, no push notifications (see file 5's Resolved section) — V3's replacement (push-based Webhook Subscription Manager) designed in `v3-deepdive-04-ingestion-api.md` §4.1.3, which also confirms content-hash idempotency makes V2's own `.drive_processed_ids.json` tracking file fully obsolete.
16. **Gateway API** — RESOLVED: confirmed no V2 equivalent (V2 wasn't a web app) — designed fresh in `v3-deepdive-19-gateway-api.md`.
17. **Billing & Subscription API** — RESOLVED: confirmed no V2 equivalent — designed fresh in `v3-deepdive-22-billing-subscription-api.md`.
18. **Health API** — RESOLVED: `health.py` has a real `Watchdog` (liveness-kick, auto-restart-on-silence) and `Heartbeat` class, plus `check_disk_space()` — folded in as Health API's new Watchdog sub-API (see Core APIs list), fully designed in `v3-deepdive-20-health-api.md`, which also now owns the live GPU/resource-reservation ledger the OCR/Inference/Preprocessing deep-dives' shared-substrate discussion resolved to.
19. **Search/Query API** — RESOLVED: confirmed no V2 equivalent (V2 had no query interface beyond opening the Excel file directly) — designed fresh in `v3-deepdive-21-search-query-api.md`.
20. **Migration API** — RESOLVED: V2 had no schema-version field anywhere in `config.py`; its "migration" handling (`migrate.py`, `sheet_migrate.py`) was two one-time, hand-written, user-confirmed scripts, not a general mechanism (see file 5's Resolved section). V3's replacement (a chained N→N+1 registry writing through Persistence's own atomic path) designed in `v3-deepdive-23-migration-api.md`, which deliberately drops V2's manual-confirmation requirement since atomicity/revertability removes the specific risk it was guarding against.
21. **Update/Deployment API** — RESOLVED: no existing update mechanism beyond manual `git pull` + rerunning setup scripts, confirmed. Also surfaced a real stale-`__pycache__`-clearing bug from commit history, folded into the release-dir swap requirements — full design in `v3-deepdive-24-update-deployment-api.md`.
22. **Review/Flagging API** — PARTIALLY RESOLVED: `v3-deepdive-25-review-flagging-api.md` designed the flag lifecycle and taxonomy-consumption boundary, but the specific comparative check this checklist item asks for (confirm the severity-tier/lifecycle model is a genuine improvement over V2's actual flagging code, not missing something the janky version got right) was never actually performed — still a real gap, not resolved.
23. **Setup API** — RESOLVED: `hardware.py` and `hw_import.py` confirmed as the real precedent Setup API's hardware-detection responsibility is built on/against — `v3-deepdive-11-setup-api.md` preserves the specific real V2 gotchas (WMI single-GPU dict-unwrap, AdapterRAM-vs-registry VRAM precedence, external CPU-Z/HWiNFO report import) rather than reinventing them. The `setup.bat`/`setup.sh`/`.ps1` sprawl's own specific bugs are addressed at the architectural level (idempotent re-runnability, no self-move-while-running) rather than a line-by-line comparison against the old scripts.

**New-generation APIs with no V2 lineage** (Content Security, Telemetrees, Persistence's Disaster Recovery sub-API, Account Guardian API) **are exempt from this checklist entirely** — there's nothing in V2 to compare them against.

---
