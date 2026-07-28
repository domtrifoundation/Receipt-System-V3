# Setup API

Setup API owns: the one-time distribution/bootstrap handoff, hardware/environment detection (**the static profile** — see §5 for the important distinction from live resource tracking), dependency installation, and the first-run config wizard.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 ran a real first-run setup interview and persisted the answers to `receipt-processor-config.json`. V2 had `setup.bat`/`setup.sh` plus `scripts/setup_wizard.ps1` and `scripts/setup_check_config.py` — the helper-script sprawl this generation exists to fix. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

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

Idempotent, safely re-runnable *is* the fix for V2's sprawl — not a nicer wrapper around the same fragility. A self-referential script must never move or delete itself while running (fragile everywhere, worse on Windows with locked executing files): the setup script's last action hands off to this API's own Python finalize routine. `strip_development_content()` is shared with Update API's `release_manager.py` rather than reimplemented, so the two strip lists cannot drift.
