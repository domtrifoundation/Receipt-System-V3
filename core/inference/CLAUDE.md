# Inference (LLM) API

Inference API's job, per file 01's existing framing: **parser/corroborator, not decision-maker.** Concretely, given a prompt (optionally with images, optionally with a tool manifest, optionally with a required output schema), run generation on a loaded model and hand back the result.

## API version at x03.00.00 Zircon

`a03.00.00`

`MM` is this API's real generation count, determined against actual V1 and V2 source rather
than asserted (`docs/MAINTENANCE.md` §1). Third generation. V1 *was* a vision-model receipt reader — reading the image and returning vendor/date/total/notes was the whole of it. V2 rebuilt that as a local LLM stack (`backend_onnx.py`, `llm_worker.py`, `llm_vision.py`, the deprecated `backend_llamacpp.py`). The `.00.00` tail matches the same
deliberate-jump discipline `x03.00.00` itself follows: Zircon is the first stable release of
this generation, not a running total of the commits that got there. `MM` increments again on
any subsequent breaking change to this API within V3's lifetime.

## Current API version

`a03.00.04`

The **running** value, distinct from the Zircon target above. The target states where this
API lands when `x03.00.00` ships; this states where it actually is today. It ticks its `pp`
in the same commit as any change to this API's own behaviour, alongside the program's own
`pp` in `common/version.py` — see `CONTRIBUTING.md`'s versioning section for the standing
practice and why both move together.

## Full design

**During development (deep-dive corpus still present)**: [`docs/apis/v3-deepdive-02-inference-api.md`](../../docs/apis/v3-deepdive-02-inference-api.md) —
read this before making any non-trivial change. This file is a working summary, not a
replacement for it.

**Before x03.00.00 ships** (`docs/CLAUDE_MD_GUIDE.md` §2.1): this section gets rewritten to a
self-contained summary plus a pointer to `contracts.py`/`service.py` as the living source of
truth. The deep-dive corpus does not ship with the program — the pointer above stops being
valid the moment it is removed, and this file is what future sessions will have instead.

## What this API explicitly does NOT own

- **own what tools exist or dispatch them** — that's the separate Tool Call API (file 01, #11). Inference API receives a tool *manifest* as part of a request (a shape Tool Call API defines), builds the right constrained-decoding grammar from it, and returns which tool the model chose to call with what arguments — it never executes a tool itself.
- **decide agent-loop policy** — how many rounds a tool-calling loop gets, when to give up and fall back to deterministic logic, when a result is "good enough" to stop asking for more corroboration. That's orchestration logic living in whatever caller is running the loop (a background worker, the receipt pipeline, a chat handler), exactly the same boundary OCR API drew for "should this receipt get a second opinion."
- **decide what's true** — if OCR API and Inference API's vision pass disagree about a receipt's vendor, Inference API doesn't adjudicate that; it reports what it saw, same as every OCR engine reports its own reading and leaves merging to whoever asked.

## Forward-Compatibility Pattern applicability

Yes. This folder's contracts are `@dataclass(frozen=True)` with dict-typed fields, so they use `common/frozen_dict.py`'s `FrozenDict` rather than a plain `dict` (`docs/PRINCIPLES.md` §2.1). Any `isinstance` check against one must test `collections.abc.Mapping`, never `dict` — the 3.15 builtin is not a `dict` subclass. Module-level lookup tables in this folder are `FrozenDict` too, per §2.1.1.

## Real gotchas specific to this folder

`PresetWorker` is a handle to a real `multiprocessing.Process`, not a thread — corrected in `docs/PROCESS_TOPOLOGY.md` §5 after the original design was isolated in name only. The `og.Model`/`og.Generator` objects live entirely in that child process; this service's own process never imports `onnxruntime_genai`'s native bindings. Preserve that: a crash in generation must stay contained to one preset's worker. Lazy model loading also needs its own lock, separate from the generation lock, or two concurrent first-calls race.

- **`backends/onnx_genai_backend.py` is built from `onnxruntime-genai`'s own published API
  and release notes, not verified end-to-end against real model weights this session.**
  Downloading a real model directory (multi-GB) is one of this project's own "ask the user
  first" actions and there was no need to for what this package's own concurrency design
  actually required proving. Say this plainly rather than implying parity with
  Preprocessing's/OCR's own live-hardware-validated engines — `build_prompt()`'s chat
  template is explicitly a placeholder (no real per-model-family template verified),
  and `set_guidance()`'s exact signature is taken from the library's own examples, unverified.
