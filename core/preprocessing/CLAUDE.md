# Preprocessing API

Preprocessing API's job: given a single ingested file (a PDF page or an image), produce a **rasterized base image**, and on request, one or more **processed variants** of it for OCR API to read.

## API version at x03.00.00 Zircon

`a02.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). V2 generated real OCR variants — `extractor.py`'s `_preprocess_for_ocr`, the `standard` / `bw_threshold` / multispectral variant set. V1 did no image transformation of any kind. The `.00.00` tail matches the same
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

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-03-preprocessing-api.md`](../../docs/apis/v3-deepdive-03-preprocessing-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **decide which variants a weak OCR reading needs** — same boundary OCR API drew for "should this receipt get a second opinion." That policy (is the standard variant good enough, or does this receipt need the full sweep) lives in the orchestrator, not in Preprocessing API.
- **read or interpret image content** — that's entirely OCR API's job; Preprocessing only transforms pixels, never looks at what they say.
- **decide OCR accuracy** — Preprocessing doesn't know or care whether a variant it produced actually helped a downstream OCR reading; that feedback loop (which variant kinds are worth generating by default) is a bench-measured, config-driven decision fed back from outside this API, not something Preprocessing evaluates itself.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

Variant generation runs in a `ProcessPoolExecutor`, not threads, because OpenCV's free-threaded wheels are not ready (tracked upstream at `opencv/opencv#27933`). That is a tracked dependency fact, not a permanent choice — when the blocker clears, this is one of the first places to revisit. The child processes are private to this service and invisible to gRPC (`docs/PROCESS_TOPOLOGY.md` §4).

## Implementation status

**Not implemented.** Every `.py` file in this folder is a 0-byte scaffold created by the Phase-1
commit that laid out the repository, and no commit since has put a line of logic into any of
them. Everything above this section describes the design this package will have, not code that
exists — a distinction worth stating in the one file a future session is most likely to read
first, because the folder's file list looks exactly like an implemented package from the
outside.

Nothing outside this folder imports from it yet, so the emptiness is inert rather than a broken
dependency. Building it is a full Core API pass against the deep-dive linked above, with the
`new_core_api` and `new_provider` templates in `docs/templates/`. **Delete this section in the
commit that implements the package** — a stale "not implemented" note is worse than none.
