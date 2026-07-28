# Design Principles

This document is the single compiled reference for every cross-cutting rule and promise this project holds itself to — pulled together from the full V3 planning corpus (the `v3-plan-*` design documents and all `v3-deepdive-*` API documents) into one place for the first time. If a PR conflicts with something here, the PR is wrong until this document is deliberately changed in the same PR with reasoning for the change — this isn't a style guide to skim once, it's the thing CI and review both hold code to.

Each section states the rule, why it exists (not just what it says), and points to where it came from if you want the full reasoning.

---

## 0. The V2 Rule

V2 (the previous generation of this project) is analyzed for exactly one reason: to identify what broke, why, and what V3 must independently design around. **V2 is never a source of code to port, patterns to adopt, data to reuse, or "good practices" to carry forward.** It was deprecated because the combination of everything in it made stable development impossible — that verdict stands, full stop.

Every V3 design decision — down to individual thresholds, recipes, and config values — is derived independently on its own merits, even where a V2 number happens to exist. A handful of V3 decisions do land near a V2 behavior (e.g., Background Workers' idle-time execution class, Setup API's hardware-detection technique) — that's because those specific things were independently re-derived and happened to be sound, not because V2 was trusted. The distinction matters: every deep-dive that kept something V2-adjacent says explicitly *why*, not just *that*.

If you're extending this project and find yourself reaching for V2's implementation "because it's already there," that's the exact failure mode this rule exists to prevent.

---

## 1. Modularity

### 1.1 Package-per-API, not file-per-API
Every core API is its own subpackage/directory (`core/<api>/` or `services/<api>/`), split internally by responsibility — `contracts.py` for types, `service.py` for the thin gRPC implementation, one file per distinct concern (`engine_registry.py`, `corroboration.py`, etc.). Soft target ~300–400 lines per file; a CI check warns past the soft cap and fails past a hard ceiling.

**Why**: long files degrade an LLM-assisted development session's output quality over time — context strain leads to worse edits, which leads to more strain, a real downward spiral for a project whose actual development model leans heavily on Claude Code sessions. A small, stable `contracts.py` lets a session load "what this API promises" without pulling in a huge implementation file it doesn't need for the task at hand.

### 1.2 Provider Registry pattern — multiple simultaneous providers, not single-selection
Any pluggable capability (OCR engines, Preprocessing variant generators, Inference hardware backends, Geo/Address providers, blob backup targets) is implemented as a registry where more than one provider can be enabled and run **in parallel** where corroboration or redundancy adds real value — not a single config value swapped one at a time. New pluggable capabilities default to this shape.

The one exception: a capability that's inherently single-choice at the moment of use (a payment method chosen per-transaction, an SSO provider chosen per-login) — there, "swappable" means "available in the registry, one selected when needed," not "all run in parallel." The distinction is whether running multiple simultaneously produces real value (OCR corroboration does; running two payment methods for one transaction doesn't).

### 1.3 External dependencies are always swappable, never hardcoded — at every granularity
Any integration with an outside service (auth/SSO provider, payment processor, backup/blob storage target) *or* any external library/import (OCR engine bindings, HTTP client, image processing library) sits behind a small internal interface/adapter, with the actual implementation chosen via config or swapped by editing one adapter file — never hardcoded into call sites scattered throughout the codebase.

**Why**: self-hosted installs need to point service-level interfaces at their own choice (their own Drive, their own S3-compatible box, their own payment account); the hosted service has a sane default. This also makes the dependency-update testing loop (Proving Grounds) tractable, since a library bump's blast radius is contained to one adapter file instead of scattered call sites.

### 1.4 No hardcoded TUI
Any screen that's fundamentally "a list of labeled actions" (top-level nav, settings/config, anything with a tooltip and a target API call) is expressed as declarative menu data (label, target API call, tooltip, docs reference) and rendered through one generic `MenuScreen` — never written as a bespoke screen class. The only exceptions are a small, explicitly enumerated set of genuinely stateful/custom screens (run monitor, OCR corroboration diff viewer, vendor/branch editor, staff audit-review queue, the fleet screen, Boot Sequence loading screen, the codename header, the credits screen) — and even those use Textual's widget system directly, never ad hoc print/input-style control flow. Adding a new simple menu item must be possible by editing menu data alone.

