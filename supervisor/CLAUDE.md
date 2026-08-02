# Supervisor

Supervisor is the **one thing that lives outside every release clone, permanently** — not inside any versioned `<version>_<commit-hash>` directory, a genuine top-level citizen alongside config and shared data (`docs/PRINCIPLES.md` §1.6). It owns: determining which release is active per channel, launching every service from the correct clone's own venv in dependency order, health-gating rollout cutover, driving rollback, and — new — sleeping/waking genuinely idle services.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no process supervision, release arbitration, or rollback — `run.bat` started the one program. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a01.00.00`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-38-supervisor.md`](../docs/apis/v3-deepdive-38-supervisor.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide business logic** — Supervisor launches processes and watches health signals; it has no opinion about what any service actually does.
- **update itself the way it updates everything else** — this is the entire reason this document exists; see §4.
- **replace Watchdog** — Watchdog (Health API's sub-API) proves a *running* service is alive via kicks; Supervisor decides whether a service should be *running at all* in the first place. Different questions, deliberately different owners.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

Structurally neither Layer 1 nor Layer 2 (`docs/PROCESS_TOPOLOGY.md` §1): it lives outside every release clone, permanently, because it is what decides which clone is active and cannot be part of what it launches. Keeping it small is a load-bearing design goal, not tidiness — it is the one component that cannot update itself the way it updates everything else. It launches processes and watches health signals; it has no opinion about what any service does.
