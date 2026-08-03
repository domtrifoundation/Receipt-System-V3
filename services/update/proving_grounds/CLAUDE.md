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

## Current API version

`a01.00.01`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

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

**Every file §2 names, plus `.proto`/`service.py`, is now real** — this folder was entirely 0-byte scaffolding before this session. `test_candidate()` and `gate_promotion()` match the deep-dive's own §4 signatures exactly. Confirmed live: real streamed downloads against a real local HTTP server (including a real `Authorization: Bearer <token>` header for HF-gated models, §3's own hardening requirement), a real `docker version` reachability probe correctly reporting unavailable when Docker isn't installed, a real bench-dispatch round trip through a registered `BenchDispatcher`, a genuine bench failure correctly distinguished from a test that couldn't run at all (`passed=False` vs. `ok=False`), a dispatcher's own exception converted to data rather than propagating, and `gate_promotion()` correctly denying a `passed=True` result whose `ok=False` (the test never actually ran) — the exact case §7's "promotion-gate bypass test" hook exists to catch.

**No bench suite exists for any Core API yet — `BenchDispatcherRegistry.default_registry()` starts empty, the honest state, not a gap papered over.** `test_candidate()` against any real `affected_api` today correctly reports `NO_BENCH_DISPATCHER`, matching `core/task_scheduler/registry.py`'s own `default_registry()` posture toward its allowlist. Wiring in a real dispatcher for a given API is that API's own future work (each one's own deep-dive testing-hooks section is the design to build against), not something this pass fabricates.

**Isolation is Docker via a plain `subprocess` CLI wrapper, not the `docker` Python SDK** — matching `installer/common.sh`'s own "plain CLI, nothing else" posture, and one fewer third-party dependency for what a single subprocess call already does. A host with no Docker binary correctly reports `CONTAINER_RUNNER_UNAVAILABLE` rather than silently running a candidate's bench suite unisolated — an untrusted candidate run unisolated would defeat this whole sub-API's reason to exist.

**`changelog_watcher.py` is real but deliberately does nothing beyond reading.** It is not in the deep-dive's own §2 package layout (present in this folder's scaffold anyway, kept rather than deleted); it fetches Telemetrees' own real `GetChangelog` RPC content for a human to read and builds no `TestCandidate` and calls no `test_candidate()` — `core/telemetrees/dependencies_warden/CLAUDE.md`'s own words: "whether a surfaced change is program-important is a human call, deliberately not automated from a changelog diff."

**`GetTestHistory` is backed by a real in-memory list, not persisted** — the same honest, explicitly-scoped choice `core/billing/service.py`'s own `SubscriptionService` makes; a persistence adapter is real future work, not this pass's scope.
