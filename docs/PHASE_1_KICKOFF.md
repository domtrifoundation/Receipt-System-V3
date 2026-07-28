# Phase 1 Kickoff — Local Claude Code Session

Hand this document directly to the local Claude Code session as its starting instructions. This is Phase 1 of a two-phase plan: repo hygiene, documentation setup, file/folder structure, every `CLAUDE.md`, and — a real, deliberate exception — a working implementation of the Agent Control API specifically (§1.5 below), so its MCP and headless capabilities are genuinely available to Claude Code from the start of Phase 2, not built partway through it. **Both phases run locally for now** — Phase 2 also runs locally, specifically because running the real OCR engines (and other locally-hardware-dependent work, §1.5's own note on this) isn't something a remote session can do properly. The plan is to move to remote sessions for ongoing work once x03.00.00 ships; this document doesn't need to account for that transition, `PHASE_2_KICKOFF.md` does.

---

## 0. Before anything else — the `gh` account requirement

**Every `gh` command in this session must run as the `domtrifoundation` account specifically, not whichever account happens to be locally active.** Per `docs/MAINTENANCE.md` §7, use `GH_TOKEN` explicitly for every `gh` invocation rather than relying on the ambient active account:

```bash
GH_TOKEN=$(gh auth token --user domtrifoundation) gh <command>
```

If this is the first `gh` command run in this session, confirm the `domtrifoundation` account is actually authenticated locally (`gh auth status`) before proceeding — if it isn't, stop and ask the human operator to run `gh auth login` for that account first, rather than proceeding under the wrong identity.

---

## 0.5 Before anything else, part two — confirm the local dev environment is actually ready
**A real gap found while assembling this document: nowhere else states what "a working local environment" concretely requires.** Confirm, don't assume:
- **Python 3.14.6** as the primary development interpreter — confirmed the free-threaded build, not a standard build that happens to report a matching version number.
- **Python 3.15 (latest) available as a second interpreter**, and **Python 3.16 (built from source, since it isn't stably released yet)** available as a third — both are **recommended, not mandatory**, validation targets specifically for anything the Forward-Compatibility Pattern actually touches (`docs/PRINCIPLES.md` §3.3.1 has the concrete list: `FrozenDict` code confirming it takes the built-in-type branch rather than silently still using the external package, free-threading/no-GIL assumptions, `asyncio` changes across these versions, and PEP 734 subinterpreters). Set these up now if they aren't already available — a multi-interpreter setup (`pyenv`, or several parallel installs) is the practical way to have all three on hand without constant reinstalling.
- **`pip install` needs `--break-system-packages`** on this project's own established convention — don't fight this with a venv workaround unless a venv is what's actually wanted; check `docs/MAINTENANCE.md` for the current stated approach before assuming either way.
- **A local SQLite-capable environment** — no separate database server to stand up, but confirm `sqlite3` and Python's own `sqlite3` module are both genuinely available.
- If any of this isn't already true on the machine this session is running on, set it up now, before task 1.1 below — don't discover a missing dependency three tasks in.

---

## 1. Task order for this session

Do these in order. Each one is a real prerequisite for the next — don't reorder them for convenience.

### 1.1 Repo hygiene
- Confirm `.github/workflows/`, `.github/scripts/`, `.github/instructions/`, `.github/PULL_REQUEST_TEMPLATE/`, and `docs/templates/` all exist and match what's described in `docs/MAINTENANCE.md` §7 and the deep-dive corpus.
- **Set up branch protection now, while `gh` access is available** — this is genuinely a this-session task; Phase 2 also has local `gh` access, but there's no reason to defer something this cheap and this consequential when it can be done now. Follow `docs/MAINTENANCE.md` §7's own scriptable `gh api` command, using the `GH_TOKEN` pattern from §0 above for the `domtrifoundation` account specifically, since branch protection is an admin-gated action.
- Verify `.github/scripts/check_pr_checklist.py` and `.github/scripts/check_stripped_content_list.py` are both present and pass a local syntax check before relying on them.

### 1.2 Documentation setup
- Confirm every file listed in `docs/index.md` actually exists at the path it claims.
- This is also the point to act on `docs/WIKI_MIGRATION_PLAN.md` §4 if the GitHub Wiki is being set up as part of this session — move `docs/SELF_HOSTED_NOMINATIM.md`, leave the stub redirect described there.
- Confirm `docs/LEGAL_REVIEW_NEEDED.md`'s own placement question (that document's own §3, referenced from `WIKI_MIGRATION_PLAN.md` §3) has been resolved by the human operator before this session finishes — if it hasn't, flag it explicitly rather than silently leaving a sensitive document in a public location.

### 1.3 File paths and folder structure
- Create the real top-level directory structure per `v3-deepdive-11-setup-api.md` §4's own "top-level directory discipline" (`docs/PRINCIPLES.md` §1.6) — `core/`, `services/`, `webapp/`, `config/`, `data/`, `models/`, and the top-level launcher files, as siblings, never nested inside a release-clone-specific structure at this stage.
- Create each Core API's own package folder per that API's own deep-dive "Package layout" section — an empty, correctly-named folder structure with `__init__.py` placeholders is the right amount of scaffolding for this session; **do not write real implementation code in this session**, that's explicitly Phase 2's job.
- Cross-check the folder structure against `docs/PROCESS_TOPOLOGY.md` to confirm it matches the actual process map, not just a plausible-looking guess.

### 1.4 Every `CLAUDE.md`
- Follow `docs/CLAUDE_MD_GUIDE.md` precisely — this is the point of that document existing.
- One at repo root.
- One in each Core API's own top-level folder (all 32, per `v3-plan-01-core-apis.md`'s own numbered list).
- One in each sub-API's own folder, where a sub-API has a real, separate directory (Groups, Task Scheduler, temporal_learning, Tunnel Exposure, and the rest — cross-check `v3-plan-01-core-apis.md` and each Core API's own deep-dive for which sub-APIs actually warrant their own folder versus living as a module inside the parent).
- **Every `CLAUDE.md`'s own "full design" pointer must reference a real, existing deep-dive file** — verify this the same way the corpus's own final verification pass did (`v3-plan-03-decisions.md`'s own "FINAL VERIFICATION PASS" entry), not just written and assumed correct.

### 1.5 Implement the Agent Control API — the one real exception to "no application code" in this session
**A deliberate exception, not scope creep**: `v3-deepdive-55-agent-control-api.md` gets a genuine, working implementation in this session — not just the folder scaffolding every other Core API gets — so its MCP server and headless CLI are actually usable from the moment Phase 2 starts, rather than something Phase 2 has to build for itself partway through before it can even use it. Follow that deep-dive directly: agent tokens, the MCP tool set (§4 there — `persistence_query`, `find_setting`, `propose_setting_change`, the real ones, not invented names), the headless CLI, and the rate-limit/audit wiring. **This session's own real completion criterion for this specific piece**: issue a real agent token, confirm an MCP client can actually call `find_setting` and get a real result back, and confirm a revoked token's next call actually fails — not just written code, an actually-working round trip.

---

## 2. What this session should NOT do

- Write real application/business logic for anything other than the Agent Control API exception in §1.5 above.
- Make product or architecture decisions not already resolved in the deep-dive corpus. If something genuinely looks unresolved or contradictory while doing this scaffolding work, stop and flag it rather than guessing — the same discipline the planning phase itself followed throughout.
- Skip the branch protection step because it feels like it could wait. It's genuinely easier to do now, while a session with real admin `gh` access already exists, than to schedule a second local session later just for this.

---

## 3. Handoff to Phase 2

When this session's work is done, it should leave a real, written summary (not just a final chat message) — a `PHASE_1_COMPLETE.md` or equivalent, listing: what was created, what was flagged/skipped and why, and explicit confirmation that (a) branch protection is live, and (b) the Agent Control API round trip described in §1.5 above actually worked. Phase 2's own session (`docs/PHASE_2_KICKOFF.md`) should read that summary before starting, the same way this session read the planning corpus before starting.
