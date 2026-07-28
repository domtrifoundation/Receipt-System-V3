# Audit/Event Log API

This project has three genuinely different logging mechanisms, and keeping them distinct rather than merging "for simplicity" is itself the design decision worth stating clearly:
- **Logs API** — operational trace (OCR timings, LLM prompts, worker activity, errors). High-volume, gitignored, rotated, retention-policy-driven. Answers "what did the system do."
- **Persistence's Historian sub-package** — data-change trail (table/row/before-after/actor for every logical write to a user's own receipt data). Lives inside each user's own Persistence database, atomic with the write itself. Answers "how did this receipt's data get to its current state."
- **Audit/Event Log API (this document)** — privileged, security-relevant *actions*, not data changes: break-glass access grants, global vendor contribution reviews (approve/reject), config/role changes, confirmed-malicious content verdicts (Content Security's staff resolution). Answers "who did something with real security/compliance weight, and when."

## API version at x03.00.00 Zircon

`a01.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Genuinely new. V2 had no privileged-action log — its `docs/AUDITING.md` is a code-review guide for humans reading diffs, an unrelated sense of the word. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-08-audit-event-log-api.md`](../../docs/apis/v3-deepdive-08-audit-event-log-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- _(This deep-dive states its boundary as prose rather than a list; see its §1.)_

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Append-only must be a structural property of the public surface, not a convention: no `update_event()` or `delete_event()` exists anywhere, and no module hands out a raw connection object that would let someone route around it (`docs/PRINCIPLES.md` §2.3). The whole value of this log is being trustworthy in exactly the situation where someone would want to quietly alter it.
