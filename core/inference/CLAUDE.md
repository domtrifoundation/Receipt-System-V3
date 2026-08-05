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

`a03.00.15`

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

**This package is now live-confirmed against real model weights, real hardware, and real
receipts — a real full-fleet concurrent-submission test's follow-up validation session,
given explicit permission to download models.** `phi4-mini` text generation and
schema-constrained structured output both work correctly end to end on CPU and DirectML
(a real Intel Arc GPU); DirectML's own first real generation call pays a one-time ~39s
JIT/shader-compilation cost (confirmed live via per-token timing — token 1 and tokens 3+
are ~0.01s, token 2 alone is ~39s), not a hang, worth knowing before assuming a stuck
DirectML load is broken. Two real `onnxruntime-genai` API-shape bugs were found and fixed
in the vision/multimodal path this same session — see `backends/onnx_genai_backend.py`'s
own module docstring for the full account (`og.MultiModalProcessor(model)` should be
`model.create_multimodal_processor()`; `GeneratorParams.set_inputs(...)` should be
`Generator.set_inputs(...)`, called after construction). After both fixes the vision path
runs without error against a real downloaded `phi4-vision`; real receipt *extraction
quality* through it is still unverified and a real, open follow-up, not solved just
because the code stopped crashing. `resolve_variant_path()` (`presets.py`) had two more
real, previously-unverified bugs of its own, also live-found and fixed this session — see
that module's own docstring. `service.py`'s `__main__` had no environment-variable seam
to point a real install at real downloaded models at all (unlike every other service with
an external resource dependency); `RESIBO_INFERENCE_MODELS_DIR`/
`RESIBO_INFERENCE_PRESETS_ENABLED`/`RESIBO_INFERENCE_DEVICE` close that gap.

**The "model manager"/"EP manager"/"downloader" gap identified by a direct follow-up
audit ("is any of the operational layer around the engine actually built") is now real,
built to §4.4/§8.6's own design, not just the engine underneath it.** Confirmed missing
by that audit: `resolve_variant_path()` was called nowhere outside its own tests, no
execution-provider auto-selection existed anywhere, and the venv installer always
installed the CPU-only `onnxruntime-genai` regardless of detected hardware. Fixed across
several passes:
- **`model_provisioning.py`** — the real downloader `presets.py`'s own docstring pointed
  at without ever building. `list_remote_variant_files()`/`preset_status()`/
  `provision_preset()`, built on `services/update/proving_grounds/download.py`'s new
  resumable (`Range`-header), retrying `download_file()` — a third real caller of that
  shared infrastructure. Naturally resumable across a full process restart: every call
  re-checks real disk state before touching the network, so there is no separate resume
  token to lose. Confirmed live against the real Hugging Face Hub (11 real files/sizes
  for `phi4-mini`, matching an earlier manual download exactly) and against a real,
  already-downloaded model correctly reporting `READY`.
- **`ProvisionPreset`, a new server-streaming RPC** (`inference.proto`, matching
  Supervisor's own `StreamBootProgress` shape exactly) — real per-file, per-chunk
  progress over the wire. `ListPresets` gained an appended `preset_statuses` field;
  its one real Hub round trip per preset is cached after the first call
  (`InferenceServicer._live_status`), never a live network call per request, matching
  `model_registry.py`'s own existing "never per-request" rule for model-directory
  resolution.
- **`common/execution_provider.py`'s `select_execution_provider()`** — the real "shared
  session/EP-selection utility" §8.6 designed and never built, generic-enough to sit
  outside both this API and OCR's own domain (structural `GpuLike` typing, not an import
  of `services.setup.contracts`, matching this package's own `BlobRef`-re-declaration
  convention). Wired into `InferenceModelRegistry._device_for`: an operator's explicit
  `device_by_preset` entry still wins outright; an *unconfigured* preset now falls back
  to a real hardware-derived device when a `HardwareProfile` is published (new optional
  `hardware_profile` constructor param), `"cpu"` only when neither is available —
  existing callers (no profile passed) keep the exact prior behavior. Confirmed live:
  resolves this development machine's real Intel Arc B580 to `"directml"`.

