# Setup API

Setup API owns: the one-time distribution/bootstrap handoff, hardware/environment detection (**the static profile** — see §5 for the important distinction from live resource tracking), dependency installation, and the first-run config wizard.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 ran a real first-run setup interview and persisted the answers to `receipt-processor-config.json`. V2 had `setup.bat`/`setup.sh` plus `scripts/setup_wizard.ps1` and `scripts/setup_check_config.py` — the helper-script sprawl this generation exists to fix. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.10`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-11-setup-api.md`](../../docs/apis/v3-deepdive-11-setup-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own dependency *download infrastructure*** — that's shared with Update API's Proving Grounds sub-API (file 01 #21's note), Setup just calls into it for the initial install.
- **own live resource/VRAM commitment tracking** — resolved here, differently than the other three deep-dives tentatively proposed: see §6.
- **own Keymaster's licensing logic** — Update API's territory; Setup's wizard is only where a license key gets *entered*, not where it's validated or enforced.
- **run on every launch** — that's the Startup Sequence (file 02, a designed flow, not its own API). Setup runs once (or whenever explicitly re-invoked); Startup Sequence runs every time the program starts.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

**Implemented.** Every file §2's own package layout names is real: `contracts.py`, `bootstrap.py` (§4/§7.4's finalize routine), `dev_mode_strip.py` (§4.1), `dev_fixtures.py` (§4.1, deliberately narrower than the sketch — see below), `hardware/detect.py`/`report_import.py`/`scoring.py` (§5), `wizard.py` (§7 — the whole `docs/SETUP_WIZARD_SCRIPT.md` step sequence, all three branches, verified against real live hardware and a real live `grpc.aio` connection during development, not just unit-tested against fakes), `errors.py`, `metrics.py`. Plus `venv_provisioning.py`, `service.py`, `setup.proto` + `generated/`, beyond §2's own list — see below for each.

**Files here that the deep-dive's §2 package layout does not list**, with the reason:
- `venv_provisioning.py` — per-service venv creation, the mechanism behind the "dependency installation" this API's own §1 has always claimed to own but never described. Full design in [`docs/VENV_AND_IMPORTS.md`](../../docs/VENV_AND_IMPORTS.md). It sits here rather than in Update API for the same reason `dev_mode_strip.py` does: Setup provisions the *first* clone, Update's `release_manager.py` provisions every subsequent one, and one shared implementation is what stops the two drifting (`docs/PRINCIPLES.md` §1.5).
- `setup.proto` + `generated/` + `service.py` — §9 sketches the gRPC surface but never names where the `.proto` lives, the same gap every other API's own `CLAUDE.md` notes about its own proto. Regenerate with `python -m grpc_tools.protoc -I. --python_out=generated --grpc_python_out=generated --pyi_out=generated setup.proto` from this directory, then re-apply the relative-import fix in `generated/setup_pb2_grpc.py` (`import setup_pb2` → `from . import setup_pb2`); never hand-edit generated files. `service.py` imports them lazily inside each method and inside `serve()`, matching `core/geo_address/service.py`'s own convention, so this package stays importable — and its tests meaningful — on an interpreter with no `grpcio` wheel (this project's own live gap on 3.15, `docs/MAINTENANCE.md` §8.1).

**`RunWizard` is bidirectional streaming, correcting §9's own sketch.** §9 wrote `rpc RunWizard(WizardRequest) returns (stream WizardStep)` — one input, then a one-way stream. That cannot express the wizard's real flow: each step needs the owner's answer before the next step is even decided (which branch a use case takes, whether a decline changes what comes next). `WizardEngine.run()` is an async generator for exactly this reason, and bidirectional streaming (`rpc RunWizard(stream WizardAnswerMessage) returns (stream WizardStepMessage)`) is gRPC's direct mapping of that same shape. Recorded as a correction, not a silent fix — the same category as Execution Core's §7 retry sketch and Reconciliation's §4.1 VAT sketch.

**`dev_fixtures.py` deliberately implements only one of §4.1's three asks.** §4.1 wants "a pre-populated `.env`/config," "sample/fixture receipt images and a seeded SQLite dataset," and "stub/mock provider configurations." Only the first is built. The other two are not gaps — they conflict with standing rules this project holds elsewhere: no synthetic receipt data of any kind, ever (images or database rows), and no package reaching into another API's own Provider Registry to add a provider implementation it doesn't own (`docs/PRINCIPLES.md` §1.2/§1.3). `dev_fixtures.py`'s own module docstring states both conflicts and the resolution in full; read it before "completing" either of those two asks.

**`dev_mode_strip.py` owns the classification lists; `.github/scripts/check_stripped_content_list.py` imports them from here.** That is the reverse of what the CI script originally claimed, and the reversal is not stylistic: `.github/` is itself in `DEV_ONLY_STRIP_LIST`, so the old direction had `strip_development_content()` importing its own strip list out of the directory it deletes — fine on a first run, broken on the second, and Setup is explicitly re-runnable while Update strips every fresh clone. `services/` ships, so the definition lives here where it stays reachable. Do not move it back.

**`NESTED_STRIP_FILENAMES` is why `CLAUDE.md` is stripped from all 52 nested locations, not just the root.** A top-level entry name cannot express "strip this filename wherever it appears"; the CI script flagged that gap explicitly for whoever implemented this module. A nested-strip name that is also in `SHIPPED_ALLOWLIST` would delete shipped content repo-wide, so CI now guards that intersection separately — the two top-level lists can be perfectly disjoint while this one is still wrong.

**Venvs hold third-party packages only.** First-party code resolves from the clone root on `PYTHONPATH` — nothing installs this project into a venv. If you are tempted to add `pip install -e .`, read `docs/VENV_AND_IMPORTS.md` §3 first: across N clones × 32 venvs, editable installs' failure mode is importing *another clone's* code, which is exactly what the clone-per-release model exists to prevent.

**Per-service venvs isolate dependencies, not namespaces.** The whole clone is on `PYTHONPATH`, so a service *can* physically import a sibling's modules. The rule that it must not — gRPC and injected `Protocol` seams, never a direct `core.x` import — stays enforced by review and the `contracts.py`-only convention. Do not assume the venv boundary is enforcing it.

Idempotent, safely re-runnable *is* the fix for V2's sprawl — not a nicer wrapper around the same fragility. A self-referential script must never move or delete itself while running (fragile everywhere, worse on Windows with locked executing files): the setup script's last action hands off to this API's own Python finalize routine. `strip_development_content()` is shared with Update API's `release_manager.py` rather than reimplemented, so the two strip lists cannot drift.

**`bootstrap.py` also copies `LAUNCHER_SCRIPT_NAMES` (`start.bat`/`start.sh`) to the install root and writes `config/install.json`'s `dev_mode` flag** — two real §4/§1.6/§4.1 steps that were missing from the original sequence. Launcher copy overwrites on every finalize (every update is a fresh clone, and the install root's own launcher should track whichever clone most recently finalized); the install config is written exactly once and never overwritten, per §4.1's own "not something asked again on every subsequent update."

**`ensure_wizard_dependencies()` exists because a "clean" venv provisioning report is not a guarantee, confirmed by a real live failure, not a hypothetical.** A real `setup.bat` run (this exact commit, this exact machine) reported `venvs: ok (34 services, 0 failed)` and then the wizard subprocess crashed with a raw `ModuleNotFoundError: No module named 'textual'` — the interface venv's own provisioning genuinely lied. Root cause traced to a *different*, real, live-confirmed bug: `core/ocr/requirements.txt`'s `rapidocr-onnxruntime>=1.3` has no published wheel for Python 3.13+ at all, and under concurrent 8-way venv provisioning, a failure in one service occasionally left a sibling service's own venv in an inconsistent state without that failure surfacing on its own outcome (exact mechanism not fully isolated — Windows + concurrent `pip`/`venv` subprocess creation is the suspected culprit, not confirmed with full certainty). Fixed at the actual source (`core/ocr/requirements.txt` now marks that dependency `; python_version < '3.13'`, matching this file's own header comment's promise that a missing OCR dependency degrades gracefully rather than failing the whole install) *and* defensively (`ensure_wizard_dependencies()` re-verifies `import textual` actually works in the target venv before handing control to it, with one bounded `pip install` repair attempt, reporting a clear actionable message instead of a raw traceback if it still can't). Belt and suspenders, deliberately — the OCR fix addresses the confirmed root cause; the defensive check means a *different* future silent-provisioning-failure can't produce the same scary crash again.

