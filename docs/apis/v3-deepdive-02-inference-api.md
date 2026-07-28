# V3 Deep Dive: Inference API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md` · `v3-deepdive-01-ocr-api.md`

**Status:** Second deep-dive session. Same ground rules as the OCR deep-dive: everything below is a fresh V3 decision, reasoned independently even where it lands near a V2 behavior; V2 material is background on failure modes, never a template. This deep-dive also resolves the shared-ONNX-substrate question the OCR deep-dive flagged and couldn't close alone (§8.6).

---

## 1. Scope & boundary

Inference API's job, per file 01's existing framing: **parser/corroborator, not decision-maker.** Concretely, given a prompt (optionally with images, optionally with a tool manifest, optionally with a required output schema), run generation on a loaded model and hand back the result. It does not:
- **own what tools exist or dispatch them** — that's the separate Tool Call API (file 01, #11). Inference API receives a tool *manifest* as part of a request (a shape Tool Call API defines), builds the right constrained-decoding grammar from it, and returns which tool the model chose to call with what arguments — it never executes a tool itself.
- **decide agent-loop policy** — how many rounds a tool-calling loop gets, when to give up and fall back to deterministic logic, when a result is "good enough" to stop asking for more corroboration. That's orchestration logic living in whatever caller is running the loop (a background worker, the receipt pipeline, a chat handler), exactly the same boundary OCR API drew for "should this receipt get a second opinion."
- **decide what's true** — if OCR API and Inference API's vision pass disagree about a receipt's vendor, Inference API doesn't adjudicate that; it reports what it saw, same as every OCR engine reports its own reading and leaves merging to whoever asked.

This mirrors OCR API's shape almost exactly: a **pure generation capability provider**. Everything about *when* to call it, with which tools, for how many rounds, belongs to the caller — and that symmetry is deliberate, not incidental; both APIs are "run a model, report what came back, don't own the policy above that." **A concrete example of this already-established boundary in practice**: when Execution Core assembles the prompt for the `INFERRED` stage, it includes Matching API's own ranked vendor candidates as context (`v3-deepdive-15-matching-api.md` §5) — Inference doesn't know or care that this context came from a fuzzy-matcher rather than anywhere else; it just receives a prompt and reports what it concludes, the same way it would for any other caller-assembled context.

---

## 2. Package layout

```
core/inference/
  __init__.py
  contracts.py            # GenerationRequest, GenerationResult, ModelPreset, ContentBlock, ToolCall, error types
  service.py                # thin gRPC service implementation, delegates everything
  model_registry.py         # Provider Registry: which presets are configured, lazy-load-with-locking (§6.2)
  presets.py                 # named model presets → HF repo + Model Builder config, live-resolved variants
  backends/
    __init__.py
    base.py                  # Backend protocol
    onnx_genai_backend.py     # onnxruntime-genai — the ONLY backend, see §4.2
  generation.py              # request → og.Generator loop, search options, batching hookup
  structured_output.py       # JSON-schema/regex constrained decoding (LLGuidance), see §5
  tool_calling.py            # turns a Tool Call API manifest into a constrained-decoding grammar
  vision.py                  # multimodal request handling, weight-sharing rules, see §7
  batching.py                # micro-batch window, per-preset request queue, see §6.3
  errors.py                  # ModelNotLoaded, GenerationTimeout, SchemaViolation, etc.
  metrics.py                 # tokens/sec, load time, batch size — feeds Health API and the bench suite
```

Same discipline as OCR API: `contracts.py` is the only file other APIs import from.

---

## 3. Data contracts (`contracts.py`)

```python
class ContentBlockType(str, Enum):
    TEXT = "text"
    IMAGE = "image"          # base64 or blob_ref, see §7 — same shape family as Anthropic's own content blocks and OCR API's Cloud Vision engine's multi-part payload, deliberately familiar rather than inventing a new convention

@dataclass(frozen=True)
class ContentBlock:
    type: ContentBlockType
    text: str | None = None
    image_ref: BlobRef | None = None   # content-addressable, same pattern as OCR API's image_ref

@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[ContentBlock, ...]

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: FrozenDict            # JSON Schema, shape owned by Tool Call API — Inference API only consumes it — FrozenDict per the project-wide policy (Tool Call deep-dive §6): a frozen dataclass with a plain dict field is only shallowly immutable

@dataclass(frozen=True)
class GenerationRequest:
    run_id: str
    user_id: str
    preset: str                         # which configured model preset to use — caller's choice, not policy
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()     # empty = no tool-calling grammar built
    response_schema: FrozenDict | None = None  # JSON Schema for constrained decoding — mutually exclusive with `tools` in practice, see §5
    max_tokens: int = 512
    temperature: float = 0.0
    timeout_ms: int = 30_000

@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: FrozenDict

class FinishReason(str, Enum):
    STOP = "stop"                # model naturally finished
    LENGTH = "length"            # hit max_tokens — see §5.2's truncation handling
    TOOL_CALL = "tool_call"
    ERROR = "error"

@dataclass(frozen=True)
class GenerationResult:
    text: str                            # empty when finish_reason == TOOL_CALL
    tool_call: ToolCall | None
    finish_reason: FinishReason
    schema_valid: bool                    # did constrained output actually validate against response_schema/tool schema — see §5
    device: str                          # "cpu", "cuda", "openvino:npu", etc. — same convention as OCR API's EngineReading.device
    duration_ms: int
    error: InferenceError | None = None   # populated + empty text on failure — never raises across the API boundary, same convention as OCR API
```