- **Everything that *is* live-confirmed this session, without needing model weights**: the
  real `multiprocessing.Process`/`Queue` mechanics — worker startup and the load-status
  handshake, the micro-batch drain loop (`batching.py`), per-request response routing via
  a single dedicated reader task (never N racing consumers on one shared queue), an
  in-generate exception staying contained to the worker (worker survives, next call still
  works), and a hard `Process.kill()` correctly failing every pending caller with
  `WorkerUnavailable` rather than hanging forever. `test_generation.py` exercises all of
  this against `tests/unit/core/inference/fakes.py`'s own module-level fake backend — a
  closure could not have survived being pickled to the child process under Windows's
  `spawn` start method (confirmed directly during Preprocessing API's own development).
- **The §6.2 lazy-load-locking race is a real regression test, not just design
  reasoning** (`test_model_registry.py`): ten concurrent `get_worker()` calls for an
  unloaded preset result in exactly one `load()` call, verified against a fake worker
  with an artificial load delay to widen the race window.
- **`InferenceModelRegistry`'s per-request model-directory resolution is deliberately
  simple** — a plain `os.path.join(models_dir, preset_name)`, never the live Hugging Face
  variant lookup `presets.resolve_variant_path()` performs. That live lookup is a one-time
  provisioning step (Setup/Update API's own territory), never re-derived on every
  `generate()` call, and was never actually invoked this session (no network call made).
- **`PresetWorker`/`InferenceModelRegistry` both take a `backend_factory`/`worker_factory`
  seam** — the same shape as Preprocessing API's own `blob_store_factory`: a plain,
  picklable, zero-argument callable, defaulting to the real implementation, overridable
  by tests so the real concurrency mechanics can be proven without real model weights.
- **§8's execution-provider selection was completely missing from the first pass of this
  package — `load()` called plain `og.Model(model_dir)` with the `device` argument
  accepted and stored but never actually used to select anything.** Fixed:
  `backends/onnx_genai_backend.py`'s `load()` now builds an `og.Config`, calls
  `clear_providers()`/`append_provider(name)` for a real non-CPU device, and only then
  constructs `og.Model(config)` — the documented mechanism from `onnxruntime-genai`'s own
  example scripts. Confidence varies genuinely by provider: high for `cuda`/`dml`, medium
  for `rocm`/`qnn`, low for `openvino`/`tensorrt` (this session could not confirm the
  exact provider-name string either of the last two expects) — see the module's own
  docstring for the full per-provider breakdown, not glossed over as uniformly solid.
  Session-level settings from §8.2 (IOBinding, CUDA graph capture, memory arena tuning,
  `intra_op`/`inter_op` thread counts) are genuinely **not implemented** — current
  `onnxruntime-genai` controls most of these through `genai_config.json`'s own schema
  inside the model directory, not a separate Python session-options object, and
  confirming the exact JSON keys needs a real model directory this session doesn't have.
- **§8.6's Health API VRAM reservation integration was also completely missing from the
  first pass — a real, complete gap, not a documented placeholder.**
  `core/health/resource_ledger.py`'s own module docstring names Inference explicitly as
  one of three APIs promised this integration; none of the three had it until this was
  caught and fixed. `InferenceModelRegistry._default_worker` now calls Health API
  (`health_client.py`) before ever handing a non-`"cpu"` device to a `PresetWorker` —
  confirmed live, both directions, against a real running Health service: with no
  `HardwareProfile` published (Setup API doesn't exist yet), the reservation is rejected
  (`UNKNOWN_DEVICE`) and the worker loads on `"cpu"` instead; against a real
  `StaticHardwareProfile`, the reservation is genuinely granted and the worker loads on
  the requested device. Each preset's `estimated_vram_mb` (`presets.py`) is a reasoned
  placeholder pending real bench measurement, the same posture as every other
  unmeasured constant in this project. Reservations are released on
  `InferenceModelRegistry.shutdown()`; there is no periodic refresh against Health's own
  TTL (`resource_ledger.py` §5.2) for a worker that stays loaded longer than the TTL —
  flagged, not silently assumed permanent, same caveat OCR's own engines carry now.
- **Three more real, complete gaps found only when directly asked "is every deep-dive
  detail actually implemented" — not caught by this session's own review before that.**
  All three follow the identical shape: a field or parameter existed, and nothing ever
  read it.
  1. **`vision.py`'s resolved image bytes were computed, threaded into `_WorkerJob.
     images`, carried across the process boundary, and then silently dropped** —
     `backend.generate()` had no `images` parameter at all. Fixed: `InferenceBackend.
     generate()` now accepts `images`/`reasoning_marker`/`reasoning_token_budget`;
     `OnnxGenAiBackend._run_one_pass()` branches to `og.MultiModalProcessor`/`og.Images.
     open_bytes()` when images are present (a genuinely different input path from plain
     `tokenizer.encode()`, not an optional extra parameter) — unverified against real
     vision weights, same honesty posture as every other unverified `og.*` call in this
     module. Confirmed live through the real multiprocessing pipeline (not the real
     model) that images now genuinely reach `backend.generate()`
     (`test_images_reach_the_backend_through_the_real_worker_process`).
  2. **`reasoning_token_budget` was a real `InferenceConfig` field read by nothing.**
     Fixed: `presets.py` gained a `reasoning_marker` per-preset field (`None` on both
     presets shipped today, matching §12's "non-reasoning instruct presets only, by
     default" resolution), and `OnnxGenAiBackend.generate()` now runs a real two-call
     thinking-then-answer sequence when a preset's marker is set — free generation up to
     `reasoning_token_budget` or until the marker is seen, then a second call continuing
     into the schema-constrained answer. Confirmed live that the parameters genuinely
     cross the process boundary; the real phase-switch *logic* itself is unverified (no
     reasoning-tuned preset exists to test against) and the module docstring says so.
  3. **`max_concurrent_generations` (§10's own "queue depth cap before backpressure, per
     preset") did not exist anywhere in the code at all.** Fixed: `PresetWorker.submit()`
     now acquires a real `asyncio.Semaphore(max_concurrent_generations)` around the
     dispatch-and-await-response span (created in `load()`, bound to the right event
     loop) — the (N+1)th concurrent caller genuinely waits for a free slot. Confirmed
     live with a real timing measurement: 6 concurrent requests at a cap of 2 against a
     deliberately slow fake backend took ~3x one request's own delay, not ~1x — real
     serialization, not a cap value accepted and ignored
     (`test_max_concurrent_generations_creates_real_backpressure`).
  4. **`default_preset`/`vision_preset` were both declared in `InferenceConfig` and read
     by nothing.** `default_preset` is now real: an empty `GenerationRequest.preset`
     resolves to it in `generate()` rather than failing as unconfigured.
     `vision_preset` is deliberately left unread by this module's own runtime — §1's own
     "caller's choice, not policy" principle means Inference must not auto-substitute a
     vision-capable preset just because a request happens to carry image content; this
     value exists for *other* callers (Execution Core, Interface API's settings menu) to
     read, not for this API to enforce on itself. Stated explicitly in the config
     dataclass's own docstring so it isn't mistaken for a missed wiring later.
  5. **Provider *options* (`config.set_provider_option(...)`) were described in this
     file's own earlier revision as "attempted... below" and were not actually
     implemented anywhere** — a docstring claim the code didn't back up, caught by
     grepping for the call it claimed existed. Now real: `_provider_options()` sets
     CUDA's `device_id` and, per §8.1's own explicit "mandatory, not optional"
     requirement, TensorRT's engine-cache enable flag and cache path (uncached TensorRT
     rebuilds its engine from scratch on every session creation).
  6. **`InferenceMetrics.truncation_retry_count` was declared and structurally could
     never be incremented** — the retry decision (`_generate_with_retry`) happens
     entirely inside a `PresetWorker`'s own child process, while the metrics collector
     lives in the parent (`InferenceModelRegistry`); the signal was computed and then
     discarded at the call site (`output, _retried = ...`), never crossing the process
     boundary at all. Fixed: `_WorkerResponse` (the internal message crossing
     `response_queue`) now carries `retried: bool`; `PresetWorker.submit()` gained an
     optional `on_retry` callback invoked only when this specific request actually
     retried; `InferenceModelRegistry.generate()` passes one that increments the real
     metric. Confirmed live through the real multiprocessing pipeline: `on_retry` fires
     exactly once for a request that truncates and retries, not at all for one that
     completes normally (`test_on_retry_fires_only_when_a_real_retry_happened`).

## Implementation status

Implemented this session — `contracts.py`, `errors.py`, `backends/` (Protocol + the one
`onnxruntime-genai` backend, unverified against real weights per the gotcha above),
`model_registry.py`, `presets.py`, `generation.py`, `batching.py`, `structured_output.py`,
`tool_calling.py`, `vision.py`, `metrics.py`, `service.py` + `inference.proto`. 33 tests,
all passing.
