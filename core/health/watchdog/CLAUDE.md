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

`a02.00.01`

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

**Yes — this line changed when the implementation landed, and this is the PR that changed it.**
It previously read "not applicable" because the folder was scaffolding. It has a `FrozenDict`-typed
field now: `WatchdogConfig.per_service_timeouts`, which is how §10's resolved open question
(a global default plus real per-service overrides, since Inference's model-load cycle is
genuinely longer than a lightweight API's heartbeat) is carried. `timeout_detector.resolve_timeout`
reads it through `.get` and never through `isinstance(x, dict)` — on 3.15 the builtin
`frozendict` is not a `dict` subclass, so such a check silently returns False and hands every
service the global default while appearing to honour the override
(`docs/PRINCIPLES.md` §2.1, §2.1.1). `tests/unit/core/health/test_contracts.py` carries the
`@pytest.mark.forward_compat` assertion for it.

`KickRegistry`'s own map is genuinely mutable internal state, which §2.1.1 does not reach, and
is guarded by a real lock rather than relying on the GIL making `dict` mutation atomic — this
project targets free-threaded 3.14t, where that assumption does not hold (§3.3.1).

## Real gotchas specific to this folder

The failure mode this exists for is hung-not-crashed: a process that still exists and still answers a process-status check while doing nothing. That is why liveness is proven by periodic kicks rather than inferred from the process table. Watchdog detects and triggers; Supervisor performs the restart. Version and commit ride on the heartbeat response specifically, not on every business response.
