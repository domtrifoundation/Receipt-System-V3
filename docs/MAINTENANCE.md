# Maintenance Guide

This document is for maintainers — release process, versioning, channel management, dependency lifecycle, and the decisions worth not re-litigating. If `docs/PRINCIPLES.md` is "what we always do," this is "how the project actually operates day to day."

---

## 1. Versioning scheme

**Program version**: `x<MM>.<mm>.<pp> [code-repo commit hash]`
- `MM` = product generation (V1=01, V2=02, V3=03), each with a codename. The first real V3 stable release is `x03.00.00` — **Zircon** — not restarting the counter at 1.
- `mm` = increments per merged PR.
- `pp` = increments per commit within the current PR, kept at 2 digits (see `docs/PRINCIPLES.md` §3.1's 99-commit PR cap — this is *why* that cap exists, not an independent rule).
- **Pre-release work starts at `x00.00.00` and ticks `x00.00.01`, `x00.00.02`, ... per commit — corrected from an earlier, less precise version of this line that said `x00.01.00`.** Every PR/commit during development gets a real, sequential pre-release tag; `x03.00.00` is a deliberate jump once the program is judged fully feature-complete and validated, not reached by ordinary incrementing — the version number itself marks that this is a genuinely different kind of release, not just the next commit.
- The bracketed commit hash pins the exact build, since `mm.pp` are sequential counters, not content-addressable.

**API version**: `a<MM>.<mm>.<pp>`, same shape, per-API. `MM` reflects real lineage — **verified against the actual V1 and V2 source, not asserted from memory.** V2 lives at `github.com/domtrifoundation/Receipt-System` — also a real, worthwhile reference for what *not* to do (see `v3-plan-04-v2-audit-findings.md` for the specific documented failures); V1 predates that repo and exists as separate source material. For each API, determine its own real starting `MM` from what actually existed in V1/V2 for that function, not from a pre-decided list — an earlier version of this section asserted specific APIs' own lineage tier without that verification having actually happened, which is exactly the kind of unverified claim this project's own discipline argues against elsewhere. Brand-new-to-V3 APIs (no real V1/V2 ancestor) launch at `a01.00.00`. `MM` also increments for any subsequent breaking change to that specific API within V3's own lifetime. **Each API's own `CLAUDE.md` states the real, specific `aXX.XX.XX` that API is actually at once x03.00.00 Zircon ships** — not a placeholder, the genuine value determined by this process.

**Major version codenames**: minerals/gemstones, Z→A (Zircon, Yttrium, Xenotime, Wulfenite, ...). A couple of letters (Q, X) have thin natural coverage and may need a compound name when reached — extend the living list as real major versions actually ship, don't front-load it.

**Codename ASCII art retention**: every codename's art file is kept indefinitely, never pruned — LTSC exists specifically so a channel can stay on an old major version long-term on purpose, and that install still needs its own correct banner. This is a functional requirement flowing from LTSC's purpose, not nostalgia.

---

## 2. Channels

Four channels: **LTSC**, **Stable**, **Beta**, **Alpha** (user-selectable), plus an owner-only **Latest-Commit** channel.

**Version control shape — not four uniform branches.** Stable, Beta, and Alpha are **tags**, not branches — labels on one linear history, promoted forward over time. A branch would imply divergent development needing constant merge/rebase these three don't actually need. **LTSC is the genuine exception and gets a real branch**, since a long-term-support channel needs backported security fixes without dragging in newer feature work — that requires an actual fork point tags can't represent.

**In hosted multi-tenant mode, multiple channels are a standing state, not a transient rollout window.** Since each user picks their own channel, several release directories can be genuinely, simultaneously serving real traffic at once as ongoing normal operation, not just during a brief cutover.

**Release mechanics**: every update is a fresh `git clone` into a new named directory (`<version>_<commit-hash>`) — never a pull, never in-place mutation. Old release directories are garbage-collected past a retention window by a Background Workers idle-time job, always keeping the current release plus at least one prior for rollback safety. Rollout cutover is health-gated: Supervisor launches the new release, waits for Health API to confirm every service's genuine readiness (not just "process exists"), and only then completes the cutover.

**Exception**: the Inference API never multiplies per channel — every user's inference requests route to one shared instance pinned to the system's primary/Stable channel, regardless of which channel their other services run on. (Open question, not yet resolved: how a Beta/Alpha user gets to test a genuinely new Inference API feature before it reaches Stable, given this.)

---

## 3. Dependency lifecycle

The full policy is `docs/PRINCIPLES.md` §3.3 (the Forward-Compatibility Pattern). Operationally:

1. **Dependencies Warden** (Telemetrees' sub-API) polls every tracked dependency continuously — stable releases, pre-releases, and other fact kinds (free-threading support flags, specific upstream issue states, model/preset currency) depending on what that dependency actually needs tracked. A change surfaces into a checked-in changelog summary a Claude Code session picks up automatically, not a dashboard someone has to remember to check.
2. A human decides whether a surfaced change is **program-important** — this is deliberately not automated from a changelog diff.
3. If program-important, **Proving Grounds** (Update API's sub-API) tests the candidate against the real bench workload it actually affects (an OCR engine bump runs OCR's own bench suite, an ONNX Runtime bump runs Inference's) — never a generic smoke test standing in for real exercise of the affected code path.
4. A passing test gates promotion to a channel, through the same Health-API-gated cutover discipline as a code release — a dependency bump doesn't get a looser bar just because it isn't a code change.
5. Findings (failed bump tests, flagged program-important pre-release features) route through Telemetrees into deduplicated, trackable GitHub Issues — the mechanism that turns "we monitor and try" into "and here's confirmation something actually tracks it through to follow-through."

**The tracked-dependency inventory, as of this writing** (extend as new ones get added — this list itself should stay current, not go stale the way the old V2 wishlist file did before its own audit):
- `onnxruntime` / `onnxruntime-genai` — release version + free-threading support (shared between OCR and Inference).
- `opencv-python` — release version + free-threading support + two specific upstream issues (`opencv/opencv#27933`, `opencv-python#1051`, the free-threaded-wheel blocker).
- `pillow-heif`, `pymupdf` — release version + free-threading support.
- `authlib`, `cryptography` — release version + free-threading support.
- `frozendict` (the PyPI package) — compatibility posture against the 3.15 builtin's exact semantics.
- `grpcio` / `grpcio-tools` (shared between every Core API's own gRPC surface, `docs/PRINCIPLES.md` §1.7) — Python 3.15 wheel availability specifically. **Confirmed missing, empirically, not assumed**, while setting up Forward-Compatibility Validation (§8 below): pip falls back to building the full C++ grpc/abseil/protobuf stack from source against a 3.15 beta on Windows, and that build failed here for both `grpcio-tools` and plain `grpcio` alone. Re-check once 3.15 reaches its own stable release, which is typically when grpc's wheel builds catch up.
- RapidOCR's bundled ONNX models — currency relative to PaddleOCR's own newer model generations.
- ClamAV's virus-definition database — freshness, a security-critical dataset check distinct from the `pyclamd` package version.
- The Python interpreter itself — 3.14t/3.15 adoption readiness, tracked like any other dependency, not a one-time migration decision.

---

## 4. Decisions worth not re-litigating

A short list of things that were seriously considered and deliberately reversed or resolved a specific way — if you find yourself wanting to revisit one, read the linked reasoning first, since it's very likely the tradeoff was already weighed.

- **Blob metadata tagging** (Explorer-visible Title/Tags/Comments on archived receipt images) — scoped, a real fix for the hash-changes-when-tagged problem was even designed, reversed anyway in favor of pure immutability + Search/Query-based browsing. See `docs/PRINCIPLES.md` §2.2.
- **Historian as a standalone API with a parallel git-committed event log** — scoped, reversed in favor of a sub-package inside Persistence, once it became clear the parallel git record bought none of git's actual benefits given the live SQLite file was never going to be git-tracked directly anyway.
- **A second OCR backend (docTR) to avoid a PyTorch dependency** — considered (docTR supports a TensorFlow backend as an alternative to PyTorch), dropped entirely anyway rather than taking on a second heavy DL framework just to dodge the first one. PaddleOCR already covers the "heavier, more accurate local engine" role.
- **Cross-user batching of archival image encoding** — provably safe from actual data leakage (still-image intra encoding has no cross-frame state to leak), rejected anyway because a "safe today because we checked the codec" exception to structural per-user isolation is exactly the kind of thing that's easy to accidentally break later.
- **Hardware-accelerated archival re-encoding** (Intel Quick Sync/MFX, NVENC, AMD VCN) — real, checked, understood technology, not adopted: AV1 hardware encode is gated to fairly recent hardware across every vendor, and the integration cost (three separate vendor SDKs, none with Python bindings) stopped being worth it once cross-user batching was also ruled out and the codec settled to one system-wide choice.
- **V2's "propose-then-confirm" pattern for mutating LLM tools** — V3 has no AI Mode interactive chat surface, so there's no live user to confirm with during automated processing. Mutating tools during automated processing self-apply instead, with safety coming from *which* tools are offered (only ones staging into an existing review gate), not a confirmation step that has nothing to confirm with.

---

## 5. Developer Mode

**Setting up this program for real, runnable development requires downloading the installer — not cloning the repository directly.** Cloning the source repo gets you the code; it doesn't get you a working top-level directory structure, config, first-run wizard, hardware detection, or a Persistence database to actually run against. The installer exists precisely to build all of that correctly, once, the same way for every install. If you `git clone` this repo directly and try to run it, it won't work — that's expected, not a bug.

### Setting up a development environment, step by step
1. Go to this repository's GitHub Releases page and download the release archive for your OS.
2. Extract it. Inside, you'll find two setup scripts: `setup.bat`/`setup.sh` (normal) and `setup-dev.bat`/`setup-dev.sh` (developer mode).
3. **Run the developer-mode script**, not the normal one — this is the one part of the process a contributor needs to do differently from an end user. Running the normal installer for development work will leave you without the `docs/` folder, the test tree, and the CI/PR scaffolding once first-run completes (Setup API's own deep-dive §4.1) — genuinely correct behavior for an end-user install, actively unhelpful for development.
4. The script performs the first real `git clone` of this repository into a named release directory, then hands off to the program's own first-run setup — hardware detection, initial config, and (if you're setting up multi-tenant mode) the first owner account.
5. Once setup completes, the top-level directory contains: the release clone(s) (siblings, never nested), shared config, model weights, and the launcher script. The original setup scripts are gone from the top level by this point — moved/deleted as one of setup's own last actions, not left cluttering a directory that can end up hosting several release clones at once (see `docs/PRINCIPLES.md` §1.6 for why this matters).
6. From here, work inside the release clone like any normal repository — it's a real git working directory with full history, not a stripped export.

**Multiple clones under one top-level install**: if you need a second, independent clone for testing a different branch/channel side by side, re-run a developer-mode setup pointed at the same top-level directory rather than cloning manually — this keeps the shared config/data-path conventions (`docs/PRINCIPLES.md` §1.6) intact rather than accidentally producing a clone that doesn't know where the shared top-level assets live.

### Switching a normal install to developer mode later
Not currently supported as a live conversion — `dev_mode` is set once at first install and read by every subsequent Update API clone (Setup deep-dive §4.1). Converting an existing normal install to developer mode means a fresh developer-mode setup run, not a config flag flip on a live instance.

---

## 6. Documentation maintenance

- `docs/PRINCIPLES.md` gets updated in the *same PR* as any change that affects a cross-cutting rule, not as a follow-up.
- Each API's own `v3-deepdive-*.md` document is the authoritative implementation-level detail for that API — when code and its deep-dive document disagree, that's a bug in one of them, not a case where the code is silently assumed correct.
- Open questions logged in a deep-dive document should be resolved (and the document updated) as part of whatever PR actually resolves them — don't let a document's own "open questions" section silently go stale the way the pre-audit version of this project's V2 wishlist file did.

## 7. Making the checklists actually enforced, not just advisory — a real GitHub repo-settings action, not a file

**A real limitation worth being explicit about**: a checkbox in a PR description is purely cosmetic to GitHub itself — nothing native stops someone from submitting a PR with every box unchecked, or checking every box without doing the underlying work. `.github/workflows/pr_checklist_enforcement.yml` closes half of that gap (it parses the PR body and fails CI if a box is left unchecked, or if the two highest-stakes items — Forward-Compatibility Hygiene, Backward-Carrying Capability — are checked with no real justification text behind them). **The other half is a repository setting, not something committed to the repo at all**, and it needs to actually be turned on for any of this to be hard-enforced rather than advisory:

1. Repo Settings → Branches → Branch protection rules → add a rule for `main` (or whichever branch is the real integration target).
2. Enable **"Require status checks to pass before merging."**
3. Add `Verify PR checklist is genuinely complete` as a required check. **This is the `jobs.verify-checklist.name` value inside `pr_checklist_enforcement.yml`, not the workflow's own `name:` (`PR Checklist Enforcement`)** — an earlier version of this line named the workflow instead, which is a real trap rather than a cosmetic slip: GitHub matches required status checks against the *job* name, so requiring the workflow name creates a check context that never reports and therefore blocks every PR permanently. Corrected in Phase 1 after checking the workflow file rather than trusting this line.
4. Enable **"Require branches to be up to date before merging"** so a required check can't pass against a stale base commit.
5. **Leave "Include administrators" checked, deliberately** — an admin bypassing their own project's own hygiene rules "just this once" is exactly how the recurring V2-era mistakes this project keeps correcting actually happened; the rule protects the person tempted to skip it as much as anyone else.

### 7.1 Adding the other eight `check_*.yml` workflows as required checks — read this before doing it
An earlier version of step 3 above said to add "the relevant per-category checks from the other eight `check_*.yml` workflows too" once real application code exists. That advice is right in spirit and **actively dangerous applied literally**, for a reason found in Phase 1 by reading the workflow files rather than trusting the sentence:

**Six of the eight are path-scoped**, and a path-scoped workflow that doesn't trigger never reports a status at all — GitHub treats a required check that never reports as *pending forever*, so any PR not touching those paths becomes permanently unmergeable. This is the same class of mistake as naming the workflow instead of the job in step 3, and it fails in the same silent, confusing way.

- **Safe to require today, unscoped, they run on every PR**: `check_menu_data_integrity.yml` (deliberately unscoped — a gRPC rename anywhere can silently break a menu entry), `check_no_shadow_taxonomy.yml`, `check_stripped_content_completeness.yml`.
- **Not safe to require as currently written**: `check_new_core_api.yml`, `check_new_sub_api.yml`, `check_new_provider.yml`, `check_new_dependency.yml`, `check_config_schema.yml`, `check_grpc_compatibility.yml`. To make any of these required, first restructure it to run unconditionally and decide internally whether it has anything to inspect — the same "always report, skip internally" shape the three above already have — rather than gating at the `on.pull_request.paths` level.

**Separately, all eight currently no-op with a `::warning::`** because their `tests/ci/test_*.py` files don't exist yet. A required check that passes vacuously is worse than an absent one: it reads as enforcement on the branch-protection screen while verifying nothing. Add each one only once its own `tests/ci` test genuinely exists *and* its trigger has been unscoped.

### 7.2 "Require deployments to succeed" — a rulesets-only rule, and a genuine later step
Repository **rulesets** (not classic branch protection) offer a `required_deployments` rule — "choose which environments must be successfully deployed to before refs can be pushed." It is worth having eventually and cannot be set up yet, for two independent reasons:

1. **It requires GitHub Environments to exist, and none do** (`gh api repos/{owner}/{repo}/environments` returns `total_count: 0` as of Phase 1). The rule names environments; with none defined there is nothing to require.
2. **This project's actual deployment mechanism is not GitHub Deployments.** A release here is a fresh `git clone` into a named release directory, health-gated by Supervisor against Health API before cutover (§2 above, `v3-deepdive-38-supervisor.md` §3.2). Wiring GitHub Environments in means deliberately deciding how that internal mechanism reports into GitHub's own deployment API — a real design step, not a checkbox.

Note also that the enforcement currently live on `main` is **classic branch protection**, which has no equivalent of this rule. Adopting `required_deployments` means moving to a ruleset (the two can coexist, with the most restrictive winning, but running both indefinitely is a needless second source of truth). Sequence it as: real application code and CI tests → §7.1's unscoping work → define environments and decide how Supervisor's health-gated cutover reports into them → then move enforcement to a ruleset and add this rule.

**Scriptable equivalent, if you'd rather hand this to Claude Code than click through the UI** — `gh` (the GitHub CLI) can configure this directly via the API:
```bash
gh api --method PUT repos/{owner}/{repo}/branches/main/protection \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=Verify PR checklist is genuinely complete" \
  -F "enforce_admins=true" \
  -F "required_pull_request_reviews=null" \
  -F "restrictions=null"
```
**Two real conditions for this to actually work, not guarantees**: whatever token `gh` is authenticated with needs *admin* rights on the repo specifically — push access alone isn't enough, branch protection is an admin-only endpoint. And this is exactly the kind of consequential, security-relevant change worth a deliberate one-time confirmation before it runs, whether that confirmation comes from a human reviewing the command or from Claude Code's own permission prompt for `Bash(gh *)` — not something to pre-approve blindly into an always-allow list alongside routine read-only commands.

**If you maintain two `gh` accounts (an owner/admin account and a non-admin collaborator account) — don't rely on the interactive account picker for this command.** `GH_TOKEN` overrides the active account entirely, and `gh auth token --user <name>` fetches a specific stored account's token non-interactively — combined, this sidesteps the picker prompt completely rather than needing anything to detect or click it:
```bash
GH_TOKEN=$(gh auth token --user your-owner-username) gh api --method PUT repos/{owner}/{repo}/branches/main/protection \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=Verify PR checklist is genuinely complete" \
  -F "enforce_admins=true" \
  -F "required_pull_request_reviews=null" \
  -F "restrictions=null"
```
This is the right general pattern for any admin-gated command run non-interactively — set `GH_TOKEN` explicitly for that one command rather than depending on whichever account happened to be active.

**Copilot custom instructions — set up, but not relied on as real enforcement.** `.github/instructions/*.instructions.md` files with an `applyTo` path-glob frontmatter block are a real, GitHub-documented mechanism for scoping Copilot's automated PR review to specific parts of the repo — four are already written in this repo (`core-apis.instructions.md`, `providers.instructions.md`, `dependencies.instructions.md`, `grpc.instructions.md`), matching the highest-stakes PR template categories. **A genuine, current caveat worth stating plainly rather than glossed over**: multiple community reports (as recent as February 2026) describe Copilot's automated PR-review agent sometimes ignoring custom instructions entirely and falling back to generic review output, apparently because the automated reviewer runs on a different execution path than the interactive Copilot Chat surface, which does reliably read them. Set these files up since they're low-cost and the mechanism is real — but the actual hard enforcement in this project stays with `pr_checklist_enforcement.yml` and branch protection, since that path is deterministic (it parses text, it doesn't depend on an LLM reliably choosing to apply a file it was given). Treat Copilot's own review as a helpful second opinion, not a control this project's own hygiene depends on.

**This is a real, one-time setup action someone needs to actually perform** — writing this section down doesn't turn the setting on by itself, the same way writing a `docs_ref` citation doesn't substitute for a lawyer reviewing the actual Terms of Service text (`v3-deepdive-06-account-guardian-api.md` §7). Worth doing before the first real PR lands, not after — a rule added retroactively doesn't apply to anything already merged under the honor system.

## 8. Forward-Compatibility Validation — the concrete mechanism, not just the policy

`docs/PRINCIPLES.md` §3.3.1 states *what* needs periodic validation across this project's supported Python versions (anything touching `FrozenDict`'s actual resolved type, any GIL-protected assumption, any `asyncio` behavior that differs across versions, PEP 734 subinterpreters) and *why*. This section is the operational mechanism that actually does it — the same "PRINCIPLES states the rule, MAINTENANCE states how it operates day to day" split already used for the Forward-Compatibility Pattern itself (§3 above).

**Two separate mechanisms, for two separate needs — don't conflate them:**

### 8.1 Automated test validation — `nox -s forward_compat`
`noxfile.py` at the repo root runs the subset of tests marked `@pytest.mark.forward_compat` (registered in `pytest.ini`) against both 3.14 and 3.15, each in its own isolated venv:

```bash
nox -s forward_compat        # both interpreters
nox -s forward_compat-3.15   # just the newer one
nox -s forward_compat_316    # manual, once a 3.16 build exists locally — genuinely optional
```

nox rather than tox, specifically for Python-native session config — this matters once sessions are filtering to a specific marked subset rather than just running everything. It requires both interpreters to actually be installed and discoverable; if 3.15 isn't there, the session fails loudly rather than silently skipping, since a missing interpreter is a real environment gap to fix, not something to route around. On Windows, nox finds `3.14`/`3.15` through the `py` launcher automatically — no `python3.14`-style PATH entry is needed the way Linux/macOS or a pyenv install would produce.

**Tag a test `@pytest.mark.forward_compat` going forward whenever it specifically validates FrozenDict/free-threading/asyncio-version-sensitive behavior** — not retroactively across the whole suite, and not on a test that merely happens to import a module that also touches those things. `tests/unit/test_forward_compat_frozen_dict.py` is the first real example: it empirically confirms `common.frozen_dict.FrozenDict` resolves to the actual Python 3.15+ builtin (`type(FrozenDict).__module__ == "builtins"`) rather than silently still using the external PyPI package once a newer interpreter makes the marker-scoped install a no-op — precisely the §3.3.1 gap stated above, made concrete and checked rather than assumed.

**Why this session installs a narrow, explicit dependency list (`pytest`, `frozendict`) rather than the project's full `requirements.txt`, confirmed empirically rather than assumed while setting this up**: `grpcio` and `grpcio-tools` have no prebuilt wheel yet for CPython 3.15 — pip falls back to compiling the entire C++ grpc/abseil/protobuf stack from source, and on this project's own dev machine that build genuinely failed against a 3.15 beta (confirmed for both `grpcio-tools` and plain `grpcio` alone, not just the codegen tool). That's a real, current Day-0 gap in an upstream dependency — added to the tracked-dependency inventory in §3 above — not a reason to make the fast, frequent-cadence compat check depend on it. None of the tests currently marked `forward_compat` import `grpc` at all. If a future `forward_compat`-marked test genuinely needs a package `requirements.txt` also carries, add that package to `noxfile.py`'s own dependency list explicitly — don't switch the session over to installing `requirements.txt` wholesale, which would reintroduce exactly this coupling.

### 8.2 Manual runtime selection — `PYTHON_BIN`
For actually running the program itself under a chosen interpreter, by hand — a genuinely different need from §8.1's automated test subset. `start.bat`/`start.sh` both respect a `PYTHON_BIN` environment-variable override:

```bash
./start.sh                          # default pinned interpreter (currently 3.14)
PYTHON_BIN=python3.15 ./start.sh    # the whole system running under 3.15
```

Unset, always, on a real end-user install — those get their interpreter from Setup API's own environment detection and never touch this variable. It exists for a dev checkout, to hands-on test against a non-default interpreter ahead of (or alongside) a `forward_compat` review. **On Windows, there is usually no bare `python3.15` command even when 3.15 is genuinely installed** — the `py` launcher resolves a specific version there instead, so the override is passed as one quoted variable: `PYTHON_BIN="py -3.15" ./start.sh`.

Verified for real, both directions, not just written and assumed: with `PYTHON_BIN` unset and `python` on `PATH` resolving to the pinned 3.14, `start.sh` launches Agent Control's own gRPC service (`core/agent_control/service.py` — the one real, running Core API as of Phase 1; every other API's launcher target is still scaffolding, and this script's `exec` line is expected to be replaced with a real Supervisor invocation once Supervisor itself is real code) and the running process's own `sys.executable`/`sys.version` — printed at startup specifically so this is checkable from outside the process rather than trusted on faith — confirmed `Python314\python.exe`, `3.14.6`. With `PYTHON_BIN="py -3.15"`, the exact same `exec $PYTHON_BIN` expansion was independently confirmed to resolve to `Python315\python.exe`, `3.15.0b4` — the override genuinely switches interpreters. That second run then hit the same missing-`grpc`-on-3.15 gap §8.1 already documents, which is an environment fact about an upstream dependency, not a defect in the `PYTHON_BIN` mechanism itself.

### 8.3 The real cadence — not a one-time setup
Run `nox -s forward_compat` after finishing each API's own implementation — a natural per-API checkpoint — and again as a required gate before tagging `x03.00.00`. **This is not optional once set up.** Treat a skipped validation checkpoint the same as a skipped version-tick on a commit (§1 above) — an incomplete unit of work, not a minor omission. This doesn't mean every PR needs a nox run (§3.3.1's own "recommendation, not a hard requirement for every PR" still holds) — it means the checkpoints above are non-negotiable when they come due, the same way a version tick isn't optional on the commit that triggers it.
