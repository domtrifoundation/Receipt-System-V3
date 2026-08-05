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

`a02.00.05`

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
- **`opencv-python`, `pymupdf`, and `numpy` have no prebuilt wheel for Python 3.15 yet**
  (still beta as of this writing) — the same gap Preprocessing API's own `CLAUDE.md`
  documents, for the same reason. `PaddleOCR`/`boto3` are simply not installed in this
  development environment at all (heaviest local engine and a cloud SDK, both genuinely
  opt-in) — their adapters degrade to unavailable, a real, live-confirmed outcome rather
  than a gap in what got tested.
- **`rapidocr-onnxruntime` is a real, separate, worse gap than the note above — confirmed
  live against a real install, not assumed from a changelog.** It has no published version
  supporting Python **3.13 or later at all** — every release through 1.4.4 caps at
  `Requires-Python >=3.6,<3.13`. This was live-confirmed the hard way: a real `setup.bat`
  run on this Python-3.14 development machine deterministically failed venv provisioning
  for this whole service, which failed the entire install's `finalize_clone()` — one
  optional engine's own missing wheel blocking the whole program from ever finishing
  setup, directly contradicting this file's own header comment's promise that a missing
  OCR dependency degrades gracefully. `core/ocr/requirements.txt` now marks this package
  `; python_version < '3.13'` so pip skips attempting it entirely past that point, instead
  of failing the venv — RapidOCR correctly reports unavailable at runtime on 3.13+, the
  rest of OCR's engines are unaffected.
- **A second, real, live-found install-blocker in the same file, same live-tested
  `setup.bat` run: `winsdk>=1.0` matches nothing.** `winsdk` has never published a stable
  `1.0` — only pre-releases (`1.0.0b1` through `b10` as of this writing) — and pip's
  default resolver excludes pre-releases unless the version specifier itself names one
  (PEP 440). Fixed to `winsdk>=1.0.0b1`. After both fixes, a full repo-wide sweep
  (`pip install --dry-run -r <file>` against every `requirements.txt` in this repo under
  the real Python 3.14 interpreter) found no further broken pins — this pass, not assumed.
- **RapidOCR's own wrapper (`rapidocr_onnxruntime`, this installed version, checked by
  reading its actual source rather than assumed) does NOT expose the deep-dive's full
  §5.1 execution-provider list at all — only a single boolean `use_cuda` flag.**
  `OrtInferSession` (`rapidocr_onnxruntime/utils.py`) hardcodes
  `[CUDAExecutionProvider, CPUExecutionProvider]` gated on that one flag; there is no
  `providers=[...]` passthrough for OpenVINO/DirectML/QNN/MIGraphX in this wrapper at all.
  Confirmed live: passing `det_use_cuda=True` without also passing `det_model_path=None`
  raises a bare `KeyError` in this version — an undocumented quirk, not something
  reasoned about from the outside. `use_cuda` is the one real lever this wrapper gives,
  and it is now wired through (see the Health API point below) — the rest of §5.1's list
  simply isn't reachable through this dependency as it exists today.
- **PaddleOCR's GPU device kwarg is unverified** — its constructor's own GPU-selection
  kwarg has genuinely changed across major releases (`use_gpu: bool` vs. the newer
  PaddleX-based `device: "gpu"|"cpu"`), and PaddlePaddle is not installed here to check
  which one a real install needs. `use_gpu` is used as the more broadly-applicable
  choice today, flagged rather than asserted with false confidence.
- **RapidOCR/PaddleOCR now call Health API's live VRAM reservation ledger
  (`health_client.py`, deep-dive §5.6) before ever requesting a GPU device — this was a
  real, complete gap in the first implementation, not a documented placeholder.**
  `core/health/resource_ledger.py`'s own module docstring names OCR explicitly as one of
  three APIs promised this integration; it was built for none of them in the initial
  pass and had to be added afterward. Confirmed live, both directions, against a real
  running Health service: with no `HardwareProfile` published (Setup API doesn't exist
  yet), every reservation attempt correctly comes back `UNKNOWN_DEVICE` and the engine
  falls back to CPU; against a real `StaticHardwareProfile`, a reservation is genuinely
  granted and the engine stays on GPU. The resolved device decision is cached per engine
  instance (not re-reserved every `read()` call) — a genuine Health API round trip on
  every single OCR call would be real, avoidable overhead. Reservations are not
  refreshed via Health's own TTL mechanism (`resource_ledger.py` §5.2) — a long-lived
  engine singleton's reservation will lapse on Health's own sweep unless a periodic
  refresh is added later; flagged here rather than silently assumed permanent.
- **Two more real, complete gaps found only when directly asked "is every deep-dive
  detail actually implemented" — the same audit that caught Inference's own gaps of the
  identical shape.**
  1. **`OcrConfig.per_engine_timeout_ms` (§6) was declared and read by nothing** —
     `OcrRequest.timeout_ms` (the caller's own per-request value) was silently the only
     timeout that ever applied, regardless of what an operator configured. Fixed:
     `OcrEngineRegistry.run()` now takes `min(request.timeout_ms, config.
     per_engine_timeout_ms)` as the effective timeout — the configured value is a real
     ceiling a caller cannot exceed, not a duplicate default. Confirmed with a real test:
     a request asking for 10s against a 50ms-configured ceiling still times out at 50ms
     (`test_per_engine_timeout_ms_config_is_a_ceiling_a_caller_cannot_exceed`).
  2. **`CloudEngineConfig.timeout_seconds` was applied by `google_vision.py`'s and
     `azure_doc_intelligence.py`'s own `httpx` clients, but never threaded into
     `aws_textract.py`'s `boto3` client at all** — a hung Textract call would only ever
     hit boto3's own unrelated default socket timeouts, never this engine's configured
     budget. Fixed: `_run_textract()` now passes a real `botocore.config.Config
     (connect_timeout=..., read_timeout=...)` built from `config.timeout_seconds`.