**`bootstrap.py`'s own CLI now actually runs the interactive first-run wizard in normal mode — it did not before.** `run_first_run_wizard()`/`wizard_command()`, called from `__main__` right after a successful `finalize_clone()`, only on the non-`--dev-mode` path (§4.1's own normal/dev split). This re-execs into `.venvs/services.interface/`'s own provisioned interpreter to run `services/interface/tui/wizard_entrypoint.py` — Setup's own `bootstrap.py` process has no `textual` dependency itself and never will (`services/interface/requirements.txt` is a new file, Interface API's own, that is what actually gets `textual` into the interface service's venv during `venv_provisioning.provision_clone()`, itself a step inside the same `finalize_clone()` call). Live-confirmed the whole chain resolves through a freshly-provisioned real venv, not just this repo's own dev `.venv`.

**Real `GetDevMode`/`GetRunOnStartup`/`SetRunOnStartup` RPCs, added for the TUI's own
Settings screen.** `read_dev_mode`/`write_install_config` already existed and are real;
`read_run_on_startup`/`write_run_on_startup` are new, sharing `INSTALL_CONFIG_RELPATH`
with `dev_mode` but never touching that key. **Real, deliberate asymmetry**:
`run_on_startup` is freely re-toggleable at any time (an ordinary operational
preference), unlike `dev_mode`'s write-once-at-first-clone semantics — the two functions'
own docstrings state this explicitly rather than leaving it to be inferred. `SetupServicer`
now takes an optional `install_root`, resolved in `__main__` via the new
`common/install_paths.resolve_install_root()` (a service launched by Boot Sequence runs
with `cwd` set to its own release clone, not the install root — this was a real, previously-
unfilled gap: no service anywhere threaded `install_root` before this pass, because there
was never a shared, honest way to compute it from an arbitrary launched module's own file
location).