Same design choice as OCR API: errors are data, not exceptions, at the API boundary. A caller checking `result.error` instead of wrapping every call in try/except is the same pattern for the same reason — this project's postmortem lesson about never silently swallowing failure detail applies here too.

---

## 4. Model backend & dependencies

### 4.1 The single backend decision — no llama.cpp carried forward
V2 ran two backends (`backend_onnx.py` primary, a deprecated `backend_llamacpp.py` kept only because its prebuilt wheels capped the whole project at Python 3.11–3.12). **V3 ships exactly one backend: `onnxruntime-genai`.** The reasoning, stated plainly rather than inherited: `onnxruntime-genai` now has prebuilt wheels for Python 3.11 through 3.14 across every target platform, which was llama.cpp's only remaining reason to exist in this project — once that Python-ceiling problem is gone, maintaining a second backend implementation (a second set of model presets, a second prompt-templating path, a second set of quirks to work around) has no remaining justification. This is the same shape of decision as OCR API dropping docTR: when one option now fully covers the need a second option existed for, keep one, not two.

### 4.2 Dependency
```
pip install onnxruntime-genai              # CPU
pip install onnxruntime-genai-directml     # most GPUs, Windows
pip install onnxruntime-genai-cuda         # NVIDIA
```
Exactly one of these three gets installed per machine, chosen from the shared hardware detection (§8.6) rather than guessed — this is a real install-time decision, not a runtime flag, since each package bundles a different native runtime. `onnxruntime` itself (the base package, not the GenAI extension) is already a dependency via OCR API's RapidOCR — `onnxruntime-genai` is the only incremental install for this API, which is exactly the shared-substrate story §8.6 is about.

### 4.3 Model is a directory, not a file
An ONNX GenAI model is a directory (`genai_config.json`, the `.onnx` graph + weights, tokenizer files), not a single artifact — this matters for how presets get downloaded/cached and for the blob-storage question (these live on local disk under a models directory, not in Persistence's per-receipt content-addressable blob store, since they're shared program assets, not per-user data).

### 4.4 Presets — self-healing resolution, same technique as OCR API's model-currency concern
```python
# core/inference/presets.py — sketch
MODEL_PRESETS: FrozenDict[str, FrozenDict] = FrozenDict({   # FrozenDict per docs/PRINCIPLES.md §2.1.1 — a read-only table shared across threads under free-threading
    "phi4-mini": {
        "repo": "microsoft/Phi-4-mini-instruct-onnx",
        "variant_hints": {"cpu": ("cpu", "int4"), "cuda": ("gpu", "int4"), "directml": ("gpu", "int4")},
        "context_window": 128_000, "supports_tools": True, "supports_vision": False,
    },
    "phi4-vision": {
        "repo": "microsoft/Phi-4-multimodal-instruct-onnx",   # or the newer Phi-4-reasoning-vision-15B export, once it has one — see §9
        "variant_hints": {"cpu": ("cpu", "int4"), "cuda": ("gpu", "int4"), "directml": ("gpu", "int4")},
        "context_window": 128_000, "supports_tools": False, "supports_vision": True,
    },
    "qwen-tools": {
        "repo": "<Qwen ONNX export repo, TBD>",
        "variant_hints": {"cpu": ("cpu", "int4"), "cuda": ("gpu", "int4")},
        "context_window": 32_000, "supports_tools": True, "supports_vision": False,
    },
})   # inner per-preset mappings are FrozenDict too — the nesting matters, a FrozenDict of plain dicts is still mutable one level down
```
Which quantization *variant subfolder* inside a given repo to pull (`cpu-int4` vs `gpu-int4`, block sizes, etc.) is resolved from the **live repo listing at download time**, never hardcoded — the exact self-healing technique already established for OCR API's own model-currency concern (§9 of the OCR deep-dive), now shared conceptually across both APIs since both consume Hugging Face-hosted ONNX artifacts that can restructure their folder layout between releases. A real library of pre-quantized presets already exists on Hugging Face for the common families (Phi, Qwen, Llama, Gemma, Mistral, SmolLM, Granite, DeepSeek) — this project shouldn't need to do original quantization work for whichever presets get chosen, only point at the right repo and resolve the variant folder live.

### 4.5 Reasoning models — a real design caution, not just a V2 footnote
Reasoning-tuned models (chain-of-thought presets in the Phi-4-reasoning family, DeepSeek-R1-style, Qwen3-thinking variants) emit a thinking/CoT segment before their actual answer. That's a genuine token-budget and structured-output design concern for this API specifically: a CoT preamble consumes real tokens against `max_tokens` before the schema-constrained answer even starts, and if the budget runs out mid-preamble the constrained-decoding grammar (§5) never gets a chance to run at all. **Decision: reasoning-capable presets get their own separate token budget for the thinking segment** (`reasoning_token_budget` in config, distinct from `max_tokens`), with generation only switching into the schema-constrained grammar once the model's own thinking-end marker is seen (most reasoning models emit an explicit delimiter, e.g. a closing `</think>`-style tag) or the reasoning budget is exhausted, whichever comes first. Whether any reasoning preset is worth including as a default `tools`-capable option at all — given the added latency and budget complexity — is left open (§9); non-reasoning instruct presets (Phi-4-mini, Qwen-Instruct) remain the default for tool-calling/extraction tasks where speed matters more than deep reasoning.

---

## 5. Structured output & tool calling — native constrained decoding, not prompt-engineering