**Manual EP selection, real and separate from auto-detection — a direct follow-up
request after the above landed ("still have manual EP selection... are ALL of the
[deep-dive's] EPs selectable and installable").** §8.6's hardware-derived default was
never meant to be the *only* way to pick a device; the operator can now see and choose
from the full real catalog, not just what auto-selection would have picked.
- **`common/execution_provider.EXECUTION_PROVIDERS`** — the full deep-dive §8.1
  vocabulary (`cpu`/`cuda`/`tensorrt`/`directml`/`openvino`/`qnn`/`migraphx`) as real,
  checkable data (device, label, confidence tier, `pip_package`, `installable`, a
  human-readable note), not scattered across docstrings. **Real, live-confirmed findings,
  not assumed from the deep-dive's prose alone** (`pip index versions` against the real
  PyPI index): `onnxruntime-genai-cuda` is real; `onnxruntime-genai-tensorrt`/`-qnn`/
  `-rocm` do **not** exist as separate wheels at all — TensorRT genuinely installs via the
  same CUDA-enabled wheel CUDA does (selected by provider name at runtime, not a separate
  package, so `installable=True` for both), while OpenVINO/QNN/MIGraphX have no prebuilt
  `onnxruntime-genai` wheel through any path (`installable=False`) — still real,
  selectable devices for *generation* (`config.append_provider(name)` doesn't require
  special provisioning, it just fails at load time if unsupported, the deep-dive's own
  "a real install failure specifically is not a surprise" honesty), just not something
  provisioning can swap a venv onto.
- **`venv_provisioning.py`'s own `_ONNXRUNTIME_GENAI_VARIANT_BY_DEVICE` now derives from
  that same table** (`{ep.device: ep.pip_package for ep in EXECUTION_PROVIDERS if ep.
  pip_package is not None}`) rather than an independently-maintained duplicate — one real
  source of truth for "which device installs which package."
- **Two new RPCs, `ListExecutionProviders`/`SetPresetDevice`** (`inference.proto`) — the
  first reports the real catalog above for the TUI to render; the second persists an
  explicit per-preset override via new `device_overrides.py`
  (`config/inference_device_overrides.json`, the same `write_hardware_profile`-shaped
  read-modify-write pattern) — **effective on the next Inference process restart, not
  live**, matching `settings_backend.py`'s own existing `takes_effect_on_restart`
  precedent for a different setting rather than building a riskier hot-swap mechanism
  this pass has no real need for. `_config_from_env()` merges a persisted override on top
  of `RESIBO_INFERENCE_DEVICE`'s own uniform-across-presets default — the more specific,
  explicitly-set-by-an-operator value wins, the identical "more specific wins" shape
  `InferenceModelRegistry._device_for` already applies between `device_by_preset` and the
  hardware-derived fallback.
- **TUI**: `ModelProvisioningScreen` gained a real device `Select` populated from
  `ListExecutionProviders` (confidence + a "no prebuilt wheel, generation-only" tag for
  the non-installable three) — pre-selects a preset's current device on selection,
  provisioning uses whatever the operator has chosen (not silently forced back to the
  auto/configured device), and a new "Set Device" button calls `SetPresetDevice` for
  real. Live-tested against a genuine running `InferenceServicer`, including every one of
  the seven real devices round-tripping through the actual `Select` widget.

**OpenVINO specifically re-checked against official documentation, not just PyPI probing,
on direct request ("did you do your research?") — and then a real, working, officially-
distributed path was found and built, on a second direct challenge ("Intel driver
installers always install a complete OpenVINO or oneAPI... check")**. Both challenges
led somewhere real, not just more caveats:

1. No pip-only path exists. Microsoft's own install docs (`onnxruntime.ai/docs/genai/
   howto/install`) list exactly four pip variants for `onnxruntime-genai` — bare CPU,
   `-directml`, `-cuda` (CUDA 12), and CUDA 11 via source build — no OpenVINO or QNN
   variant. The official build-from-source page documents only `--use_dml`/
   `--use_trt_rtx`/`--use_cuda`, no `--use_openvino` flag.
2. The user's instinct that a real runtime "comes with the drivers" was directionally
   right, just not via the GPU driver itself: live-checked, Intel's Arc B580 driver only
   bundles an NPU *compiler* DLL (`npu.inf`'s own `openvino_intel_npu_compiler.dll`), not
   a full runtime — but a bare `pip install openvino` (no separate toolkit installer, no
   `setupvars.bat`) genuinely detects CPU/iGPU/dGPU/NPU on this machine via `ov.Core().
   available_devices`, live-confirmed.
3. The user's separate correction that WinML is DirectML's real successor (like TensorRT
   is to CUDA) is also confirmed by Microsoft's own docs (`learn.microsoft.com/windows/
   ai/new-windows-ml`) — and following that thread found the actual official distribution
   mechanism: Windows ML's own `ExecutionProviderCatalog` publishes real OpenVINO/QNN/
   MIGraphX/NvTensorRtRtx EP plugin packages. Its own Python API (a real, installable pip
   package, `wasdk-Microsoft.Windows.AI.MachineLearning`) fails immediately when called
   from this project's own unpackaged venv processes: `OSError: The process has no
   package identity` — a genuine MSIX requirement, not a bug on this project's side.
4. **The real distribution channel underneath that catalog is plain NuGet — no MSIX
   needed at all.** A NuGet package is nothing more than a downloadable zip. Live-tested
   end to end: downloaded `Intel.ML.OnnxRuntime.EP.OpenVINO` 1.6.1 (121 MB, via a plain
   HTTPS GET, no auth), extracted `onnxruntime_providers_openvino_plugin.dll`, called
   `onnxruntime_genai.register_execution_provider_library("OpenVINOExecutionProvider",
   dll_path)` — it succeeded. (A second call for the same provider name correctly raises
   `RuntimeError: library is already registered` — a real native-layer idempotency
   constraint `ep_plugins.py`'s own `_registered_providers` cache exists to respect.)

**Built, not just documented — `core/inference/ep_plugins.py` is the real mechanism.**
`EP_PLUGIN_SPECS` carries the real NuGet coordinates for `openvino` (live-confirmed
end to end) and `qnn` (`Microsoft.ML.OnnxRuntime.QNN` — real package, downloaded and
inspected, but **not** live-loaded: no Qualcomm/Snapdragon hardware on this machine, and
live-checked, the package ships only a `runtimes/win-arm64/` native build — genuinely
uninstallable on any x64 host, since Snapdragon's Hexagon NPU is ARM64-only hardware, not
just unverified). `migraphx`/`tensorrt`'s own NuGet packages weren't found under the
expected names when checked live — not confirmed absent entirely, just not identified.
`ensure_ep_plugin()` (async, reuses Phase A's resumable `download_file()`) is called from
`venv_provisioning.py` during provisioning — never from the generation path, matching
`model_registry.py`'s own "per-request generation must never make a network call" rule.
`register_ep_plugin()` (sync, no network) is called from `onnx_genai_backend.py`'s own
`load()`, threaded through `install_root` (new optional param on `PresetWorker`/
`InferenceModelRegistry`/`InferenceServicer`, plumbed all the way from `service.py`'s own
`__main__`, and across the real `multiprocessing.Process` boundary `_worker_main` runs
behind under `spawn`). `common/execution_provider.py`'s `ExecutionProviderInfo` gained a
`nuget_package` field alongside `pip_package` — `installable` is now true for either
channel; `openvino`/`qnn` flip from `installable=False` to `True`, `migraphx` stays
`False` (no channel found for it at all).

**DirectML generation timing is genuinely unstable on real hardware — a real, live-
confirmed finding, not a code bug, found while running real receipts through the full
pipeline for the first time.** The exact same `OnnxGenAiBackend.generate()` call — same
prompt, same 10-token cap, `do_sample=False` (fully deterministic) — produced byte-
identical output across four separate real runs on this machine's Arc B580, but took
1.6s, 16.5s, 85.5s, and 146.5s wall-clock respectively. Ruled out as a code bug by direct
comparison: a bare script replicating `_run_one_pass()`'s exact `og` API call sequence
(`generate_next_token()` -> `get_next_tokens()` -> `tokenizer_stream.decode()`) was
sometimes fast, sometimes exactly as slow as the real backend class — same code, same
inputs, wildly different wall-clock cost. The leading candidate is real DirectML/driver-
level resource pressure (GPU memory not fully released between repeated model
load/unload cycles across separate processes within one session, plausible given the
model is 3.4GB and this machine ran five-plus separate real loads in quick succession
during this diagnosis) — not confirmed with full certainty, flagged honestly as the
leading hypothesis rather than a proven root cause. **Practical fix applied**:
`services/execution_core/gateways.py`'s `GrpcInferenceGateway.generate()` now defaults
`timeout_ms` to 300000 (5 minutes) instead of `InferenceConfig`'s own 30-second default —
a real, correct generation must not fail outright just because this specific hardware's
worst-case observed latency is ~150s. IOBinding (§8.2, still genuinely unimplemented) was
the first suspect and is ruled out as the *sole* cause by this same evidence — it may
still be worth implementing for raw throughput, but it would not explain a 90x variance
between two runs of the identical code.

**Follow-up same session: neither real GPU path actually works for this preset on this
hardware — a clean, complete, real comparison, not a partial one.** Direct testing of
`device_id`/hardware-ID GPU targeting for DirectML made things *worse* (28.6s/token
explicitly targeting the Arc B580 by its real `OrtHardwareDevice` id/vendor_id, ruling out
"wrong adapter" as the explanation). A clean CPU-only control run was fast and perfectly
linear — 0.092s/token, zero variance across all 10 tokens — isolating the instability to
DirectML specifically, not general system contention. OpenVINO's GPU path was tried next
(the real NuGet-distributed plugin built earlier this session, `ep_plugins.py`) and found
to **silently fail to compile for GPU/NPU and fall back to CPU internally**:
`device_type=GPU` produced `IE::FrontEnd::importNetwork` "Upper bounds are not specified"
errors across all 32 transformer layers, and the loaded model's own `device_type` property
reported `"CPU"` regardless of the `GPU` request — no exception, no error surfaced to the
caller, just a silent downgrade. Root cause: this project's Microsoft-exported int4 ONNX
models use fully dynamic sequence-length shapes, which OpenVINO's CPU plugin tolerates but
its GPU/NPU compiler cannot. OpenVINO's own CPU execution, however, was both fast *and*
stable — 0.047-0.051s/token, marginally faster than plain ONNX Runtime CPU (0.092s/token)
and dramatically more reliable than DirectML. **`_provider_options()` now defaults
`OpenVINOExecutionProvider` to `device_type=CPU`** for exactly this reason — not a
cautious fallback, the actual best real result found. Net, honest conclusion: on this
machine, for this preset, **no GPU acceleration path currently works** — CPU (plain, or
via the OpenVINO EP) is the only fast, stable option tonight. This is a real, unresolved
hardware/driver-level limitation (Intel Arc DirectML driver instability; this ONNX
export's dynamic shapes being GPU/NPU-incompatible for OpenVINO), not a gap in this
package's own code — both EP integrations load, register, and generate correctly; they
simply cannot get real acceleration out of this specific hardware for this specific model
export tonight. Real follow-up, not done here: a statically-shaped model export (Model
Builder can target this) might unlock OpenVINO's GPU/NPU compiler; DirectML's own
instability needs either a driver update or an upstream Intel/Microsoft bug report to
actually resolve.

**§8.2's `intra_op_num_threads`/`inter_op_num_threads` are real now — found and fixed
the same session, directly connected to the finding above.** Running real receipts
through the full `SubmitReceipt` pipeline (Execution Core's own real six-stage flow)
concurrently exercises Inference *and* OCR on the same machine, and an unbounded ONNX
Runtime session claiming every core genuinely starved OCR for the same threads — a real,
observed cause of some of Phase 1's own real timeout failures (`services/execution_core/
CLAUDE.md`), not just DirectML/OpenVINO-GPU's own separate instability. `og.Config` has
no dedicated thread-count setter, but `overlay()` (confirmed live: accepts a JSON string
merged into the exact same schema `genai_config.json` itself uses) does —
`onnx_genai_backend.py`'s new `_session_thread_overlay()` sets `intra_op_num_threads` and
`inter_op_num_threads=1` (this is one sequential decode loop, not a multi-branch graph —
no benefit from inter-op parallelism here). Applied to every load path, not just the
non-CPU ones — `og.Config(model_dir)` is now always constructed and overlaid before
`og.Model(config)`, replacing the old `og.Model(model_dir)` bare-string-path shortcut for
the CPU-default case, since that shortcut had no `Config` object to overlay onto at all.

**The `intra_op_num_threads` number itself was corrected the same session, from half the
detected cores to three-quarters — a real architecture finding, not a re-guess.** Real
concurrent-receipt testing (raising Execution Core's `per_user_limit` to prove genuine
pipelining, `services/execution_core/CLAUDE.md`) surfaced that `core/inference/
generation.py`'s own `_worker_main` processes its batch-drain loop with a plain `for item
in batch:` — every request for one loaded preset runs through **one single worker
process, strictly sequentially**. `max_concurrent_generations` (the semaphore gating how
many requests can be dispatched at once) was never a true parallel-compute knob; it only
bounds how many can be *queued* at the same worker. So "half the cores, to leave room for
concurrent Inference requests" was solving a contention that doesn't exist — there is
never more than one active generation drawing on this session's threads at any moment,
only ever "this one generation vs. whatever OCR is doing for a *different* receipt at the
same time." Halving the thread count measurably slowed every single request for a
concurrency benefit that was never real. Corrected to three-quarters, which still leaves
real headroom for concurrent OCR without starving the one thing actually running.

**Follow-up, same session: that "still-open question" is now answered — a real,
opt-in worker pool.** Live concurrent-receipt testing confirmed the queueing directly
(5 receipts concurrently, real per-stage timing: `geod -> inferred` alone cost
234-293s per receipt, several exceeding the generation timeout) even after the OCR
parallelization and thread-count fixes — the actual bottleneck was never thread
starvation, it was that every request for one preset shares exactly one `PresetWorker`.
`InferenceModelRegistry` now supports `InferenceConfig.worker_pool_size` (default `1`,
byte-for-byte identical behavior and test contract to every prior session — the
double-checked-locking regression test still gets exactly one load) — a value above `1`
loads that many real, independent `PresetWorker` replicas (each its own
`multiprocessing.Process`, own full model copy, own Health VRAM reservation) and
`get_worker()` round-robins across them, so concurrent requests for the same preset
genuinely run in parallel instead of queueing behind each other. Replicas load
sequentially at pool warm-up, deliberately not via `asyncio.gather` — this session's own
DirectML findings above are reason enough not to risk concurrent cold loads compounding
real EP/driver instability, and warm-up is a one-time cost, not a per-request one. Real,
live-confirmed headroom on this session's own test hardware: 95GB RAM, a 3.4GB int4
model — several replicas are affordable, not reckless, on hardware like this. **Not yet
done**: exposing `worker_pool_size` as a real, operator-facing setting (TUI/settings
surface) — real, scoped follow-up, the config field itself is the seam already built for
it. `tests/unit/core/inference/test_model_registry.py`'s own `test_worker_pool_size_*`
tests cover both the new pool behavior and the exact-original-behavior guarantee at
`worker_pool_size=1` directly.

**Follow-up, real live-found crash on the very first real fresh-install run that
exercised `warm_up()`: it let `ModelLoadFailed` propagate straight out of the process.**
An enabled-but-not-yet-provisioned preset (a completely normal, expected state — that is
what `ProvisionPreset` exists for) crashed the entire service at startup, taking every
*other* enabled preset's own warm-up down with it — exactly the one-degraded-component-
takes-down-the-run failure `docs/PRINCIPLES.md` §4.4 forbids. Fixed: `warm_up()` now
catches `ModelLoadFailed` per preset and logs to stderr rather than raising; a failing
preset stays unavailable (its first real request still raises the identical
`ModelLoadFailed` `generate()` already turns into a `GenerationResult.failure` — no new
failure mode introduced, just no longer a crashed process) while every other enabled
preset still gets its real warm-up. `test_warm_up_does_not_crash_the_process_when_one_
preset_fails_to_load` covers this directly.

**Follow-up, same session: the worker-pool fix above made a fresh process's first wave
of concurrent requests *worse*, not better — a real regression found by testing the fix
itself live, not a hypothetical.** `get_worker()`'s double-checked-locking pattern has
every concurrent caller for a preset block on the *same* `asyncio.Lock`, not just the
first one in — so on a cold process, 5 receipts submitted concurrently all raced into
that lock together and every one of them stalled behind one shared cold load of all
`worker_pool_size` replicas in sequence, rather than just one replica as before this
session. Live-confirmed: 5 concurrent receipts against a freshly-started process with
`worker_pool_size=3`, two receipts failed identically at 332.32s wall-clock, both
`reached_stage=geod outcome=failed` — the same number for both is itself the signal:
that is a shared bottleneck firing, not two receipts organically taking the same real
time. Fixed with `InferenceServicer.warm_up()`, called from `service.py`'s `__main__`
after `serve()` starts but before it prints `BOUND_ADDRESS` — every enabled preset's
full pool loads once, serially, at process startup, so real concurrent request traffic
never arrives before the pool is ready to actually serve it. `test_service.py`'s
`test_warm_up_loads_the_full_pool_for_every_enabled_preset_before_returning` asserts
`worker_pool_size` real loads happen, not just one.

**Real, live-found second repo shape: `resolve_variant_path()` only handled Microsoft's
own tagged-subfolder-per-variant convention, and a real community repo doesn't follow
it.** Added the `qwen2.5-3b` preset (`keisuke-miyako/Qwen2.5-3B-Instruct-onnx-int4`) as a
direct, same-hardware, same-backend comparison point for a real "is V3's own architecture
the bottleneck, or is this model/hardware just slow" question — confirmed live via
`list_repo_files` before adding it that this repo genuinely has a real `genai_config.json`
(loadable by the existing `OnnxGenAiBackend`, unlike `onnx-community`'s own Transformers.js-
style Qwen exports, which have none). Its real layout is flat — every file directly at the
repo root, no `cpu_and_mobile/<tag>/` nesting to disambiguate among, because there is
nothing to disambiguate: one repo, one build. `resolve_variant_path()` now falls back to
`""` (meaning "the repo root itself") whenever no file anywhere in a repo's listing
contains `/`, regardless of which precision/quant tag was requested — a flat repo has
exactly one variant by construction. `model_provisioning.py`'s two prefix-stripping call
sites (`list_remote_variant_files`, `provision_preset`) both needed the matching fix:
`f"{variant}/"` produces a bare `"/"` for an empty variant, which no real file path starts
with, silently excluding every file rather than including all of them. Existing nested-repo
behavior (`phi4-mini`, `phi4-vision`) is unchanged — the fallback only triggers when zero
subfolders exist anywhere, never when tags simply don't match a real multi-variant repo.

**Real, live-found follow-up the same session: the flat-repo fix above was incomplete —
a third call site building the actual download URL had the identical bug.** Confirmed
live provisioning `qwen2.5-3b` for real against the real fresh install: `ok=False`,
every one of 13 real files failed, nothing written to disk, despite
`list_remote_variant_files` already resolving the repo correctly (the two spots fixed
first). `provision_preset()`'s own download loop built the request URL as
`f"…/resolve/main/{variant}/{relative_path}"` unconditionally — for `variant == ""` this
produces a real double-slash URL (`…/resolve/main//model.onnx`) that Hugging Face's
server does not normalize and simply 404s on. Fixed with the same
`f"{variant}/" if variant else ""` guard as the other two spots.
`test_provision_preset_downloads_a_flat_repo_without_a_double_slash_url` serves against
a real local HTTP server matching the real repo's own path shape, so a regression here
fails exactly the way the real provisioning call did — confirmed by running it against
the pre-fix code first.

## Implementation status

Implemented this session — `contracts.py`, `errors.py`, `backends/` (Protocol + the one
`onnxruntime-genai` backend, unverified against real weights per the gotcha above),
`model_registry.py`, `presets.py`, `generation.py`, `batching.py`, `structured_output.py`,
`tool_calling.py`, `vision.py`, `metrics.py`, `service.py` + `inference.proto`. 33 tests,
all passing.