### 1.5 Shared substrate without conflating domains
Where two APIs genuinely need the same underlying plumbing (OCR and Inference both consuming ONNX Runtime), the fix is a shared, generic utility layer beneath both — never merging the domains themselves, and never assuming shared runtime implies shared ownership. The concrete precedent: Setup API owns static hardware *detection* (a one-time, rarely-invoked concern); Health API owns the live resource *ledger* (a continuously-queried runtime concern) — split across two APIs specifically because each one's own nature fit a different half of the problem, worked out by actually examining what each API is built for rather than defaulting either "put it all in one place" or "whoever thought of it owns it."

---

### 1.6 Top-level directory discipline: folders for shared/persistent state, a minimal set of files for what the user actually runs
The top-level installation directory (siblings to every release clone — config, default data paths, models, the launcher script, per Setup API's own deep-dive §4) holds exactly two kinds of things: **folders** that hold genuinely shared or persistent state (config, per-user data roots, model weights, backup staging), and the small handful of **files** a user actually needs to interact with to run the program. Anything whose entire job was "get the first clone going" does not belong there once that job is done.

**Why this is a real, consequential rule and not tidiness for its own sake**: a single top-level install can — and, in hosted multi-tenant mode, routinely does — host multiple release-directory clones simultaneously (every channel a user might be on, Update API's own multi-channel design). Anything left lingering at the top level unnecessarily multiplies with every install, not with every clone; it's exactly the wrong place for anything that isn't genuinely shared. The clearest case: the initial `setup.bat`/`setup.sh`/`.ps1` script's entire purpose is making the first clone and handing off to Setup API's own code now living inside that clone — once that handoff happens, the setup script has nothing further to do. Setup API's own finalize routine (running *inside* the first clone, never the setup script trying to clean up after itself, since a script must never attempt to move or delete itself while still running) moves or deletes the now-redundant top-level setup files as one of its own last actions.

**The same discipline extends to development-only content within a clone itself, not just the top level**: see `docs/MAINTENANCE.md`'s Developer Mode section — a normal end-user install strips `CONTRIBUTING.md`, `docs/`, the full test tree, and CI/PR-template scaffolding from each clone once setup completes, since none of it serves any purpose in a running instance and it would otherwise multiply per clone the same way top-level clutter would. A developer-mode install keeps all of it.

---

### 1.7 Process separation via gRPC — the whole point of choosing it, stated as its own principle
**See `docs/PROCESS_TOPOLOGY.md` for the full, precise map of which API runs in which process — this section is the principle, that document is the concrete architecture.** One correction worth stating here directly: there is no single "main process." Every Core API runs as its own independently-launched process, each with its own venv (Update API's own per-service-venv design) — "the core service cluster" is the accurate description, a set of cooperating processes, not one bundled process. Some individual deep-dives in this corpus loosely say "the main process" as shorthand written before the topology document existed; treat that as imprecise phrasing, not a different architecture.

**The core service cluster (every Core API, collectively) runs continuously, and it does not care whether anything is watching it.** Interface (TUI + webapp) and Gateway are **detachable clients** of that cluster, connected only through gRPC — they can be closed, crash, or never be launched for a given install, and the cluster notices nothing and loses nothing. This is not an incidental consequence of using gRPC for IPC; it's the actual reason gRPC was chosen over simpler alternatives, and it directly fixes a real, specific V2 failure: V2's `daemon_loop` literally instantiated the menu system, keyboard listener, and dashboard inside the same loop that ran the processing pipeline — one crash anywhere in that loop took down everything, and the pipeline's own liveness was structurally entangled with the UI's. Process separation via gRPC makes that specific coupling impossible to reintroduce by construction, not by convention.

**Concretely, what this means for any new design or document in this project**: an API's own scope-and-boundary section should never describe its core functioning as depending on whether a *client* (Interface, Gateway, or any future one) is present, connected, or healthy. If a design reads that way, that's this principle being violated, not a stylistic choice — a real instance of this mistake happened during this project's own planning (an earlier pass on Logs/Interface API's own documents blurred exactly this line, corrected once caught, not caught by review the first time).

**Why gRPC specifically, not just "some IPC mechanism"**: typed, versioned `.proto` contracts (Migration API's own field-only-append discipline, `docs/templates/new_grpc_endpoint.md`) rather than an ad hoc wire format; server-streaming, which directly answers V2's own "results only show at the end of a run" bug (Execution Core's live progress, Logs' live tail, Interface's chat surface all lean on this); and a language-agnostic contract boundary, meaning a future non-Python client is a real possibility this architecture already accommodates rather than something that would require a rewrite.

### 1.8 A real feature gets its own sub-API document, never buried as a subsection — a hard rule, stated after it was broken twice
Two real instances happened in this project's own planning before this rule was written down: Task Scheduler (a genuine Protocol with three swappable trigger providers, its own data model, its own TUI screen) got buried as a subsection of Background Workers' own deep-dive, and Groups (a genuine third access-control shape spanning four APIs, its own data model, six gRPC RPCs) got buried as a subsection of Auth's. Both had to be corrected out later. **The concrete threshold, so this stops being a judgment call made under time pressure**: if a feature has *any two* of the following, it gets its own document under `docs/templates/new_sub_api.md`'s process, not a subsection —
1. Its own `Protocol`/interface with more than one concrete implementation.
2. Its own data model requiring genuine storage (not just a config value).
3. Cross-references from more than one other API's own deep-dive.
4. Its own dedicated UI surface (a TUI screen, a settings page) beyond a single menu toggle.

A feature meeting the threshold gets extracted **the same session it's designed**, not noticed later during an audit. This is stated as a hard rule specifically because "it seemed small at the time" is exactly how both prior instances happened — the threshold above exists so the decision doesn't depend on how the moment felt.

### 1.9 Backward-carrying capabilities — anything the main run can do, Reconciliation can do too, against old data
Found during a full pipeline walkthrough, when Geo/Address's own caller was traced and it turned out to genuinely have two, not one: **a per-receipt capability built for the synchronous main pipeline (Execution Core) should be built as a single, reusable function that Reconciliation's own idle-time sweep can call too, against already-written, older receipts** — never duplicated into two separate implementations, one live and one "for old data." The concrete case that surfaced this: Geo/Address does two real things — completing/correcting an incomplete address, and reverse-checking what business is actually at that address to cross-corroborate the vendor match — and both are exactly as useful applied retroactively as applied to a brand-new receipt. When the underlying capability improves (a better geocoding provider, a fixed matching algorithm, a corrected vendor entry in Architect's own directory), that improvement should be able to carry backward and benefit historical data, not just receipts processed from that point forward. Concretely: the capability itself lives in its own owning API (Geo/Address, Matching, wherever it belongs), called from two different orchestrators — Execution Core for new receipts during the live run, Reconciliation for old receipts during an idle-time sweep — never re-implemented separately for the "old data" case. Worth checking for this pattern whenever a new synchronous-pipeline capability is designed: does this also make sense as something Reconciliation could apply retroactively, and if so, is it built so that's actually possible without a second implementation?

---

## 2. Immutability

### 2.1 Frozen contracts everywhere, `FrozenDict` for dict-typed fields
Every request/response/result contract crossing an API boundary is `@dataclass(frozen=True)`. A frozen dataclass with a plain `dict` field is only *shallowly* immutable — the field can't be reassigned, but the dict it points to can still be mutated in place. Any such field uses `FrozenDict` instead (Python 3.15's built-in `frozendict`, PEP 814; a version-gated shim covers earlier Python):
```python
# common/frozen_dict.py
try:
    FrozenDict = frozendict            # Python 3.15+ builtin — no import needed
except NameError:
    from frozendict import frozendict as FrozenDict   # PyPI package, pre-3.15
```
**Real compatibility gotcha**: the builtin `frozendict` is not a `dict` subclass (inherits directly from `object`) — `isinstance(x, dict)` checks silently miss it. Prefer `isinstance(x, collections.abc.Mapping)` in new code.

### 2.1.1 Module-level shared constants are `FrozenDict` too — a real gap between §2.1's letter and this project's own free-threading target
**Found during a co-developer audit sweep, not present in the original principle.** §2.1 above scopes `FrozenDict` to "contracts crossing an API boundary," which left a real category uncovered: module-level lookup tables intended as read-only constants but declared as plain mutable `dict` (`MODEL_PRESETS` in Inference's own `presets.py`, `LEVEL_STYLE_HINT` in Logs' own module, and any future table of the same shape). These pass §2.1 as written, since they aren't contracts — and they're still a genuine problem for two independent reasons:
1. **Immutability in substance, not just at boundaries**: a table every module reads and nothing should ever write is exactly the thing that gets accidentally mutated once, somewhere, and produces a bug nobody can trace back.
2. **Free-threading specifically** (`docs/PRINCIPLES.md` §3.3, and this project's own stated 3.14t target): shared mutable module-level state read concurrently across real OS threads without a GIL serializing access is a genuine race hazard, not a theoretical one. This is the concrete intersection where the immutability principle and the forward-compatibility principle turn out to be the same requirement.

**The rule**: any module-level dict-shaped constant uses `FrozenDict`, the same version-gated shim §2.1 already defines. Mutable module-level `dict` remains correct for genuinely mutable internal registries (a provider registry populated at startup, a per-user semaphore map, a lock table) — those aren't constants and this rule doesn't reach them; the distinction is intent, and it should be visible in the type.

### 2.2 The blob store is purely immutable, content-addressed via a corrected two-layer scheme, zero embedded metadata
Every archived receipt image has a stable **logical identity** (`logical_id` — SHA-256 of the original uploaded bytes, computed before any re-encoding) that every reference in the system uses — SQLite rows, Historian, Audit, exports — and that never changes, ever. This is deliberately *not* the same value as the file's actual on-disk address: this project's real retention policy deletes the original upload a while after scanning, keeping only the re-encoded archival copy long-term, and if the identity hash were also the storage filename, the file on disk would stop matching its own name the moment the original it was hashed from no longer exists anywhere — silently breaking both the basic definition of content-addressable storage and any integrity check that assumes a stored file's hash matches its filename (an earlier version of this design had exactly this bug; caught before it shipped, not after). The fix: a small mapping table connects `logical_id` to `physical_hash` (the hash of whatever is *actually* stored right now, which is always genuinely self-consistent, recomputed whenever the stored representation changes) — one added indexed lookup to resolve a blob, in exchange for the identity layer never needing to change regardless of retention policy, codec changes, or anything else about physical storage. Blobs carry no embedded metadata (a metadata-tagging approach using standard Explorer-recognized fields was seriously scoped, a real fix for the "tagging changes the hash" problem was even designed, and it was still reversed — see `docs/MAINTENANCE.md`'s decision record if you're tempted to revisit this).

### 2.3 Append-only audit tracks — enforced structurally, not just by convention
Historian (data-change trail) and Audit (privileged-action log) are both append-only. This needs to be a structural property of the code's public surface — no `update_event()`/`delete_event()` method exposed anywhere, not a policy someone could bypass with a raw SQL statement if a module happened to expose a connection object carelessly. The reasoning is specific: an audit trail's entire value is being trustworthy evidence in exactly the scenario where someone might want to quietly alter it.

### 2.4 Code repo and per-user data repos are structurally separate
The application source (what deployment updates) and each user's isolated data (Persistence's own per-user database/folder) are different things with different lifecycles, never conflated. Deploying new code never touches a user's data; a user's data operations never touch the code repo. This is also what makes zero-downtime updates possible without any contention between deployment and live data writes.

## 3. Maintainability

### 3.1 File-length and PR-size caps (mechanism in §1.1)
Soft cap ~300–400 lines per file, CI-enforced hard ceiling. **A PR may not exceed 99 commits** — a PR that large is already unreviewable independent of any versioning concern, and it's also what keeps this project's own version scheme's `pp` segment safely at 2 digits.

### 3.2 Testing & bench suite discipline
Test tree mirrors the package-per-API layout (`tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/interface/`, `tests/bench/`). The **interface walker** is auto-generated by iterating the live menu-data structure — it can never go stale, because it reads what the app actually renders from, not a separately-maintained test fixture. The **bench suite** runs the real pipeline, never mocked, with per-test process isolation (a native crash in one engine gets logged as CRASHED, not taken down with the whole run) and a dedicated failure-injection mode that deliberately crashes one engine to confirm the scheduler survives it.

### 3.3 Day-0 dependency support — the Forward-Compatibility Pattern
This program strives for day-0 support of new Python and dependency releases, not lagging adoption. Concretely, a repeating pattern worth using deliberately rather than re-deriving per feature:
1. **Conditional dependency installation via environment markers** — `frozendict; python_version < '3.15'`, resolved automatically at install time. The older dependency isn't just unused on newer Python, it's never installed at all.
2. **Feature-detection over version-checking**, wherever a target API's shape might still be in flux — `hasattr(zipfile.ZipFile, 'remove')`, not `sys.version_info >= (3, 16)`. A still-alpha API can shift shape before its stable release; a hard version check would need updating, a feature-detection check just naturally stops matching and falls through.
3. **One centralized compatibility shim per capability**, not scattered version-conditional logic across call sites. When the minimum-supported version eventually gets raised, only the shim simplifies.
4. **Graceful degradation to the existing safe behavior** when a newer capability isn't available — not a special case, an instance of the general degradation philosophy below.
5. **Lazy imports where a dependency is genuinely optional** (Python 3.15's PEP 810) — a heavy, conditionally-used dependency (OCR's PaddleOCR/RapidOCR bindings, Inference's `onnxruntime-genai`) only pays its import cost when actually invoked, not at process startup regardless of whether that specific capability is even enabled. Feature-detected the same as everything else here: on pre-3.15 Python, imports happen eagerly exactly as they always have — strictly no worse, never a hard requirement.

Every tracked dependency (stable **and** pre-release activity) is monitored continuously by Telemetrees' Dependencies Warden sub-API, not reacted to after the fact. Whether a flagged pre-release feature is worth adopting is a human judgment call; once adopted, the goal is shipping our own stable support for it *before* that dependency's own feature reaches its stable release, not after.

### 3.3.1 Concrete version validation — recommended, not mandatory, for anything this pattern actually touches
**Real Python versions in active use for this project**: 3.14.6 as the primary development target, 3.15 (latest) as a recommended validation target, and 3.16 (built from source, since it isn't stably released yet) as a further recommended validation target for anything genuinely on the leading edge of this pattern. **Recommended, specifically, for**:
- **Any code touching `FrozenDict`** — validate on 3.15/3.16 specifically to confirm it actually resolves to the *built-in* frozen-dict-shaped type on those interpreters rather than silently continuing to import and use the external `frozendict` package. The environment-marker install (§3.3 point 1) handles *not installing* the external package on newer Python — validating on 3.15/3.16 is what confirms the code path *using* it actually takes the built-in branch, not just that the external package didn't get installed.
- **Anything related to free-threading/no-GIL** — the default execution mode shifts across these versions; code with any assumption baked in about GIL-protected access needs real validation on a build where that assumption no longer holds, not just a feature-detection check that compiles.
- **Anything touching `asyncio`'s own changes across these versions**, and **PEP 734 subinterpreters** specifically, given this project's own stated interest in subinterpreters as a future multiprocessing alternative (Preprocessing's own open-questions history) — validating early, even before that adoption decision is made, is what keeps the option genuinely open rather than discovered-broken later.
- This is a **recommendation, not a hard requirement for every PR** — the real requirement is the Forward-Compatibility Pattern itself (§3.3's own five points); validating on 3.15/3.16 is the concrete way to confirm that pattern is actually working as designed for anything in the categories above, not an additional independent rule.

**The concrete mechanism for doing this validation lives in `docs/MAINTENANCE.md`'s Forward-Compatibility Validation section**, the same "PRINCIPLES states the rule, MAINTENANCE states how it actually operates" split §3.3 above already uses for the Forward-Compatibility Pattern itself. In short: `nox -s forward_compat` runs the subset of tests marked `@pytest.mark.forward_compat` against 3.14 and 3.15 automatically; `PYTHON_BIN` lets a developer run the actual program under a chosen interpreter by hand. Not validating every PR does not mean never validating — the real cadence (after each API's own implementation, and as a required gate before `x03.00.00`) is stated there, not here.

### 3.4 Any new typed/learned/schema data goes through Architect API — no exceptions
No API is permitted to define its own ad hoc extensible-typed-thing, spin up its own SQLite table for learned/schema data, or invent a parallel taxonomy, even for a single narrow case. This rule exists because the same pattern was independently reinvented five separate times before Architect API was created to consolidate it — the rule is what prevents a sixth.

---

## 4. Transparency & Safety

### 4.1 Errors are data at API boundaries, not exceptions
A result object with an `.error` field, populated and returned, never raised across a gRPC boundary — a caller checking `result.error` instead of wrapping every call in try/except. The one deliberate, stated exception: Auth & Tenancy's session/role failures, where failing loudly and stopping is correct, since a caller silently ignoring an auth failure is a worse outcome than one accidentally ignoring a business-logic error.

### 4.2 Fail-closed for security-critical checks
Content Security's contract: if the scan call fails, times out, or the service is briefly unavailable, every caller treats the file as unscanned and therefore unsafe — never a silent bypass. This is a contract-level guarantee, not a caller-side convention that could be forgotten by a future integration.

### 4.3 Never silently override — always surface a genuine conflict to a human
Reimport's three-way diff: a field only the user touched applies cleanly; a field only canonical state touched keeps winning (a stale export can't silently revert a newer correction); a field **both** touched, to different values, is a real conflict, surfaced for human resolution, never guessed at by an automatic rule. The same principle shows up in break-glass access (logged and dual-notified, never silent) and Historian's narrative track (recording *why* a scan was processed the way it was, not just the final answer).

### 4.4 Graceful degradation everywhere
OpenCV's UMat falls back to CPU per-op; ONNX Runtime falls back per-node across its execution-provider chain; a missing OCR engine dependency degrades that engine to unavailable rather than crashing the run; a self-hosted install with no Drive configured degrades to direct-upload-only cleanly. This is a standing default posture for any new pluggable capability, not something to design in only when someone asks for it.

### 4.5 Structural isolation over permission checks, where the two options both exist
Per-user data isolation is a folder/database boundary (Persistence's own per-user SQLite database), not just a permission check enforced in application code — meaning a bug in a role-check at the Gateway layer is a real problem but not a catastrophic one for client-role data specifically, since the data is architecturally unreachable regardless. Prefer structural guarantees over check-based ones whenever both are actually available for a given problem.

---

## 5. Concurrency discipline

Three buckets, applied consistently rather than reinvented per API:
- **Async I/O** — network calls, disk waits, waiting on another process. The GIL is irrelevant; `asyncio`/`await` just avoids wasting a thread sitting idle. The dominant bucket for this system.
- **Native/GIL-released** — C/C++ libraries (OCR engines, OpenCV, rapidfuzz, ONNX Runtime) already release the GIL during their actual compute; plain threading already achieves real parallelism here today.
- **No-GIL candidate** — genuine CPU-bound *pure Python* logic with no native library doing the heavy lifting. Free-threading's real value is avoiding multiprocessing's IPC/serialization overhead for work currently forced into separate processes just to dodge the GIL.

Every API's own deep-dive states which bucket(s) it falls into and why — this classification is a design requirement stated up front, not an afterthought discovered during implementation. Where a design choice is reasoned but not yet measured (a scorer default, a threshold, a batching window), it's marked as such explicitly in that API's own open questions rather than presented as a settled fact — **reasoned, then measured** is the standing discipline: architecture and defaults are derived from real engineering reasoning, but treated as provisional until the bench suite actually confirms them.

---

## 6. Where to find the full detail

This document compiles the *rules*. The *reasoning behind each specific instance* of a rule — why OCR's engine roster looks the way it does, why Reimport's conflict resolution works the way it does — lives in each API's own `v3-deepdive-*.md` document. If you're extending an API and a principle here seems to conflict with something reasonable for your change, that's worth raising explicitly in review, not silently working around — either the principle has a real exception worth documenting, or the change needs rethinking.