This is the one place V2's approach is worth naming as genuinely obsolete rather than just "a wishlist item to redesign." V2's `backend_onnx.py` is explicit that `onnxruntime-genai` at the time had "no response_format/grammar constraint," so the whole system leaned on prompt instructions ("reply with ONLY this JSON") plus a family of `_salvage_*_json` regex-ish parsers to recover from truncated or malformed output, plus a `_looks_degenerate()` check for models that echoed a canned tool-call stub instead of answering. That was a reasonable workaround for what the library could do *then*.

**It's no longer the right design, because the library changed under it.** `onnxruntime-genai` has since merged native constrained decoding built on the LLGuidance library (JSON Schema and regex constraints, with function/tool-calling support built on the same mechanism) — confirmed shipping in current releases with working examples in the project's own repo, not a from-source experimental branch anymore. In the field's own current framing, prompt-engineered JSON is "Level 1" (works most of the time, no guarantees); constrained decoding is "Level 3" (schema-valid by construction, since invalid tokens are masked out during generation rather than filtered after the fact). V3 should build on Level 3 directly rather than re-implementing V2's Level-1 salvage-parsing stack as if it were still the best available option.

### 5.1 How it works in this design
1. Caller sends a `GenerationRequest` with either `response_schema` (plain structured extraction) or `tools` (Tool Call API's manifest, turned into a discriminated-union schema by `tool_calling.py` — "which one of these N tool schemas, or none").
2. `structured_output.py` compiles that schema into a constrained-decoding grammar once per distinct schema shape and reuses the compiled grammar for repeat calls against the same schema — schema compilation has a real one-time cost, not free on every request.
3. Generation runs with that grammar active; every token is masked to only schema-valid continuations. Output is guaranteed syntactically valid JSON conforming to the schema *if generation completes normally*.
4. `GenerationResult.schema_valid` reports whether the completed output actually validated — should be `True` essentially always under normal completion given constrained decoding's guarantee, `False` only really possible alongside `finish_reason == LENGTH` (see below).

### 5.2 Truncation handling — file 01's explicit requirement, now easier but not eliminated
Constrained decoding guarantees *syntactic validity of what's been generated so far*, not that generation *finishes* — a `max_tokens` cutoff can still land mid-object even with a grammar active, if the schema's valid completion is longer than the token budget allowed. So the requirement from file 01 ("handle truncation gracefully — detect and retry with more budget, or salvage partial output, never hard-fail") still applies, just with a much smaller and better-defined problem than V2 faced:
- `finish_reason == FinishReason.LENGTH` is the detection signal — no need for V2's heuristic `_looks_degenerate()`-style pattern sniffing, since the engine reports this directly.
- **Decision: on `LENGTH`, retry once with a larger `max_tokens`** (a config-driven multiplier, e.g. 2×) before giving up — this handles the common case (the schema's honest answer was just longer than the caller guessed) cheaply.
- If the retry also truncates, fall back to a salvage parse of the partial output (a genuinely reduced-scope version of V2's `_salvage_*_json` idea — worth keeping as a last-resort utility, since it's a legitimately good defense-in-depth technique even though it's no longer the primary strategy) rather than hard-failing the caller.
- The old "degenerate canned tool-call stub" failure mode was a symptom of a specific GGUF chat-template quirk in the llama.cpp backend being dropped anyway (§4.1) — not assumed to still apply to `onnxruntime-genai`'s own presets, but worth a bench check (§11) before assuming it's fully gone.

---

## 6. Concurrency — async caller, isolated generation, lazy loading with a real lock

File 02 already places Inference API in "Async caller + native/isolated-process generation," specifically to fix V2's `LLM_CALL_LOCK` stalling bug (one shared, non-reentrant loaded model; a receipt waiting on its LLM step blocked every other receipt's concurrent work). **This section had a real inconsistency, caught late: the original code sketch here used a thread-pool `run_in_executor` dispatch, not a genuine separate process — "isolated-process" in name only.** Corrected below, and worth naming why the distinction actually matters, not just fixing it silently: a thread-pool dispatch means a segfault or driver crash inside `onnxruntime-genai`'s own native code (a real, non-hypothetical failure mode — GPU driver issues, a malformed model, an out-of-memory kill) takes down Inference API's *entire own service process*, including every other loaded preset and its own ability to answer health checks — exactly the kind of blast radius Preprocessing's own `ProcessPoolExecutor` design (its deep-dive §8) was already built to avoid for the identical reason. There's no principled reason Inference API's generation should get a weaker isolation guarantee than Preprocessing's variant generation gets, especially given generation is the more expensive, more crash-prone native call of the two.

### 6.1 Why `onnxruntime-genai` forces this shape, and why the isolation needs to be real
The Python bindings (`og.Model`, `og.Generator`) are synchronous and stateful — a `Generator` object owns an in-flight sequence's KV cache and isn't safely reentrant across concurrent callers. There's no native `asyncio` support in the library itself. So "async" here has to be built, not inherited — and per the correction above, the actual generation work needs to live in a genuinely separate OS process per loaded preset, not a thread:

```python
# core/inference/generation.py — sketch, corrected
class PresetWorker:
    """A handle to a persistent CHILD PROCESS, not a thread. The actual
    og.Model/Generator objects are loaded once and live entirely inside
    that child process — Inference API's own service process never
    touches them directly, and never even imports onnxruntime_genai's
    heavy native bindings into its own process space at all (a real,
    additional benefit: the parent service process stays light and
    fast to start, since it's not the one paying model-load cost)."""
    def __init__(self, preset_name: str, device: str):
        self._process: multiprocessing.Process | None = None
        self._request_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._response_queue: multiprocessing.Queue = multiprocessing.Queue()

    async def load(self) -> None:
        self._process = multiprocessing.Process(
            target=_worker_main, args=(self._preset_name, self._device, self._request_queue, self._response_queue),
            daemon=True,   # dies with the parent, never an orphaned zombie process outliving the service that spawned it
        )
        self._process.start()
        # _worker_main runs inside the child process: loads og.Model ONCE
        # at startup, then loops forever reading GenerationRequest objects
        # off request_queue and writing GenerationResult objects to
        # response_queue — see §6.3 for the batching detail inside that loop

    async def submit(self, request: GenerationRequest) -> GenerationResult:
        loop = asyncio.get_event_loop()
        # multiprocessing.Queue's put()/get() are themselves blocking calls
        # (real OS-level IPC, not free) — still worth off-loop dispatch via
        # run_in_executor so even the IPC hop itself can't stall the event
        # loop's ability to service other concurrent work
        await loop.run_in_executor(None, self._request_queue.put, request)
        return await loop.run_in_executor(None, self._response_queue.get)

    async def health_check(self) -> bool:
        """Inference API's own process can independently confirm a given
        preset's worker is still alive (self._process.is_alive()) without
        that check itself ever being at risk from whatever crashed inside
        the worker — the parent process's own health, and its ability to
        report on every OTHER preset's own worker, is structurally
        unaffected by any one worker crashing."""
        return self._process is not None and self._process.is_alive()
```
Callers `await submit(...)` — a receipt's LLM step never blocks another receipt's concurrent OCR/matching/whatever work, because the caller's coroutine just waits while the event loop keeps servicing everything else. The actual blocking `og.Generator` work runs entirely inside its own dedicated child process, one preset's requests never contending with another preset's (each `PresetWorker` owns its own process and its own queues), and — the corrected, load-bearing property — **a crash in one preset's generation process is contained to that process alone**, never propagating to Inference API's own service process or to any other preset's worker.

### 6.2 Lazy loading with a real lock
File 01 explicitly calls out that this needs "real locking (not just the generation-call lock) to avoid a load race" — two concurrent first-requests for a preset that isn't loaded yet must not both trigger a duplicate load:
```python
_load_locks: dict[str, asyncio.Lock] = collections.defaultdict(asyncio.Lock)

async def get_worker(preset_name: str) -> PresetWorker:
    if preset_name in _loaded_workers:
        return _loaded_workers[preset_name]
    async with _load_locks[preset_name]:
        # re-check inside the lock — the double-checked-locking pattern;
        # a second concurrent caller that queued behind the lock must not
        # reload after the first caller already finished loading
        if preset_name in _loaded_workers:
            return _loaded_workers[preset_name]
        worker = PresetWorker(preset_name, device=...)
        await worker.load()   # spawns the child process and waits for og.Model(...) construction to complete inside it — see §6.1's corrected design, no longer an executor thread
        _loaded_workers[preset_name] = worker
        return worker
```
One `asyncio.Lock` per preset name (not one global lock) — loading `phi4-mini` and loading `phi4-vision` concurrently shouldn't serialize against each other just because they happen to both be "a model load."

### 6.3 Batch-first — a real micro-batch window, now correctly placed inside the child process
File 01 states Inference API is "batch-first." Concretely: `_worker_main`'s own loop, running *inside* the child process (§6.1's correction — not the parent service process, since the batch is what actually gets handed to `og.Generator` and that call only exists inside the worker), doesn't grab exactly one queued request off `request_queue` — it drains whatever's immediately available, then waits up to a small configurable window (e.g. `batch_window_ms`, default ~20–50ms) for more requests destined for the *same preset* to arrive before dispatching a single `generate()` call across the batch, writing results back to `response_queue` per-request once the batch completes. This matters concretely for this workload: multiple receipts in a batch scan hitting the same extraction preset within milliseconds of each other is the common case, not an edge case, and `onnxruntime-genai`'s `batch_size` search option exists specifically to serve exactly this pattern in one forward pass instead of N sequential ones.

### 6.4 Multi-hardware agent splitting
Different presets can be pinned to different devices — e.g. a fast text-extraction preset on an iGPU, a heavier vision preset on the one discrete GPU present — each `PresetWorker` carries its own `device`, resolved from config plus the shared hardware detection (§8.6), not a single global device setting for the whole API.

**Frozendict retrofit applied to this API's own contracts** (`ToolSpec.parameters_schema`, `GenerationRequest.response_schema`, `ToolCall.arguments`, §3) — see Tool Call API's deep-dive §6 for the full policy and the version-gated shim; stated here only to confirm this API's own contracts were checked against it, not left as an oversight.

### 6.5 Free-threading (no-GIL) — a different, simpler story than originally written, now that generation is genuinely process-isolated
An earlier version of this section reasoned about GIL/free-threading relevance under the assumption that generation ran in a thread within Inference API's own service process. **That assumption was wrong (§6.1's correction) — generation runs in a genuinely separate child process, its own independent Python interpreter instance.** This actually simplifies the story: whatever free-threading status the *parent* Inference API service process runs under has no bearing at all on what happens inside a generation worker's own process, since each has its own GIL (or lack thereof) entirely independently. The parent process delivers concurrency through process isolation, full stop — not through free-threading, and not through thread-pool dispatch either.

