# Watchdog

**Sub-API of Health API** (`core/health/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Watchdog owns **liveness monitoring** — proving a service is alive via periodic kicks, distinct from crash detection (a hung-not-crashed process passes a plain process-status check but is exactly the failure mode this exists to catch).

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2's `health.py` was exactly this — a watchdog thread that restarted the processing loop if it hung past `hang_timeout_seconds`, plus a heartbeat file for external monitors. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-34-watchdog.md`](../../../docs/apis/v3-deepdive-34-watchdog.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **execute the restart itself** — that's Supervisor's own, more conservative code path (Update deep-dive §5); Watchdog detects and triggers, Supervisor acts.
- **duplicate Health's own status/diagnostic layer** — status (up/down, queue depth) and live diagnostic (soft-degradation classification) are the parent API's own concern; Watchdog is specifically about the binary "has this service gone silent" question.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

The failure mode this exists for is hung-not-crashed: a process that still exists and still answers a process-status check while doing nothing. That is why liveness is proven by periodic kicks rather than inferred from the process table. Watchdog detects and triggers; Supervisor performs the restart. Version and commit ride on the heartbeat response specifically, not on every business response.
