# Proving Grounds

**Sub-API of Update/Deployment API** (`services/update/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Proving Grounds owns **automated candidate testing** — running a real bench workload against a dependency bump or a code-release channel candidate before it's promoted anywhere.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had a bench suite (`bench.py`) but no candidate-testing mechanism — nothing cloned, isolated, and validated a dependency bump or release candidate before adopting it. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-36-proving-grounds.md`](../../../docs/apis/v3-deepdive-36-proving-grounds.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide what to test** — Dependencies Warden surfaces "this exists now" (a new dependency release, a flagged pre-release feature); a human judgment call decides what's program-important enough to test (file 02 rule #8); Proving Grounds only executes the test once asked.
- **own the bench suite's own design** — reuses each affected API's own bench workload (OCR's, Inference's, Preprocessing's) as already specified in their own deep-dives' testing-hooks sections, never a separate testing methodology invented here.

## Forward-Compatibility Pattern applicability

No `FrozenDict`-typed field, no GIL-dependent assumption, and no `asyncio` behaviour that has changed across 3.14/3.15/3.16 in this folder as designed (`docs/PRINCIPLES.md` §3.3.1). Re-check this line in the same PR that adds one — a stale "not applicable" is the specific drift the guide's §6 warns about.

## Real gotchas specific to this folder

This mechanism does not know or care *why* it is testing something — channel promotion and Dependencies Warden are two callers of one mechanism, which is the whole reason it lives under Update (it reuses Update's release-directory machinery) rather than under Telemetrees. A dependency bump gets the real bench workload for the code it actually affects, never a generic smoke test standing in for it.