**`bootstrap.py`'s own `python -m services.setup.bootstrap <clone_dir> [--dev-mode]` CLI is the real handoff target `installer/common.sh`/`installer/common.bat` invoke.** This was genuinely missing and un-exercised for a while during development — the top-level `installer/*.sh`/`*.bat` scripts clone real committed history, and testing them against *uncommitted* working-tree changes to this file silently exercises the *previous* commit's version instead, which looks like a working end-to-end flow using pytest (pytest reads the working tree directly) while the actual installer script would clone something else entirely. Worth remembering the next time this file changes: commit before testing `installer/` against it, not after.

**`installer/` is a real, top-level, dev-only source tree** (`services/setup/dev_mode_strip.py`'s own `DEV_ONLY_STRIP_LIST`, `.github/workflows/release_installer.yml`) — `setup.bat`/`setup.sh`/`setup-dev.bat`/`setup-dev.sh` plus a `common.bat`/`common.sh` each pair shares (`docs/PRINCIPLES.md` §1.5). Four real, hard-won gotchas from building and live-testing these against actual `cmd.exe`/`bash`, not just reasoning about them:

- **Every `.bat` file here is deliberately ASCII-only with CRLF line endings.** An early UTF-8, LF-only draft made `cmd.exe`'s parser try to execute fragments of prose comments as commands — not a hypothetical, a real failure hit and diagnosed live. `findstr` also needs `/c:"exact phrase"` for a multi-word literal match; without it, `findstr` silently OR-splits the search string into separate single-word patterns, matching almost every line in the file rather than the one intended.
- **A `goto`/label combination inside a parenthesized `if (...)`/`for (...)` block parses unreliably in batch** — confirmed with a real `") was unexpected at this time"` parser error. Every control-flow branch in `common.bat` is deliberately flat (`if ... goto :label`, labels outside any parens) for exactly this reason; do not "clean up" the flat structure back into nested parenthesized blocks, it will reintroduce the same parse failure.
- **A bare `PYTHON_BIN=python`/`python3` default is not safe** — `grpcio` has no prebuilt wheel for 3.15 (`docs/MAINTENANCE.md` §8.1, already documented before this installer existed), and every one of the ~30 service venvs `venv_provisioning.py` creates needs it. Live-tested consequence: every venv silently stalled trying to build `grpcio` from source, indistinguishable from a genuine hang without checking `.venvs/<service>/Lib/site-packages/` directly. Both `common.sh`'s and `common.bat`'s own `detect_python_bin` prefer a real 3.14 (`python3.14`, or `py -3.14` on Windows) before falling back — `start.sh`'s own header comment already states the real intent ("default pinned interpreter (currently 3.14)"); nothing yet actually enforces that pin on a fresh machine, which is the deeper, still-open gap this papers over rather than closes. `common.sh`'s own version keeps the resolved command in the array `PYTHON_CMD`, never a scalar — a scalar holding a two-word value like `"py -3.14"` gets treated as one literal, nonexistent command name when invoked, the exact same failure mode this function exists to avoid, one layer further in.
- **`cmd.exe`'s own `set VAR=value && next-command` (unquoted) silently includes trailing whitespace in the value.** Hit live via `REF_OVERRIDE` (the standing escape-hatch env var both scripts share, for bootstrapping a specific branch/PR ref instead of a channel — genuinely useful beyond testing, not just a today-only knob): a trailing space turned a valid branch name into `git ls-remote`'s own "branch not found" error, which reads nothing like a whitespace bug. `common.bat`'s `:trim_trailing_space` subroutine fixes this — note `for /f "tokens=* delims= "`, the usual idiom people reach for here, only trims *leading* whitespace, confirmed directly; it does not solve this.
