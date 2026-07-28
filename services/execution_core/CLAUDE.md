# Execution Core API

Execution Core owns the **run** — the actual pipeline "running loop": scheduling (per-user/global concurrency limits), sequencing (Ingestion → Preprocessing → OCR → Matching → Geo → Inference → Persistence write → Review/Flagging on low-confidence → Notifications on completion), and applying the active tier profile's knobs to a given run.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had the pipeline loop, just never named as an API — `main.py`'s `daemon_loop`/`run_once` plus `processor.py`. Formalizing it is the change; the function existed. No V1 equivalent. The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-10-execution-core-api.md`](../../docs/apis/v3-deepdive-10-execution-core-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **launch processes** — that's the Supervisor's job (file 01 #21), a structurally separate, more conservative component that exists precisely so the thing deciding "should Execution Core's own release be swapped" is never Execution Core itself.
- **implement any pipeline stage's own logic** — Execution Core calls OCR/Preprocessing/Inference/etc.'s own gRPC contracts; it never reimplements a fragment of what any of them do internally.
- **decide UI/interaction concerns** — V2's `daemon_loop` literally instantiated the menu system, keyboard listener, and dashboard inside the same loop that ran the pipeline; V3's process separation makes that coupling structurally impossible to reintroduce, since Interface only ever reaches Execution Core through its gRPC contract.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

V2's `daemon_loop` instantiated the menu system, keyboard listener, and dashboard inside the same loop that ran the pipeline, so one crash anywhere took down everything. Process separation makes that impossible to reintroduce by construction — Interface only ever reaches this API through its gRPC contract (`docs/PRINCIPLES.md` §1.7). Per-stage checkpointing is what makes retries resumable and what emits Historian's narrative track; a stage added without it is a stage with no story and no resume point.
