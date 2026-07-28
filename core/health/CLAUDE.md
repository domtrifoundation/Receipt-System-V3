# Health API

Health owns two layers: **status** (service up/down, queue depth, per-instance resource utilization, external-dependency reachability) and **live diagnostic** (the bench suite's own empirical classification technique, reused continuously against real traffic). It also now owns the **live resource commitment ledger** (§4, resolved in Setup's deep-dive) — tracking which process currently holds how much VRAM on which device, distinct from Setup's own static `HardwareProfile`.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had a real health layer — `health.py`'s watchdog thread and heartbeat file, plus `metrics.py` and `hardware.py` for utilization and capability reporting. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a02.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-20-health-api.md`](../../docs/apis/v3-deepdive-20-health-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **detect what hardware exists** — that's Setup API's `HardwareProfile` (its own deep-dive §5); Health reads that published profile rather than re-probing.
- **decide rollout cutover policy** — Update API's Supervisor consumes Health's status signal to gate a release swap; Health only reports, it doesn't decide when a rollout proceeds.
- **implement Watchdog's restart mechanism itself** — Watchdog (§5) is Health's own sub-API, but the actual process-restart action is a Supervisor-level capability Watchdog triggers, not something Health performs directly on a process it doesn't own.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Setup owns static hardware *detection*; Health owns the live resource *ledger*. That split is deliberate and worked out from what each API is actually for, not from who thought of it first (`docs/PRINCIPLES.md` §1.5) — Health reads Setup's published profile rather than re-probing. Health reports; it never decides when a rollout proceeds.
