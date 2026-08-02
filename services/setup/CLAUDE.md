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

`a03.00.01`

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

**Partially implemented.** `contracts.py` and `venv_provisioning.py` are real; hardware detection (§5), the wizard (§7), `bootstrap.py`, and `dev_mode_strip.py` are still 0-byte scaffolding. `contracts.py` says so at the top so a future session does not mistake it for a finished file.

**Files here that the deep-dive's §2 package layout does not list**, with the reason:
- `venv_provisioning.py` — per-service venv creation, the mechanism behind the "dependency installation" this API's own §1 has always claimed to own but never described. Full design in [`docs/VENV_AND_IMPORTS.md`](../../docs/VENV_AND_IMPORTS.md). It sits here rather than in Update API for the same reason `dev_mode_strip.py` does: Setup provisions the *first* clone, Update's `release_manager.py` provisions every subsequent one, and one shared implementation is what stops the two drifting (`docs/PRINCIPLES.md` §1.5).

**Venvs hold third-party packages only.** First-party code resolves from the clone root on `PYTHONPATH` — nothing installs this project into a venv. If you are tempted to add `pip install -e .`, read `docs/VENV_AND_IMPORTS.md` §3 first: across N clones × 32 venvs, editable installs' failure mode is importing *another clone's* code, which is exactly what the clone-per-release model exists to prevent.

**Per-service venvs isolate dependencies, not namespaces.** The whole clone is on `PYTHONPATH`, so a service *can* physically import a sibling's modules. The rule that it must not — gRPC and injected `Protocol` seams, never a direct `core.x` import — stays enforced by review and the `contracts.py`-only convention. Do not assume the venv boundary is enforcing it.

Idempotent, safely re-runnable *is* the fix for V2's sprawl — not a nicer wrapper around the same fragility. A self-referential script must never move or delete itself while running (fragile everywhere, worse on Windows with locked executing files): the setup script's last action hands off to this API's own Python finalize routine. `strip_development_content()` is shared with Update API's `release_manager.py` rather than reimplemented, so the two strip lists cannot drift.
