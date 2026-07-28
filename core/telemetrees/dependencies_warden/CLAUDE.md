# Dependencies Warden

**Sub-API of Telemetrees API** (`core/telemetrees/`) — read that folder's own `CLAUDE.md` first for the parent's boundary.

Dependencies Warden owns **continuous, automated monitoring** of every tracked dependency's release activity and other tracked facts (free-threading support flags, specific upstream issue states, model/preset currency — the full taxonomy Telemetrees' own deep-dive §3 established).

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no dependency monitoring — its own docs noting llama-cpp-python as deprecated while `bench.py` still referenced it is the concrete example of what having none costs. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-37-dependencies-warden.md`](../../../docs/apis/v3-deepdive-37-dependencies-warden.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide whether to adopt what it finds** — surfaces "this exists now" to developers; Proving Grounds actually tests a flagged candidate, a human judgment call decides what's worth testing at all (file 02 rule #8's own explicit statement).
- **poll uniformly** — different tracked-fact kinds need different polling mechanisms (a PyPI release feed vs. a specific GitHub issue's state), already designed as distinct in the parent document.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Polling is deliberately not uniform: a PyPI release feed, a free-threading support flag, and a specific upstream GitHub issue's open/closed state are different tracked-fact kinds needing different mechanisms. This sub-API watches, judges, delegates, interprets, and reports — it never runs the test itself; Proving Grounds does. Whether a surfaced change is program-important is a human call, deliberately not automated from a changelog diff.