Where free-threading *would* matter is within each side separately: the **parent service process's** own pure-Python orchestration (`structured_output.py`'s grammar compilation, `tool_calling.py`'s schema-building, dispatching to `PresetWorker`s) — file 02's "No-GIL candidate" bucket, negligible at this API's actual request volumes but worth writing free-threading-safe from day one regardless. And separately, **each generation worker process's own interpreter** — worth running under a free-threaded build too eventually, though the actual benefit is smaller there than it might sound, since the worker's own hot path (`og.Generator`'s token loop) is already native, GIL-releasing compute the same way OCR's own local engines are — free-threading doesn't speed up work that was never GIL-bound in the first place.

**The silent-GIL-re-enable caveat still applies, now scoped correctly to where it actually matters**: `onnxruntime-genai` (and its underlying `onnxruntime`) is exactly the kind of C-extension-backed dependency that free-threaded CPython will silently fall back to GIL-enabled mode for — but this now only affects whichever generation worker process loaded it, not Inference API's own parent service process (which never imports `onnxruntime_genai` into its own process space at all, per §6.1's stated benefit). Checkable via `sys._is_gil_enabled()` inside a worker process specifically.

**Telemetrees ownership, same as OCR API's deep-dive established**: `onnxruntime`, `onnxruntime-genai`, and any tool-calling/schema-validation pure-Python dependencies belong on Dependencies Warden's tracked list (file 02, rule #8) specifically for free-threading-support status, cross-referenced against the community compatibility tracker — not asserted as a fixed fact in this document. Given `onnxruntime` is shared infrastructure between this API and OCR API (§8.6), this is one tracked entry serving both APIs' deep-dives, not a duplicated tracking effort.

**Interpreter target**: same position as the OCR deep-dive — Python 3.14t (free-threaded) or later, with Python 3.15's stable ABI for free-threaded builds (PEP 803, final release October 1, 2026) as the real confidence milestone, applied independently to the parent service process and to each generation worker process, since they're now separate interpreters that could in principle even run different Python versions if that were ever useful (not currently planned, but a real structural option this correction opens up that thread-based dispatch never could have).

### 6.6 Profiling — Tachyon and py-spy, now aimed at a process tree, not a single process
No reason to reinvent this per API — the same two tools apply, aimed at this API's own questions, with one correction: given §6.1's process-based design, profiling needs to target the right process in what's now a small process tree (the parent service process, plus one child process per loaded preset), not assumed to be a single process the way an earlier version of this section implied.
- **py-spy**, usable now (added explicit Python 3.14 support in its 0.4.2 release): its `--subprocesses` flag (already the right tool for exactly this shape of problem, per Preprocessing's own deep-dive §9.3 applying it to `ProcessPoolExecutor` workers) is what actually confirms the parent process stays responsive while a specific preset's worker process is busy generating — the single-process `--gil`/`%GIL` mode alone wouldn't show the full picture across a process tree.
- **Tachyon** (Python 3.15, `profiling.sampling`, PEP 799), once available: near-zero-overhead, attaches by PID — needs to be pointed at whichever process in the tree is actually the question (the parent for dispatch/batching-window behavior, §6.3; a specific worker for generation-loop behavior itself).
- Both belong in the bench suite (§11) alongside the throughput/load-time bench cases already specified there, turning the concurrency reasoning in this section from architectural argument into measured fact.

### 6.7 Lazy imports (Python 3.15, PEP 810) — same technique as OCR API's own deep-dive, applied to this API's own heavy dependency
`onnxruntime-genai` itself, and any preset-specific tokenizer/processor libraries a given model family needs, are exactly the kind of import-cost this technique targets — `model_registry.py`'s existing lazy-load-with-locking design (§6.2) already defers the expensive *model weight* load until a preset is first requested; PEP 810 extends the same discipline one level earlier, to the *module import* itself. Under the current design, `import onnxruntime_genai as og` at the top of `generation.py` pays its import cost at process startup regardless of whether any preset ever actually gets requested in a given process's lifetime — a real cost for a process that might be running with Inference API's presets entirely disabled (a self-hosted install that never enabled any LLM features, say). Same feature-detected, strictly-no-worse-on-older-Python treatment as OCR's own application of this technique (its deep-dive §10.4) — not a hard 3.15 requirement, a free improvement when available.

---

## 7. Vision/multimodal corroboration

Genuinely new for V3 — file 01 is explicit this was never confirmed working in V2 on either backend it tried. The contract: a `GenerationRequest`'s `Message.content` can include `ContentBlock(type=IMAGE, image_ref=...)` alongside or instead of text — a vision-capable preset (`supports_vision: True` in its preset entry, §4.4) reads the receipt image directly as an independent corroboration source, separate from whatever OCR API's text engines produced.

**Weight-sharing, clarified rather than just restated:** file 01 requires multimodal presets not double-load weights. Worth being precise about what that actually means in practice — most current vision-language ONNX GenAI exports (Phi-4-multimodal, Qwen-VL-style presets) are genuinely **one unified model** that handles both text-only and text+image requests through the same loaded weights, not two separate models glued together at the API layer. So "don't double-load" isn't a special sharing mechanism this design needs to build — it falls out naturally from `model_registry.py` treating a vision-capable preset as a single `PresetWorker` (§6.1) that happens to accept image content blocks, the same worker serving both a plain-text extraction request and a vision-corroboration request for the same preset. The double-loading risk only becomes real if two *different* presets both happen to be vision-capable and both get loaded simultaneously — a config/preset-selection concern, not an architectural one.

---

## 8. Hardware acceleration

Same ONNX Runtime substrate as OCR API's RapidOCR (§5 of the OCR deep-dive), with Inference-specific considerations layered on top since generation has a very different performance profile than a detector/recognizer forward pass.

### 8.1 Execution providers — Inference-specific notes on top of the shared list
- **CUDA** — **CUDA 12.x is now the practical minimum** (11.x support has been dropped in current releases); worth confirming target hardware's driver compatibility before assuming CUDA EP availability, not assuming it. `onnxruntime.preload_dlls()` avoids DLL conflicts on systems that also have PyTorch installed (relevant if any other component in this system's dependency tree ever pulls in PyTorch — which, per the OCR deep-dive's decision, this project now deliberately avoids everywhere).
- **TensorRT** — two current variants: the classic TensorRT EP and a newer **TensorRT RTX EP** tuned for consumer RTX cards (runtime caching, CUDA graph support, BF16, memory-mapped engines). **Engine caching is mandatory, not optional** — TensorRT builds/optimizes an engine on first run, a slow step that repeats on every session creation without caching enabled. TensorRT and CUDA are a **fallback chain, not a replacement** — TensorRT's ahead-of-time engine compilation is a poor fit for this workload's variable input shapes (prompt length varies receipt to receipt, tool-calling conversations grow), so plain CUDA EP remains the real fallback rather than TensorRT falling straight to CPU.
- **OpenVINO** — actively developed specifically for this kind of workload: continuous batching for VLM pipelines by default, KV-cache eviction, INT4/INT8 weight compression via NNCF, confirmed real CPU/GPU/NPU targeting on Intel hardware.
- **DirectML / Windows ML** — WinML dynamically loads EPs via an "ExecutionProviderCatalog" that updates through Windows Update's optional preview channel, meaning EP behavior can shift on a Windows machine outside this app's direct control — worth Health API awareness (a version/capability check at startup) rather than assuming static behavior release to release.
- **QNN (Qualcomm NPU)** — actively maintained, recent SDK additions cover new ops and native ARM64 wheels, relevant for Snapdragon X laptops (same platform OCR API's RapidOCR would also target via QNN).
- **MIGraphX (AMD)** — **the ROCm execution provider itself was removed from ONNX Runtime as of the 1.23 release** (last available in ROCm 7.0-era builds); MIGraphX is the supported AMD path going forward, not an addition alongside a still-present ROCm EP. Conceptually: ROCm is the platform layer (drivers/HIP), the AMD analog to CUDA-as-a-platform; MIGraphX is AMD's graph-optimizing compiler on top of it, the AMD analog to TensorRT on top of CUDA. MIGraphX still requires ROCm installed underneath — only the direct `ROCMExecutionProvider` path is gone. **No official Windows GPU path exists yet for MIGraphX/ROCm** even on AMD's own flagship hardware — Windows falls back to CPU-only; Linux/WSL2 has the working path. Treat AMD GPU acceleration as Linux-first, not Windows-parity with CUDA/TensorRT/OpenVINO. *(This matches the OCR deep-dive's §5.1, corrected there for the same reason — see the note at the end of this document.)*
- **Fallback is per-node, not per-model** — a single generation session can genuinely run some ops on TensorRT, others on CUDA, others on CPU within one execution. Hardware selection should be designed around this native mechanism rather than reinventing fallback logic, same principle as OCR API's RapidOCR EP list.

### 8.2 Session-level performance settings specific to generation
- **IOBinding** — avoids unnecessary CPU↔GPU memory copies between repeated calls; directly relevant given the batch-first design means many repeated calls against the same loaded session.
- **CUDA Graph capture** (`enable_cuda_graph`) — captures a kernel-launch sequence once, replays cheaply on repeated calls with the same shape; a good fit here since receipt-processing prompts have fairly repeatable structure/length.
- **Engine/session caching** — mandatory for TensorRT (§8.1); also worth caching the loaded session across the `PresetWorker`'s lifetime rather than recreating it, since session creation itself is expensive — this is already implied by §6's design (one `PresetWorker` per loaded preset, loaded once).
- **Graph optimization level** (basic/extended/all) — set explicitly rather than relying on ORT defaults.
- **Memory arena settings** (`gpu_mem_limit`, `arena_extend_strategy`) — worth tuning to avoid OOM on constrained VRAM (e.g. an iGPU with a small dedicated allocation).
- **`intra_op_num_threads`/`inter_op_num_threads`** — must be coordinated with this API's own `asyncio`/executor-thread model (§6.1) or ORT's internal threading fights the app's own threading for the same cores — the same class of problem OCR API's Tesseract/OpenMP discussion covers, applied here to ORT's own thread pool instead of Tesseract's.

### 8.3 KV cache — the central generation-specific optimization
- **FP16 halves memory** vs. FP32 with minimal quality loss — default choice.
- **Sliding-window attention** caps KV-cache growth for long contexts (relevant given some presets have 128K context windows, §4.4, though a typical receipt-extraction prompt won't approach that).
- **Greedy search over beam search by default** — beam search has real overhead this workload's deterministic-extraction use case doesn't need (`temperature: 0.0` requests, §3, are already asking for the most-likely-token behavior greedy search gives directly).
- **`past_present_share_buffer`** — recommended specifically for CUDA + greedy search, worth enabling as the default combination for this workload's dominant case.
- **KV-cache quantization is separate from weight quantization and riskier** — current research shows naive INT4 KV-cache quantization measurably hurts accuracy without smarter techniques (rotation-based methods recover most of the loss); treat as opt-in/bench-tested, not default-on, unlike weight quantization below.

### 8.4 Weight quantization
**INT4 weight-only quantization is the dominant, well-supported default** for local/edge deployment — current reporting shows surprisingly little accuracy impact, and it's what the pre-quantized preset library (§4.4) already ships by default. The **Model Builder tool** (part of `onnxruntime-genai`) exports/quantizes a Hugging Face model directly to ONNX for a target precision+EP combination in one command (e.g. `-p int4 -e dml`) when a preset genuinely needs a custom export rather than an existing pre-quantized one from the library.

### 8.5 Practical constraints worth designing around explicitly
- CUDA 12.x minimum — confirm target hardware's driver compatibility rather than assuming.
- TensorRT engines are hardware+model-specific and slow to build on first run — caching mandatory.
- WinML's EP catalog can shift via Windows Update outside this app's control — Health API monitoring, not a static assumption.
- Node-level EP compatibility varies per op — verify actual chosen model against actual chosen EP rather than assuming full acceleration from an EP's mere presence.

### 8.6 The shared-substrate question — resolved, with a refinement from Setup API's own deep-dive
The OCR deep-dive's §5.6 proposed a direction — Setup API owns hardware detection, a shared session/EP-selection utility sits beneath both APIs — and flagged live-VRAM-coordination as needing a further session to confirm. Setup API's own deep-dive (`v3-deepdive-11-setup-api.md` §6) has since resolved it, with one refinement worth restating from Inference API's own side rather than just cross-referencing:

- **Setup API as the static hardware-detection source of truth**: confirmed — Inference API's `model_registry.py` queries Setup API's published `HardwareProfile` at startup (what GPUs/NPUs/EPs exist) rather than re-probing, exactly matching OCR API's approach.
- **The shared session/EP-selection utility**: confirmed as generic-enough plumbing to live outside either domain — building an ordered `providers=[...]` list from a hardware profile plus a config'd preference is identical logic whether the caller is RapidOCR or an ONNX GenAI model.
- **Live resource coordination — resolved as Health API's job, not an extension of Setup API.** This deep-dive's own original proposal (extend Setup API into a live commitment ledger) turned out to be the wrong home once Setup API's actual nature got examined directly in its own session: Setup runs once or rarely, while a live VRAM ledger needs to be checked on effectively every GPU-backed session creation across two separate processes — a continuously-hammered runtime concern, not a one-time-setup one. Health API already exists as this project's live-diagnostic, continuously-running status layer (the same thing Execution Core's Watchdog integration and Auth's session-latency monitoring both already lean on) — a natural fit for "which process currently holds how much VRAM on which device" as one more live signal it hosts, rather than force-fitting the responsibility onto Setup API just because Setup happened to measure the hardware first. Before a `PresetWorker` (or an OCR engine) allocates a session on a GPU device, it calls Health API with "reserve ~N MB on device X," releasing the reservation when the session unloads — the same reservation-contract shape originally proposed, just hosted by the API actually built for ongoing runtime queries.
- **Domain logic stays fully separate regardless** — same statement as the OCR deep-dive: the shared substrate only ever hands back "here's a session on this device," it has no opinion about prompts, tools, corroboration, or anything else either API does with that session.

This is now fully resolved, ownership and implementation both — Health API's own deep-dive designed the reservation contract's failure modes: TTL-based reservations refreshed via a heartbeat piggybacked on Watchdog's own kick mechanism, so a reservation left behind by a crash gets released automatically once its TTL lapses rather than blocking real capacity forever.

---

## 9. gRPC surface (`.proto` sketch)

```protobuf
service InferenceService {
  rpc Generate(GenerateRequest) returns (GenerateResponse);
  rpc ListPresets(ListPresetsRequest) returns (ListPresetsResponse);   // for Interface API's settings menu, reflects actual loaded/available state
}

message GenerateRequest {
  string run_id = 1;
  string user_id = 2;
  string preset = 3;
  repeated Message messages = 4;
  repeated ToolSpec tools = 5;
  string response_schema_json = 6;   // empty = no schema constraint
  int32 max_tokens = 7;
  float temperature = 8;
  int32 timeout_ms = 9;
}

message Message {
  string role = 1;
  repeated ContentBlock content = 2;
}

message ContentBlock {
  string type = 1;        // "text" | "image"
  string text = 2;
  string image_blob_ref = 3;
}

message ToolSpec {
  string name = 1;
  string description = 2;
  string parameters_schema_json = 3;
}

message GenerateResponse {
  string text = 1;
  ToolCall tool_call = 2;         // unset unless finish_reason == "tool_call"
  string finish_reason = 3;       // "stop" | "length" | "tool_call" | "error"
  bool schema_valid = 4;
  string device = 5;
  int32 duration_ms = 6;
  string error_code = 7;
  string error_detail = 8;
}

message ToolCall {
  string name = 1;
  string arguments_json = 2;
}
```

**`StreamGenerate` removed — a real correction, not a simplification for its own sake.** This RPC existed for exactly one stated use case, a live chat/AI-Mode interface watching tokens arrive — and that use case has moved entirely to a genuinely separate system, `v3-deepdive-54-webapp-assistant.md`, backed by Cloudflare Workers AI rather than this project's own local Inference API. Keeping a purpose-built RPC around with its one stated purpose now gone would be exactly the kind of speculative, unjustified scope this project's own "reasoned, then measured" discipline argues against — every structured-extraction caller (the actual, real workload this API serves) was already well served by `Generate`'s plain unary shape; nothing here actually needed streaming once the chat use case left. If a genuine, new streaming need for local inference emerges later, it gets added then, with its own real justification — not kept on standby for a use case that already moved elsewhere.

---

## 10. Config surface

```
inference:
  presets_enabled: [phi4-mini]              # phi4-vision, qwen-tools, etc. opt-in
  default_preset: phi4-mini
  vision_preset: phi4-vision
  hardware:
    phi4-mini_device: cpu                    # per-preset, same convention as OCR API's per-engine hardware config
    phi4-vision_device: cpu
  batch_window_ms: 30
  max_concurrent_generations: 4               # queue depth cap before backpressure, per preset
  reasoning_token_budget: 1024                 # separate from max_tokens, see §4.5
  truncation_retry_multiplier: 2.0             # see §5.2
  per_request_timeout_ms: 30000
```

---

## 11. Testing hooks

- `tests/unit/core/inference/` — backend mocked (a fake `og.Model`/`og.Generator` pair), covering the lazy-load-locking race explicitly (two concurrent `get_worker()` calls for an unloaded preset must result in exactly one `load()` call — the same shape of regression test V2 eventually wrote for its own cached-instance bug, worth keeping as a real regression test in V3 rather than trusting the design alone).
- **Constrained-decoding schema-compliance bench case**: since native grammar-based structured output is a relatively recent integration in `onnxruntime-genai`, worth an explicit bench pass verifying it actually produces 100% schema-valid output on the actual chosen preset/hardware combination, rather than assuming the library's general claim holds for this project's specific models — if it doesn't hold cleanly, that's exactly the kind of finding that should feed back into whether the `LENGTH`-driven retry path (§5.2) needs to be leaned on more than expected.
- **Batch-throughput bench case**: tokens/sec at batch sizes 1, 4, 8, 16 for each enabled preset/device combination — feeds `batch_window_ms` tuning and the bench suite's existing CPU/GPU/RAM classification per setting.
- **Load-time bench case**: cold model load time per preset/device — relevant to Setup API's boot-sequence health-gating (file 02) since Inference API reporting "ready" needs to mean "a model has actually finished loading," not just "the process started."
- **Profiling integration** (see §6.6): the bench suite should run its generation phases under py-spy today (using `--subprocesses` to confirm the parent process stays responsive while a worker process is busy generating, and checking `sys._is_gil_enabled()` status inside a worker process specifically) and switch to Tachyon once the project is on Python 3.15+, rather than leaving §6.5's concurrency reasoning as an untested architectural claim.
- **Crash-isolation test — the concrete validation of §6.1's entire correction**: a bench case that deliberately kills one preset's worker *process* (not just a mid-call timeout) via `SIGKILL`, confirming (a) Inference API's own parent service process is completely unaffected and keeps answering requests for every other loaded preset, (b) the killed preset's own next request triggers a clean reload rather than hanging forever waiting on a dead process's queue, and (c) no other Core API's process is affected at all. This is the test that actually proves "isolated-process generation" delivers what its name claims, rather than trusting the design description alone — the same failure-injection principle OCR API's and Preprocessing's bench suites already apply to their own worker processes, now genuinely applicable here too since generation finally runs in a real, separate process.
- **Reasoning-model degenerate-output regression check**: a required pre-launch bench pass confirming `onnxruntime-genai`'s own reasoning-tuned presets never reproduce V2's "canned tool-call stub" failure mode — a real, specific regression to check for given the backend genuinely changed, not assumed gone just because the failure was tied to a different (llama.cpp/GGUF) backend originally.

---

## 12. Open questions for this deep-dive (logged, not guessed at)

**Resolved, locked as a reasoned default:**
- **Reasoning-model inclusion: non-reasoning instruct presets only, by default.** The added latency and separate-budget complexity (§4.5) aren't worth it for the common structured-extraction case, which doesn't benefit from extended reasoning the way a genuinely ambiguous judgment call would — locking in the leaning rather than leaving it formally unlocked. A reasoning-tuned preset stays available as a non-default option for the cases that do benefit (a genuinely ambiguous vendor match, say), never removed from the roster, just not what a fresh install runs by default.
- **Vision preset default: Phi-4-multimodal, provisional pending real bench data.** Among the three candidates, it's the most established, general-purpose choice — a reasoned starting point, not a coin flip. `docs/PRINCIPLES.md` §1.9-adjacent discipline applies here too: this default is explicitly revisable once a real accuracy/speed comparison on actual receipt images exists, tracked the same way Preprocessing's own bench-pending defaults are (§11 there), never presented as more final than it is.

**Fully resolved, nothing pending**: Health API as live resource ledger (§8.6), `StreamGenerate` removal (§9).

**Explicitly deferred to its actual owning document, not double-tracked here:**
- **Beta/Alpha channel testing for Inference features** — genuinely Update API's own resolution to make (its deep-dive), given it depends entirely on that document's own channel-cutover mechanics; this document's own requirement is just staying compatible with whatever Update API lands on, already stated correctly.

**Stays open as a real pre-launch testing item, not a design gap**:
- **Reasoning-model degenerate-output risk** — whether `onnxruntime-genai`'s own presets ever reproduce V2's "canned tool-call stub" failure mode is a real bench-verification task before shipping, not a design decision this document can resolve by reasoning alone. Added to §11's own testing hooks as a required pre-launch check rather than left as an ambient worry.

**Resolved as an ongoing operational process**: free-threading compatibility status of `onnxruntime`/`onnxruntime-genai` — Telemetrees' own continuous tracking already owns this, one shared entry with OCR API's identical dependency (§8.6), not a design gap needing further resolution here.

---

## Correction to the OCR API deep-dive (applied)

Researching Inference API's own hardware section surfaced a factual gap in the OCR deep-dive's §5.1: it listed "ROCm / MIGraphX" as if both are current, separately-available execution providers. Per §8.1 above, **the ROCm execution provider itself was removed from ONNX Runtime as of the 1.23 release** — MIGraphX is the current AMD path, not an addition alongside a still-live ROCm EP. The OCR document has been updated to match this section's more precise phrasing.
