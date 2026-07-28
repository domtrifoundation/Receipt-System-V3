# OCR API

The OCR API's job: given a **single already-selected image** (one page, one variant — a Preprocessing API output), produce **zero or more raw text readings** of it, one per enabled engine, plus a **corroborated result** when more than one reading came back.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 had real multi-engine OCR — `receipt_processor/extractor.py`'s `extract_text_<engine>` family plus the second-opinion/EXTREME engine selection. V1 had no OCR engine at all; it read receipts with a vision model, which is Inference's ancestry, not this API's. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-01-ocr-api.md`](../../docs/apis/v3-deepdive-01-ocr-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- decide which preprocessing variants exist (Preprocessing API's job — OCR just gets called once per variant it's handed)
- parse structured fields out of the text (vendor/amount/date parsing is Matching/Inference territory downstream)
- decide whether a receipt needs a second opinion at all (that policy — "is this reading weak enough to escalate" — is orchestration logic that lives in the run scheduler / Reconciliation-adjacent pipeline code, not inside this API; OCR API exposes the primitives, doesn't decide when to call itself twice)

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Every engine binding is imported *inside* its own engine module and lazily (`docs/PRINCIPLES.md` §3.3 point 5) — a missing engine dependency degrades that engine to unavailable, it never fails the run (§4.4). Nothing outside `core/ocr/` imports from `engines/` directly; `contracts.py` is the only entry point other APIs use.
