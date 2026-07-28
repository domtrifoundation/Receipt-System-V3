# V3 Deep Dive: Setup API

**Companion files:** all prior deep-dives — this one resolves the shared-hardware-substrate question the OCR (§5.6), Inference (§8.6), and Preprocessing (§6.7) deep-dives each proposed and flagged as needing Setup API's own session to confirm.

**Status:** Eleventh deep-dive session, prioritized per request alongside Execution Core. Real V2 lineage (`hardware.py`, `hw_import.py`, `setup.bat`/`setup.sh`) — genuinely good, working hardware-detection technique worth understanding in full before re-deriving fresh, per this project's usual discipline.

---

## 1. Scope & boundary

Setup API owns: the one-time distribution/bootstrap handoff, hardware/environment detection (**the static profile** — see §5 for the important distinction from live resource tracking), dependency installation, and the first-run config wizard. It does not:
- **own dependency *download infrastructure*** — that's shared with Update API's Proving Grounds sub-API (file 01 #21's note), Setup just calls into it for the initial install.
- **own live resource/VRAM commitment tracking** — resolved here, differently than the other three deep-dives tentatively proposed: see §6.
- **own Keymaster's licensing logic** — Update API's territory; Setup's wizard is only where a license key gets *entered*, not where it's validated or enforced.
- **run on every launch** — that's the Startup Sequence (file 02, a designed flow, not its own API). Setup runs once (or whenever explicitly re-invoked); Startup Sequence runs every time the program starts.

---

## 2. Package layout

```
services/setup/
  __init__.py
  contracts.py             # HardwareProfile, GpuInfo, WizardState, error types
  bootstrap.py                # ZIP → clone → handoff, see §4
  dev_mode_strip.py             # strip_development_content() — shared with Update API's release_manager.py, see §4.1
  dev_fixtures.py                # setup-dev's own default-environment seeding — sample data, stub configs, mock providers, see §4.1
  hardware/
    __init__.py
    detect.py                  # platform-dispatch probing, see §5.1-5.2
    report_import.py             # CPU-Z/HWiNFO external report fallback, see §5.3
    scoring.py                    # recommended_settings() tier calibration, see §5.4
  wizard.py                   # first-run config flow, see §7
  errors.py
  metrics.py
```

---

## 3. Data contracts (`contracts.py`)

```python
@dataclass(frozen=True)
class GpuInfo:
    name: str
    vendor: str              # "intel" | "nvidia" | "amd" | "unknown"
    discrete: bool
    vram_gb: float | None
    compute_api: str            # "cuda" | "sycl" | "directml" | "rocm" | "unknown" — see §5.2's classification note

@dataclass(frozen=True)
class HardwareProfile:
    cpu_name: str
    cores: int
    threads: int
    ram_gb: int | None
    gpus: tuple[GpuInfo, ...]
    npus: tuple[str, ...]
    detected_at: datetime
    source: str                 # "os_probe" | "os_probe+external_report" — see §5.3

@dataclass(frozen=True)
class WizardState:
    tenancy_mode: str            # "single" | "multi"
    owner_created: bool
    initial_tier: str
    drive_restore_offered: bool
    completed_at: datetime | None
```

---

## 4. Distribution model and bootstrap — already well-specified in file 01, restated with the "why" attached
A GitHub Release per OS ships a thin ZIP containing only the setup script(s) — not a source snapshot. The setup script performs the *first* real `git clone` into a named release directory, then hands off to Setup API's own code now present inside that clone. **The top-level directory structure (config, default data paths, models, the `start.bat`/`start.sh` launcher) is built as siblings to every release directory, never nested inside one** — this is what makes user data and shared assets architecturally unreachable by any future update/clone operation, the same placement principle Auth & Tenancy's and Audit's own databases already followed in their own deep-dives (§5.2 and §3.1 respectively) — Setup API is actually the *origin* of that placement convention, now stated as its own explicit rule in `docs/PRINCIPLES.md` §1.6.

**A real consequence of the Keymaster license-key timing (§4.1): the setup script itself has to carry a small amount of real logic before any Python code exists on disk at all.** Prompting for a key and calling Keymaster's own API to obtain a scoped clone token happens *before* the first `git clone` — meaning before Setup API's own package (which only exists inside the clone) is reachable at all. This is necessarily a minimal, self-contained piece of the bootstrap script itself (a `curl`/`Invoke-RestMethod` call and a bit of shell logic, not a dependency on anything this project's own codebase provides), the one deliberate exception to "the ZIP contains only the setup script, no real logic" — small and unavoidable, worth naming explicitly rather than glossing over as if the bootstrap script were purely mechanical.

**Idempotent, safely re-runnable by design — this is the actual fix for V2's helper-script sprawl, not a nicer wrapper around the same fragility.** V2's `setup.bat` checked for an existing config file and skipped the wizard if found, but the underlying script sprawl (a separate `.ps1` for the interactive wizard, another for credential fetching, fragile self-referential batch-file logic) was the real problem. **A self-referential script must never try to move/delete itself while running** — fragile everywhere, especially on Windows with locked executing files — so the setup script's *last* action is handing off to Setup API's own Python-level finalize routine for any remaining file operations, never a batch/shell self-move trick.

**Setup files are cleaned out of the top level once their job is done, not left there permanently.** `docs/PRINCIPLES.md` §1.6 states this as a general top-level-hygiene rule; concretely here, that means: once the first clone exists and Setup API's own finalize routine has run *inside* it, that routine's last action is moving or deleting the now-redundant top-level `setup.bat`/`setup.sh`/`setup-dev.bat`/`setup-dev.sh`/`.ps1` files — never leaving them sitting at the top level indefinitely. This matters concretely (not just tidiness) because a single top-level install routinely hosts several release-directory clones at once (every channel a user's on) — anything left at the top level is shared clutter multiplying with every *install*, a different and worse problem than clutter multiplying with every *clone*.

### 4.1 Two installer entry points in one archive: normal and developer mode
The downloaded release ZIP for a given OS contains **two** setup entry points, not one: `setup.bat`/`setup.sh` (normal) and `setup-dev.bat`/`setup-dev.sh` (developer mode) — deliberately packaged together in the same archive rather than published as two separate GitHub release assets, so the release surface doesn't double for a distinction most users will never need to think about. A user (or a contributor setting up for development) picks which script to run.

**Safeguard against running the wrong one by accident, decided during the Setup Sequence walkthrough: a visible confirmation prompt lives specifically inside `setup-dev`, not `setup`.** The asymmetry is deliberate, not an oversight — `setup-dev` is the one with real, unusual consequences (pulling in the full docs/test corpus, keeping CI scaffolding, a meaningfully larger and differently-shaped install than what an ordinary user expects), so it's the one that needs to double-check intent; the plain `setup` script stays a single confirm-free run, since running it by mistake instead of `setup-dev` has no bad consequence beyond needing to redo setup properly. Concretely, `setup-dev`'s very first action, before touching disk at all, is printing something like *"This installs the full development environment — documentation, test suite, and CI scaffolding. If you just want to run the program, close this and run `setup` instead. Continue? [y/N]"* — defaulting to No, requiring explicit confirmation to proceed.

**Keymaster license timing, resolved: the ZIP itself is freely downloadable (public GitHub Release, no gate) — it contains only the bootstrap setup script, zero proprietary code, so there's nothing in it worth gating. The setup script itself is the first thing that asks for a license key, immediately before attempting the first clone** — that clone is the actual point where private-repo access is genuinely needed, so that's where the gate belongs, not one step earlier at the download page (which would mean building and maintaining a second, separate auth system just for serving a small bootstrap file). Concretely: `setup`/`setup-dev` prompts for a license key, calls out to Keymaster for a short-lived scoped GitHub token, and only proceeds to `git clone` once that token is issued — a self-hosted install with an invalid or missing key simply can't get past this one step, cleanly, before anything else has happened. (Not relevant to the hosted multi-tenant service at all — DOMTRI's own hosted instances aren't customer-licensed self-hosted clones, so this entire step doesn't apply there.)

**What "developer mode" changes goes beyond stripping docs — it also changes the setup *experience* itself, not just its file contents.** Two genuinely different install philosophies, not one installer with a content toggle:
- **Normal (`dev_mode: false`) is the immersive, user-friendly experience** — the full interactive first-run wizard (§7 below), real prompts, live hardware-detection results shown clearly, the version-codename splash, genuinely designed for someone who's never touched this system before and shouldn't need to know anything about its internals to get through it.
- **Developer mode (`dev_mode: true`) is deliberately bare-bones — minimal to no interactive prompts, everything defaulted, optimized for "get to a working local dev environment as fast as possible," not for a good first impression.** Concretely: `tenancy_mode` defaults to `single` without asking (a solo contributor testing locally has no reason to stand up OIDC/multi-tenant just to run the code); the owner account is created trivially and silently, the same implicit-owner path single-tenant mode already uses (Auth's own deep-dive §6.2); no Drive config-restore offer (nothing to restore for a fresh dev checkout). **Additionally, and this is new: `setup-dev` pulls in a set of development fixtures and defaults that a contributor would otherwise have to assemble by hand** — a pre-populated `.env`/config with sensible local-dev values already filled in (not real credentials, but structurally complete so nothing crashes on a missing key), sample/fixture receipt images and a small seeded SQLite dataset for immediately exercising OCR/Matching/Reconciliation without needing real customer data, and stub/mock provider configurations (e.g. a fake Geo/Address provider that returns canned responses) so a contributor working on, say, Reconciliation's own logic isn't blocked on configuring three unrelated cloud API keys first. This is genuinely new scope for `setup-dev` beyond content-stripping, worth its own tracked file manifest the same way `strip_development_content()` has one (§9's own open question about keeping that list current applies equally here).

**Content stripping itself, restated precisely now that dev mode does more than just skip stripping**: which script runs is recorded once, at first-clone time, as a persistent top-level config flag (`dev_mode: true/false`, living in the top-level config directory alongside everything else that's genuinely shared state) — not something asked again on every subsequent update. Both installers perform the identical clone-and-handoff mechanics above; the two things that differ downstream are the wizard's own interactivity (above) and what Setup API's finalize routine does *inside* the fresh clone afterward:
- **Normal (`dev_mode: false`)**: the finalize routine strips development-only content from the clone before the program's first real boot — `CONTRIBUTING.md`, the entire `docs/` folder, the entire `tests/` tree, `.github/PULL_REQUEST_TEMPLATE/`, `.github/workflows/`, `.github/scripts/`, and `.github/instructions/` (Copilot's own path-scoped review guidance, `docs/MAINTENANCE.md` §7 — GitHub-tooling-only, no purpose in a running end-user instance). None of it serves any purpose in a running end-user instance, and per §1.6's own reasoning, it would otherwise multiply once per clone across every channel a multi-tenant hosted deployment runs — real, avoidable bloat, not a hypothetical one.
- **Developer mode (`dev_mode: true`)**: nothing gets stripped. The full docs corpus, full test tree, and full CI/PR scaffolding stay in the clone, since a contributor working in it needs all of it.

**This stripping logic is shared, not duplicated, between Setup API and Update API — a real consequence of the "shared plumbing, separate domain logic" principle** (`docs/PRINCIPLES.md` §1.5): Setup API's finalize routine handles the *first* clone, but Update API's own `release_manager.py` (its own deep-dive §3) performs every *subsequent* clone as part of normal channel operation — every update is a fresh clone, not a pull. Both call into one shared `strip_development_content(clone_dir, dev_mode)` function rather than each reimplementing the stripping list independently, which would risk the two lists silently drifting apart over time. The persistent `dev_mode` flag set at first install is what every later clone (via Update API) reads to decide whether to strip — a developer-mode install stays developer-mode across every subsequent update without re-asking, and vice versa.

---

## 5. Hardware detection — the static profile, real V2 technique worth preserving

### 5.1 Platform-dispatch probing
Windows: WMI queried via PowerShell (`ConvertTo-Json` over `Win32_Processor`/`Win32_VideoController`/etc.), parsed for CPU name/cores/threads, GPU name/VRAM, NPU presence. Linux: `/proc/cpuinfo` and `/proc/meminfo` for CPU/RAM, `lspci` for GPU enumeration (grep for VGA/3D-controller/display-controller class lines). **A real, concrete parsing gotcha worth preserving exactly**: PowerShell's `ConvertTo-Json` unwraps a single-item array into a bare object rather than a one-element array — a machine with exactly one GPU returns a dict, not a list-of-one — so the parser needs to normalize both shapes (`if isinstance(gpus_raw, dict): gpus_raw = [gpus_raw]`) rather than assuming a list, a genuinely easy bug to hit if not handled explicitly.

### 5.2 The VRAM-reporting gotcha — a real bug worth designing around, not a hypothetical
**`AdapterRAM` (the straightforward WMI field) is a capped, unreliable 32-bit value — real-world observed failure: a 12GB GPU reporting as ~2GB through this field alone.** The registry's `HardwareInformation.qwMemorySize` value (`RegVramBytes` in the parsed output) is the authoritative source whenever present and must win over `AdapterRAM`, not be averaged or treated as a tiebreak — this is a real, documented Windows WMI limitation (the field is genuinely too narrow for modern VRAM sizes), not a parsing bug on this project's side. Fallback order: registry value → `AdapterRAM` → `None` (never guess a number).

**GPU classification** (vendor, discrete-vs-integrated, compute API) matters because it's what feeds every downstream hardware-acceleration decision across OCR/Preprocessing/Inference's own deep-dives (their EP-selection lists) — an Intel Arc discrete GPU classifies to `compute_api: "sycl"` (OpenVINO/oneAPI's ecosystem), NVIDIA to `"cuda"`, AMD to `"rocm"` (with the MIGraphX caveat already established in the OCR/Inference deep-dives — ROCm's own EP was removed from ONNX Runtime as of 1.23), and a non-discrete "Intel(R) Graphics"-named adapter still correctly classifies as Intel/integrated despite the generic name (a real V2 finding — Arrow Lake-generation iGPUs report under a plain, non-descriptive name that still needs correct vendor/discrete classification, not a name-pattern miss).

### 5.3 External report import — a genuine, valuable fallback, not a redundant feature
When the OS-level probe undercounts GPU shader/core counts (a real, observed gap — WMI's own core-count reporting for GPUs is unreliable in a way VRAM's registry fallback doesn't fully compensate for), Setup API looks for a CPU-Z or HWiNFO text report the user may have already generated (common, standard tools for exactly this kind of hardware diagnostic) in a small set of candidate directories (Documents, plus any explicitly configured extra path) and parses out real hardware-read core counts to override the static per-SKU lookup/vendor-guess table for any matching adapter, merging across multiple report files if more than one is found. Best-effort either way — `HardwareProfile.source` records whether external-report data contributed, for transparency about how a given profile was actually derived, not left silently blended in. **Consent, resolved during the Setup Sequence walkthrough, following the same `dev`/normal split established for the installer choice itself (§4.1)**: `setup-dev` scans silently, consistent with developer mode's whole bare-bones, no-prompts philosophy — a contributor running a local dev checkout isn't the audience a Documents-folder-scanning consent prompt is protecting. Normal setup asks explicitly (*"Look in your Documents folder for a CPU-Z/HWiNFO report, for more accurate hardware detection?"*) as part of its own immersive, consent-conscious wizard experience — the same asymmetry as §4.1's confirmation prompt, just inverted (there, dev mode was the one that double-checks; here, normal mode is, because normal mode's whole design goal is a careful, transparent first impression for someone who's never used this system before).

### 5.4 Recommended-settings scoring
A calibrated tier-recommendation function (`scoring.py`) mapping a `HardwareProfile` to suggested defaults (which OCR engines, whether to enable heavier Inference presets, Preprocessing's UMat/OpenCL device preference) — V2's version was calibrated against real `bench.py` runs, not a theoretical formula; **worth preserving that same discipline in V3: this scoring function's actual coefficients should come from the bench suite's real measurements (already specified across the OCR/Preprocessing/Inference deep-dives' own testing-hooks sections) once they exist, not invented fresh here.** This is the natural consumer of exactly the bench data those other deep-dives' testing sections already call for.

---

## 6. Resolving the shared hardware substrate — detection here, live tracking in Health API instead
The OCR (§5.6), Inference (§8.6), and Preprocessing (§6.7) deep-dives each proposed "Setup API becomes the shared hardware-detection source of truth *and* the live VRAM-reservation broker," flagged pending this session. **Resolved with a refinement, not a flat confirmation**: splitting the two responsibilities across their natural owners gives a cleaner fit than putting both on this API.

- **Static detection (`HardwareProfile`, §3) — confirmed, Setup API's job.** This matches Setup's actual nature: runs once (or on explicit re-invocation), produces a profile, done. OCR/Inference/Preprocessing all consume this same published profile at their own startup rather than re-probing hardware independently — the original proposal's core idea, confirmed as-is.
- **Live resource commitment tracking (which process currently holds how much VRAM on which device) — reassigned to Health API instead of Setup API.** Reasoning: this is fundamentally a *runtime, continuously-queried* concern — OCR/Inference need to check in with it on effectively every GPU-backed session creation, the same high-frequency pattern as Auth's `ValidateSession` hot path (its own deep-dive §8) — and Setup API's whole nature is a one-time or rarely-invoked flow, not a service built to be hammered with frequent runtime queries. Health API, by contrast, already exists specifically as the live-diagnostic, continuously-running status layer every other API in this batch has been pointing to for exactly this kind of "ongoing runtime signal" concern (Execution Core's Watchdog integration, Auth's session latency, Account Guardian's delivery-failure signal) — a live VRAM ledger is the same *kind* of responsibility, not a new category, so it belongs there instead of being force-fit onto Setup API just because Setup API happens to be the one that first measured what hardware exists.
- **The dependency is directional, not circular**: Health API's live ledger reads its device list *from* Setup API's `HardwareProfile` (published once, refreshed only on explicit re-detection) — Health doesn't re-probe hardware itself, it tracks commitment against a profile Setup already produced.

**This resolution should be carried back into the three prior deep-dives' open-questions sections** — flagged in §10 here as the concrete follow-up action, rather than silently left for someone to notice the docs disagree.

---

## 7. First-run config wizard

**The actual, complete, word-for-word script for this wizard — layman's terms, branched by use case ("just for myself" / "my company" / "the public") — lives in `docs/SETUP_WIZARD_SCRIPT.md`.** This section describes the underlying technical mechanism each step calls into; that document is the user-facing copy built on top of it, kept consistent with this section rather than duplicating its own technical detail.

`tenancy_mode` choice (single/multi), initial owner account creation via Auth & Tenancy API (its own deep-dive — for `multi` mode the owner picks any one of Auth's four supported methods, SSO/passkey/email/SMS, `v3-deepdive-05-auth-tenancy-api.md` §4, not just OIDC specifically as an earlier version of this document assumed before that API's own multi-method expansion; for `single` mode it's the trivial implicit-owner path Auth's own §6.2 already describes), a **run-on-startup offer** (§7.1), a **Tunnel Exposure setup offer** (§7.2, new — a real integration gap found and closed during this walkthrough), a **billing configuration offer** (§7.3, new), a **Groups setup offer** for `multi`-tenant company use (new, `v3-deepdive-41-groups.md`), and a Google Drive config-restore offer if the SSO'd account has a previous instance's encrypted config backed up (relevant for a reinstall/migration scenario, not a first-ever setup). **No forced tier selection** — an earlier version of this wizard asked every install to pick an initial performance tier, which doesn't hold up once self-hosted `multi`-mode installs are a real, supported case (Auth's own Groups design, its deep-dive §7; Billing's own scope correction, its deep-dive §1): tiers are only meaningful once an owner has actually decided whether and how to use them, which §7.3 below now actually offers as a real step rather than forcing at first boot. Both the normal (immersive, interactive) and developer (bare-bones, defaulted) modes covered in full detail in Setup API's own §4.1 — TUI-driven via the same menu-data pattern as the rest of Interface API rather than a separate wizard UI technology, for the normal path specifically.

### 7.1 Run on startup — primary home is TUI settings, not the first-run wizard
**Corrected: the actual, persistent control surface for this is a TUI settings entry (Interface's menu-data), always there and changeable anytime — the first-run wizard is only an optional convenience default offered once, not the real home for this setting.** For a self-hosted install (irrelevant to the hosted multi-tenant service, which already runs continuously on DOMTRI's own infrastructure), Interface API's settings menu carries a toggle calling directly into the same registration interface below; normal-mode first-run setup *also* offers to enable it as a one-time convenience during onboarding (skipping a trip to settings for the common case of "yes, I want this"), but that wizard offer and the settings toggle are two entry points into the identical mechanism, not two different features — genuinely fine to keep the wizard convenience, since it doesn't cost anything to offer as a default while the real, persistent control stays in settings. Either path registers the top-level `start.bat`/`start.sh` launcher with the OS's own autostart mechanism, invoked at login/boot rather than requiring a manual launch every time. **Built as a Provider Registry (`docs/PRINCIPLES.md` §1.2) from the start, not per-OS branching logic scattered through one function** — the same discipline every other pluggable capability in this project already follows:
```python
class StartupRegistrar(Protocol):
    async def register(self, launcher_path: Path) -> None: ...
    async def deregister(self) -> None: ...
    async def is_registered(self) -> bool: ...
```
Concrete providers: `WindowsTaskSchedulerRegistrar`, `WindowsStartupFolderRegistrar` (two genuinely distinct Windows options, not redundant — Task Scheduler supports running elevated/with a delay/on specific triggers, the Startup folder is simpler and needs no elevation; a power user might deliberately prefer one over the other), `LinuxSystemdUserRegistrar` (a user-level `systemd` unit, `WantedBy=default.target`). **macOS (`launchd`) is a structurally accommodated future extension point, not fully designed here** — the same Protocol, a `LaunchdRegistrar` implementation whenever macOS self-hosting is actually prioritized, no redesign needed to add it later. The registry auto-selects a sensible default based on Setup's own already-detected OS (`HardwareProfile`, §5) but stays swappable — the same "auto-selected default, never hardcoded" pattern as every other Provider Registry entry in this project, exposed as a real config choice for the Windows two-provider case specifically, editable from the same settings screen at any time, not locked in at first-run.

**Deliberately not Supervisor's own concern** (`v3-deepdive-38-supervisor.md`) — Supervisor manages process lifecycle *after* the program has started; getting the program to start at all on a fresh boot is a one-time OS-registration action, squarely Setup API's own bootstrap-adjacent territory, toggleable later as a normal settings entry (Interface's menu-data) that calls back into this same registration/deregistration logic through the same `StartupRegistrar` interface. Skipped entirely in developer mode, consistent with §4.1's bare-bones philosophy — a contributor running a local dev checkout has no reason to want it launching at every boot.

### 7.2 Tunnel Exposure setup — a real integration gap, found during this walkthrough and closed
**`v3-deepdive-43-tunnel-exposure.md` §3 already stated its own first-run integration point as "Setup deep-dive §7" — but this document never actually reflected that, a real instance of the same "referenced elsewhere, never actually wired up" pattern this project has hit repeatedly.** Fixed here: for a `multi`-tenant self-hosted install that wants public reachability (irrelevant to `single`-tenant local-only use, and irrelevant to DOMTRI's own hosted service, which already has its own production ingress), the wizard offers to walk through Tunnel Exposure's own `CloudflareTunnelProvider` setup — the `cloudflared tunnel login` flow, choosing a public hostname, and the CNAME record creation — as one skippable step, reachable again later through the same settings surface (its own deep-dive §3) if declined here. **Skipped entirely in developer mode**, consistent with §4.1's bare-bones philosophy. **Completing this step sets `public_facing: true`** (Auth's own config, `v3-deepdive-05-auth-tenancy-api.md` §4.6.1) — the real signal that install's 2FA enforcement floor tightens automatically, not a separate setting an owner has to remember to also configure.

### 7.3 Billing configuration offer — genuinely optional, matching billing's own true default of "off"
For `multi`-tenant installs specifically, the wizard offers to walk through Billing API's own PSP setup (`v3-deepdive-22-billing-subscription-api.md` §3.2) — picking a provider (PayMongo default), entering credentials, choosing which tiers to enable, and — resolved with real direction — the owner's own proration policy for upgrades and downgrades (`v3-deepdive-22-billing-subscription-api.md` §3.3, independently selectable per direction). **Genuinely, visibly optional and skippable**, consistent with Billing's own confirmed default state (every tier free until an owner opts in) — declining here is a completely normal, expected outcome, not a "you'll be reminded later" deferral; the same settings entry remains available anytime an owner decides to configure it. Skipped entirely in developer mode and for `single`-tenant installs, where billing has no meaningful role to play at all.

### 7.3.1 SMS provider setup offer — genuinely optional, off by default
For `multi`-tenant installs that want SMS notifications enabled, the wizard offers to walk through Notifications API's own real, provider-specific guided setup (`v3-deepdive-09-notifications-inbox-api.md` §4.3) — picking one or more of Semaphore/PhilSMS/Twilio, entering credentials, and for the PH-specific providers, the sender-name registration step those specifically require. Off by default, skippable, with the identical setup flow also reachable anytime later through Notifications' own settings-menu entry — the same two-entry-point pattern this document already establishes for run-on-startup (§7.1).

### 7.4 The finalize routine's own last steps, restated so the full sequence is traceable end to end
Once the wizard's own steps complete (or are skipped, per the developer-mode defaults), Setup API's finalize routine performs, in order: `strip_development_content()` (§4.1, normal mode only), `build_webapp()` (Gateway's own deep-dive §4.1 — every fresh clone, including this first one, builds its own webapp bundle as part of this same routine, not a separately-scheduled step), and the top-level setup-file cleanup (§4's own "setup files are cleaned out once their job is done" rule) — before handing off to Supervisor's own Boot Sequence (`v3-deepdive-38-supervisor.md` §3.2) for the program's actual first real launch.

---

## 8. Asyncio, free-threading, and profiling

### 8.1 Where asyncio matters, and where it doesn't
Hardware detection (§5) is a mix of subprocess calls (PowerShell, `lspci`) and file I/O (external report scanning) — genuinely worth async-wrapping the subprocess calls via `run_in_executor` (the same pattern used throughout this project's other deep-dives for blocking native/subprocess work), though the actual volume here is trivially small (a handful of calls, once, not a hot path) — this is much lower-stakes than OCR's Tesseract-subprocess-under-concurrent-load concern, since Setup API never runs many of these in parallel.

### 8.2 Free-threading and profiling
Genuinely minimal relevance — a one-time or rarely-invoked flow with no compute-bound hot path and no meaningful concurrency story to speak of. Not worth the same depth of treatment as the compute-heavy APIs; stated briefly rather than padded out to match their length artificially.

---

## 9. Config, gRPC surface, and testing hooks (kept brief — deliberately a smaller surface than most of this batch)

```protobuf
service SetupService {
  rpc DetectHardware(DetectRequest) returns (HardwareProfileResponse);
  rpc RunWizard(WizardRequest) returns (stream WizardStep);   // server-streaming for a live multi-step wizard UI
}
```
```
setup:
  hardware_report_paths: []       # extra CPU-Z/HWiNFO report search paths, see §5.3
  dev_mode: false                   # set once at first clone, persists across every subsequent Update API clone — see §4.1
  startup_registrar: auto             # auto | windows_task_scheduler | windows_startup_folder | linux_systemd_user | none — see §7.1
```
**Testing**: the WMI single-GPU-unwraps-to-dict parsing gotcha (§5.1) and the AdapterRAM-vs-registry VRAM precedence (§5.2) both deserve their own explicit regression tests, given they're real, previously-hit bugs, not hypothetical edge cases — a regression here would silently degrade every downstream hardware-acceleration decision across three other APIs without necessarily failing loudly.

---

## 10. Open questions for this deep-dive, and a required follow-up action
- (Required follow-up for OCR/Inference/Preprocessing's own shared-substrate entries — resolved, no longer open. Checked directly: all three already correctly reflect §6's refined split rather than the original flat framing — OCR and Inference both explicitly state "fully resolved, nothing pending" citing Health API's own reservation design, and Preprocessing's own participation-depth question is resolved as a deliberate lightweight-registration choice. This note was itself stale, describing work that had already been done elsewhere without ever being marked complete here.)
- **Windows registrar default, resolved: Task Scheduler.** Supports running elevated/with a delay/on specific triggers — genuinely more capable than the Startup folder for the kind of "launch this heavier program reliably" case this feature exists for, a real reason to prefer it as the default rather than an arbitrary pick between two equally-viable options. The Startup folder stays available as a real, simpler alternative for an owner who specifically wants it.
- **Health API's own live-ledger design** — resolved: Health API's deep-dive (`v3-deepdive-20-health-api.md` §4) designed the reservation contract (TTL-based, refreshed via Watchdog's heartbeat), closing the loop §6 here opened.
- **Recommended-settings scoring coefficients** (§5.4) — explicitly deferred to real bench data per those APIs' own testing sections, not invented here.
- (`strip_development_content()`'s exact file list, kept current — resolved, no longer open. `.github/scripts/check_stripped_content_list.py` now enforces this structurally: every top-level entry must be explicitly classified as shipped or dev-only, or CI fails immediately with the specific unclassified entry named. This is a closed-world check, not a second hardcoded pattern-list that could drift the same way the original list did twice — a genuinely new top-level entry can't merge silently unclassified. Tested against both the passing case and the actual drift scenario before being presented, not just checked for syntax validity.)
- **`StartupRegistrar`'s macOS provider** (§7.1): structurally accommodated (same Protocol, a `LaunchdRegistrar` slots in cleanly) but not implemented — genuinely deferred, not forgotten.
