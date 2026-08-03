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

`a02.00.01`

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

- **Closures cannot be pickled**, and Windows's `spawn` start method needs every object crossing
  the process boundary to be importable by reference (`pickle.dumps` on a local function raises
  `PicklingError: Can't pickle local object` — confirmed directly). `generation.py`'s
  `_run_one_variant` is therefore a module-level function, never a closure, and each worker
  reconstructs its own `VariantRegistry` from a plain, picklable `PreprocessingConfig` rather
  than receiving a live registry object or a blob-store connection from the parent — the parent
  hands over a zero-argument `blob_store_factory` instead, which each worker calls itself.
- **`cv2.UMat` (the OpenCL Transparent API) has no `.ndim`, `.shape`, or any introspection
  attribute at all.** `variants/base.py`'s `to_gray()`/`get_shape()` exist specifically to paper
  over this: `get_shape()` special-cases `isinstance(image, cv2.UMat)` and calls `.get()` to pull
  the array back to CPU only for the shape read, and `to_gray()` catches the `cv2.error` a
  UMat-unaware call raises. Any new variant that touches shape/ndim directly instead of going
  through these helpers will pass its CPU-array tests and then fail silently (or raise) the
  moment `hardware.py` routes it through OpenCL.
- **`np.percentile` cannot operate on a `cv2.UMat` at all** (confirmed via a direct `TypeError`).
  `tonal_variants.py`'s `standard()` explicitly `.get()`s back to CPU before its percentile math
  — a genuine, permanent limitation of that one variant, not a bug to route around elsewhere.
  `fastNlMeansDenoising` and `findContours`, by contrast, both genuinely run on UMat directly —
  don't assume every OpenCV call needs the same CPU round-trip without checking.
- **`cv2.split()` on an already-2D (single-channel) array returns a 1-element tuple, not an
  exception.** `channel_variants.py`'s `channel_boost_factory` checks `len(channels) == 1`
  explicitly rather than relying on a `cv2.error` that never comes.
- **`opencv-python` and `pymupdf` have no prebuilt wheel for Python 3.15 yet** (still beta as of
  this writing), so they are deliberately absent from `noxfile.py`'s `FORWARD_COMPAT_DEPS` list —
  adding them there would just fail the same from-source build every other install attempt does.
  `tests/unit/core/preprocessing/conftest.py` guards its own `cv2`/`fitz`/`numpy` imports with
  `pytest.importorskip` instead, the same collection-time-skip pattern `core/auth`'s and
  `core/account_guardian`'s servicer tests already use for the equivalent `grpcio` gap.
- **§6.7's "register lightweight usage with Health API for visibility" is deliberately
  NOT wired in, checked against the deep-dive's own wording rather than skipped by
  oversight.** Unlike OCR's/Inference's own §5.6/§8.6 ("check in *before claiming*
  GPU resources" — a real reservation gating a real allocation, now built for both, see
  their own `CLAUDE.md` gotchas), this API's own §6.7 explicitly says Preprocessing
  "doesn't need to participate in the live reservation ledger with the same urgency" —
  UMat's OpenCL buffers are small and short-lived per-image, not a persistent multi-GB
  model load. A per-image reserve/release round trip to Health API would be real,
  disproportionate gRPC overhead against a single UMat op's own cost, and the deep-dive's
  own language is "visibility," not "gating" — a different, lighter-weight mechanism
  (a periodic usage metric push, not a reservation) than the ledger this session built
  for the other two APIs. Left as a real, named, still-open item rather than forced into
  the reservation shape it doesn't actually need.
