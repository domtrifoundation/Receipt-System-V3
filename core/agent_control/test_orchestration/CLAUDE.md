# Test Orchestration

**Sub-API of Agent Control API** (`core/agent_control/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Test Orchestration owns making genuinely complex tests — ones that can't reasonably be "just run a script and check the exit code" — callable through Agent Control's own MCP server and headless CLI, so Claude Code (or any other agent/automation) can run them, get a structured result back, and reason about what happened.

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2's `bench.py` ran benchmarks directly; nothing made complex tests callable as a structured, agent-invocable surface. No V1 equivalent. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-56-test-orchestration.md`](../../../docs/apis/v3-deepdive-56-test-orchestration.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **replace `docs/testing/TOOLKIT.md`'s own existing tools** — the bench suite, profiling, fuzzing, and load-testing tools already described there still exist and still work the way they already do; this sub-API is a new, structured *calling convention* on top of them, not a second implementation.
- **decide what a test result means** — a `TestResult` reports what happened (pass/fail, structured detail); whether that's acceptable is still the caller's (a human, or Claude Code interpreting the result) own judgment.
- **replace ordinary unit tests.** A simple, fast, mockable unit test stays exactly what it already is — `pytest`, run directly, no orchestration needed. This sub-API exists specifically for the tests that are hard to run reliably any other way.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

This is the only component in the system that deliberately signals another service's worker processes, and only ever a process Supervisor itself identified — never a blind `pkill` (`docs/PROCESS_TOPOLOGY.md` §7). It also carries a structural safeguard against synthetic test fixtures being mistaken for real receipt scans; that safeguard is load-bearing, not a convenience. Ordinary fast unit tests stay plain `pytest` — this exists for the tests that are genuinely hard to run reliably any other way.
