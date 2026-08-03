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

`a02.00.01`

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

**Not applicable to `FrozenDict` specifically** — corrected from a stale generic "Yes"
copied at scaffold time. None of this package's contracts (`contracts.py`) hold a
dict-typed field; every collection here is a `tuple`/`frozenset` (`EngineReading.regions`,
`OcrRequest.engines`, etc.), so there is no plain-`dict` field for `common/frozen_dict.py`'s
`FrozenDict` to replace. If a future field genuinely needs a mapping shape, it must use
`FrozenDict` at that point, per `docs/PRINCIPLES.md` §2.1 — this section should flip back
to "Yes" in the same commit that adds it, not be left stale again.

The Forward-Compatibility Pattern still applies to this package in the other sense that
matters here: every heavy native dependency (`opencv-python`, `pymupdf`,
`rapidocr-onnxruntime`, `numpy`) is feature-detected via `pytest.importorskip` in this
package's own tests rather than assumed installed, since none of them have a 3.15 wheel
yet (`docs/PRINCIPLES.md` §3.3) — see "Real gotchas" below.

## Real gotchas specific to this folder

Every engine binding is imported *inside* its own engine module and lazily (`docs/PRINCIPLES.md` §3.3 point 5) — a missing engine dependency degrades that engine to unavailable, it never fails the run (§4.4). Nothing outside `core/ocr/` imports from `engines/` directly; `contracts.py` is the only entry point other APIs use.

- **RapidOCR's and PaddleOCR's own wrapper objects are cached, lazily-constructed
  module-level singletons, not built fresh per call.** Confirmed live: constructing
  `RapidOCR()` itself is cheap (~0.5s), but the *first* inference call on a fresh instance
  pays a real one-time model-load cost (~13s on the development machine) — a warm, reused
  instance's steady-state inference is ~5s instead. Rebuilding per call was the original
  implementation and made a real end-to-end registry test time out against the default
  15-second per-engine budget, not a hypothetical concern. `rapidocr_engine.py`'s
  `_get_rapidocr_instance()` and `paddleocr_engine.py`'s `_get_paddleocr_instance()` guard
  first construction with a `threading.Lock` since `loop.run_in_executor`'s default pool
  runs multiple worker threads concurrently.
- **`tesseract` is a system binary, not pip-installable, and this adapter shells out to it
  directly via `asyncio.create_subprocess_exec` rather than going through `pytesseract`'s
  own high-level `image_to_string`.** The reason is `OMP_THREAD_LIMIT` scoping (§4.2):
  capping each Tesseract subprocess to one OpenMP thread must be scoped to that one
  subprocess's own environment, never mutated process-wide (that would race against
  concurrent calls and cripple any other OpenMP consumer sharing this process). `asyncio`'s
  own `env=` argument on subprocess spawn gives each call an independent environment dict
  for free; `pytesseract` stays a declared dependency for exactly one thing —
  `get_tesseract_version()` as the availability probe.
- **Windows OCR's `regions` field stays empty on purpose, not because
  `Windows.Media.Ocr` lacks word-level bounding boxes — it doesn't** (confirmed live: the
  WinRT API returns real per-word boxes). The deep-dive's own §4.3 decision classifies
  Windows OCR as plain-text-only by design, alongside the cloud tier and tier-0
  text-layer extraction, and this adapter matches that documented classification rather
  than the underlying OS API's actual capability.
- **RapidOCR's and PaddleOCR's own result shape is a four-corner-point quad box, not an
  axis-aligned rect** — `engines/base.py`'s shared `quad_to_region()` reduces it to
  `TextRegion`'s normalized `(x, y, w, h)`, and `decode_image_dims()` supplies the pixel
  dimensions both engines need to normalize against (neither engine's own wrapper reports
  image size itself).
- **Apple Vision's adapter is unverified against real macOS hardware** — this development
  machine is Windows, so only the platform gate itself (`OcrEnginePlatformUnsupported`)
  is exercised for real here; the `Vision`/`Quartz` call path inside the macOS branch has
  not been run on real hardware this session.
- **`opencv-python`, `pymupdf`, `rapidocr-onnxruntime`, and `numpy` have no prebuilt wheel
  for Python 3.15 yet** (still beta as of this writing) — the same gap Preprocessing API's
  own `CLAUDE.md` documents, for the same reason. `PaddleOCR`/`boto3` are simply not
  installed in this development environment at all (heaviest local engine and a cloud SDK,
  both genuinely opt-in) — their adapters degrade to unavailable, a real, live-confirmed
  outcome rather than a gap in what got tested.
