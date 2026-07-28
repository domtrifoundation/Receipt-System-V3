# V3 Deep Dive: OCR API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md`

**Status:** First deep-dive session. Everything below is a fresh V3 design decision. Where V2's wishlist entry (file 04) raised a question, it's answered here with independent reasoning — V2's existence is never the reasoning, only the prompt to think about it. Open items that genuinely can't be resolved without more research or a Francis decision are logged at the bottom, not guessed at.

---

## 1. Scope & boundary

The OCR API's job: given a **single already-selected image** (one page, one variant — a Preprocessing API output), produce **zero or more raw text readings** of it, one per enabled engine, plus a **corroborated result** when more than one reading came back. It does not:
- decide which preprocessing variants exist (Preprocessing API's job — OCR just gets called once per variant it's handed)
- parse structured fields out of the text (vendor/amount/date parsing is Matching/Inference territory downstream)
- decide whether a receipt needs a second opinion at all (that policy — "is this reading weak enough to escalate" — is orchestration logic that lives in the run scheduler / Reconciliation-adjacent pipeline code, not inside this API; OCR API exposes the primitives, doesn't decide when to call itself twice)

This keeps OCR API a pure **capability provider**: "read this image with these engines, tell me what each one saw and how confident you are in the merged answer." Everything about *when* to call it, with which engines, how many times, belongs to the caller.

---

## 2. Package layout

Following the package-per-API rule (soft cap ~300-400 lines/file):

```
core/ocr/
  __init__.py
  contracts.py          # OcrRequest, OcrReading, OcrResult, EngineName enum, error types — no logic
  service.py             # thin gRPC service implementation, delegates everything
  engine_registry.py     # Provider Registry: which engines exist, which are enabled, capability flags
  engines/
    __init__.py
    base.py               # Engine protocol (async def read(image_bytes, cfg) -> EngineReading)
    tesseract_engine.py
    rapidocr_engine.py
    paddleocr_engine.py
    windows_ocr_engine.py
    apple_vision_engine.py
    cloud_engines/          # Google Cloud Vision, Azure Document Intelligence, AWS Textract — one Provider Registry group, shared paid/network/cost-budget handling (see §4.7)
      __init__.py
      base_cloud_engine.py  # shared budget/timeout/error-taxonomy plumbing
      google_vision.py
      azure_doc_intelligence.py
      aws_textract.py
    text_layer_engine.py  # pdfplumber/PyMuPDF tier-0 "isn't actually a scan" fast path
  corroboration.py       # merges N readings into one OcrResult + confidence
  errors.py              # OcrEngineUnavailable, OcrEngineCrashed, OcrTimeout, etc.
  metrics.py             # per-engine timing/success counters, feeds Health API's status layer
```

`contracts.py` is the file every other API imports from. Nothing outside `core/ocr/` ever imports from `engines/` directly.

---

## 3. Data contracts (`contracts.py`)

```python
class EngineName(str, Enum):
    TEXT_LAYER = "text_layer"       # not OCR at all — PDF's embedded text, tier 0
    TESSERACT = "tesseract"
    RAPIDOCR = "rapidocr"
    PADDLEOCR = "paddleocr"
    WINDOWS_OCR = "windows_ocr"
    APPLE_VISION = "apple_vision"
    CLOUD_VISION = "cloud_vision"
    AZURE_DOCUMENT_INTELLIGENCE = "azure_document_intelligence"
    AWS_TEXTRACT = "aws_textract"

@dataclass(frozen=True)
class OcrRequest:
    run_id: str
    user_id: str                     # every call is scoped — no shared mutable state (per Decisions Log)
    image_ref: BlobRef                # content-addressable ref into Persistence's blob store, not raw bytes over the wire where avoidable
    engines: frozenset[EngineName]    # which engines to run this call — caller's choice, not policy
    timeout_ms: int = 15_000

@dataclass(frozen=True)
class TextRegion:
    text: str
    confidence: float                 # engine's own per-region score, 0.0–1.0
    box: tuple[float, float, float, float]  # x, y, w, h — normalized 0–1 against image dims, not pixels, so it's meaningful without also carrying image size

@dataclass(frozen=True)
class EngineReading:
    engine: EngineName
    text: str
    duration_ms: int
    regions: tuple[TextRegion, ...] = ()   # populated when the engine supports region-level output — see §4.3; empty tuple, never None, for engines that don't
    mean_confidence: float | None = None    # aggregate — mean of regions[].confidence where region data exists; None for engines that return plain text with no confidence signal at all (Windows OCR, tier-0 text-layer). Added per Historian's narrative-track requirement (v3-deepdive-29-historian.md §5.1) — a one-line "Tesseract read this at 87% confidence" narrative entry needs a single number, not a list of per-region scores to average ad hoc at every consumer. Computed once by the engine's own wrapper when the reading is constructed.
    device: str = "cpu"                    # which backend actually ran this reading — "cpu", "cuda", "openvino:npu", etc. See §5
    error: OcrError | None = None     # populated + text="" on failure — never raises across the API boundary

@dataclass(frozen=True)
class OcrResult:
    readings: tuple[EngineReading, ...]   # every reading requested, success or failure, always present
    merged_text: str                       # corroboration.py's pick — see §7
    agreement: AgreementLevel               # UNANIMOUS / MAJORITY / SPLIT / SINGLE_SOURCE / NONE
    confidence: float                      # 0.0–1.0, see §7.3
```

Design choice: `OcrResult.readings` always contains one entry per requested engine, **even on failure** (with `error` set, `text=""`), rather than silently dropping failed engines. Callers (and the bench suite's regression check) need to see "PaddleOCR was asked and crashed" as distinct from "PaddleOCR wasn't asked" — silently-dropped failures are exactly the kind of thing that made V2 debugging hard (per the postmortem's "full traceback vs. `str(e)`" lesson, generalized here to "never silently drop a requested unit of work").

---

## 4. Engines — dependencies, technique, failure mode

Each engine is a `Provider` in the Provider Registry pattern (architecture rule #5): independently enableable, runs in parallel with the others when more than one is requested, degrades to "unavailable" rather than crashing the run if its dependency is missing.

### 4.1 Tier 0 — Text layer extraction (not OCR)
- **Dependency:** `pdfplumber`, `PyMuPDF` (`pip install pdfplumber pymupdf`)
- **Applies to:** PDF inputs only; no-op on image inputs.
- **Technique:** Read the PDF's embedded text layer directly (`page.extract_text()` / `page.get_text()`) plus table cell extraction where present. Zero rendering, zero OCR cost — a digitally-generated PDF (an emailed e-receipt, a POS-printed PDF) often has a perfect text layer already and never needs pixel-level OCR at all.
- **Why two libraries, not one:** pdfplumber's table extraction catches tabular amounts that PyMuPDF's plain text dump sometimes runs together; PyMuPDF is faster and a good sanity cross-check. Both are cheap enough to always run together on PDF input rather than picking one.
- **Failure mode:** returns empty string (not an error) when the PDF has no text layer (i.e. it's a scanned image wrapped in a PDF) — this is the expected, common case that triggers falling through to tier 1.

### 4.2 Tier 1 — Tesseract
- **Dependency:** system binary `tesseract-ocr` (apt/brew/choco install, **not** pip-installable itself) + `pytesseract` (`pip install pytesseract`) as the Python binding.
- **License/cost:** free, Apache 2.0, fully offline.
- **Technique:** `pytesseract.image_to_string(image, lang="eng", config="--oem 3 --psm 6")`.
  - `--oem 3` selects the OCR *engine mode* — Tesseract ships both its legacy pattern-matching engine and its newer LSTM (neural net) engine; `3` means "use LSTM, fall back to legacy only if no LSTM data is available," which is the right default since the LSTM engine is meaningfully more accurate on real-world photos.
  - `--psm` is the *page segmentation mode* — it tells Tesseract what kind of layout to expect before it even starts reading, because Tesseract has to first decide "where are the blocks of text on this page" and gets that decision wrong constantly if given no hint. The relevant options for a receipt: `3` (fully automatic layout detection, Tesseract's own default — reasonable for a well-framed scan but can misjudge column/block boundaries on a narrow, ragged receipt), `4` (assume a single column of text of variable sizes — arguably the better fit for a receipt's narrow vertical strip layout), `6` (assume a single uniform block of text — simple and often good enough, currently the assumed default here), `11` (sparse text — find as much text as possible in no particular order, useful if a receipt has scattered stamps/handwriting outside the main block). **Decision: `psm` is a config value (`tesseract.psm`), not a hardcoded constant, defaulting to `6` as a starting guess — and the actual best value gets decided empirically, not argued about here.** The bench suite gets a dedicated PSM-sweep case (§11) that runs the same labeled receipt sample through Tesseract at `psm` ∈ {3, 4, 6, 11} and reports accuracy per mode, so the config default gets set from real measurement once that bench case exists, and stays a config knob afterward in case a given user's receipts genuinely differ (e.g. someone photographing wide restaurant bills vs. narrow thermal-paper receipts might legitimately want different defaults).
- **Preprocessing dependency:** Tesseract's own Otsu binarization handles real-world uneven lighting on a photographed receipt better than most preprocessing done *before* Tesseract sees the image — grayscale + mild autocontrast is the safe default input; anything more aggressive (hard thresholding, sharpening) is Preprocessing API's variant-generation territory, not something OCR API does internally. OCR API takes whatever image it's handed and doesn't second-guess it.
- **OpenMP threading, explained and resolved:** the Tesseract binary most Linux/Windows package managers ship is built with OpenMP enabled for its LSTM engine — meaning a *single* `tesseract` invocation internally spawns its own small pool of worker threads (commonly ~4, tied to `OMP_NUM_THREADS`/core count) to parallelize the neural-net matrix math for that one image. That's fine in isolation. It stops being fine the moment OCR API runs several Tesseract processes *concurrently* (which is exactly what happens whenever more than one engine or more than one preprocessing variant is being read at once) — now N Tesseract processes are each independently spinning up their own ~4-thread OpenMP gang, all contending for the same physical cores, and the OS scheduler thrashes between them instead of doing useful work. **Decision: cap each Tesseract subprocess to a single OpenMP thread by default** (`tesseract.omp_thread_limit: 1`, set via the environment passed to that specific subprocess only — never process-wide, since that would also cripple any *other* OpenMP consumer sharing the process, like PaddleOCR or NumPy's BLAS backend), and get parallelism the deliberate way instead: many single-threaded Tesseract processes running side by side under OCR API's own thread pool, which scales predictably rather than fighting itself. **This is a config knob, not a hardcoded constant** — a machine running Tesseract mostly in isolation (few concurrent engines/variants enabled) might genuinely do better letting each single Tesseract call use more of its own OpenMP threads, so `omp_thread_limit` stays overridable rather than baked in, with `1` as the default that matches this API's actual normal operating mode (many engines/variants running side by side). Exact mechanism for scoping the env var to one subprocess (rather than assuming an implementation) is still an implementation detail for the engine module, not decided here — but the direction and the default are.
- **Failure mode:** `pytesseract.get_tesseract_version()` as a startup sanity check; if the binary isn't on `PATH` or `tesseract_cmd` config points nowhere, the engine reports `OcrEngineUnavailable` at registry-init time (once, logged) rather than failing per-call.

### 4.3 Tier 2 — RapidOCR
- **Dependency:** `pip install rapidocr-onnxruntime`
- **License/cost:** free, Apache 2.0, ONNX-based, fully offline. Runs on CPU by default; genuinely hardware-accelerable across multiple runtimes since it's just ONNX Runtime underneath — see §5.
- **Technique:** detector + recognizer pipeline (PP-OCR family model, ONNX export) run via `RapidOCR()(np.array(image))`. Returns structured `(box, text, score)` tuples per detected text region.
- **Decision: structured per-region output (`TextRegion` in §3) is now a standard, first-class part of `EngineReading`, not RapidOCR-specific.** The deciding factor: this isn't actually a RapidOCR-only capability to weigh in isolation — Tesseract exposes the same thing via `image_to_data()` (word-level boxes + confidence, an easy swap from `image_to_string()`), and PaddleOCR's detector stage produces boxes natively as part of how it works at all. So nearly every engine *can* supply this cheaply; only the cloud tier, Windows OCR, and the tier-0 text-layer extractors are meaningfully plain-text-only by nature (and for those, `regions` just stays empty). Standardizing it now — rather than bolting it on later as a v2 contract migration — is the more stable path, and it directly feeds two things already flagged elsewhere in this project as needing real design attention: line-item extraction (Decisions Log, still open) and any future spatial cross-check in `corroboration.py` (comparing *where* engines agree, not just *what* they transcribed). Downstream consumers that don't care about regions just ignore the field; it costs them nothing.
- **Failure mode:** `ImportError` on missing dependency → `OcrEngineUnavailable`; runtime exceptions during inference → `OcrEngineCrashed` with the exception logged at debug (per-engine failures on individual receipts are expected/normal, not alarm-worthy).

### 4.4 Tier 2 — PaddleOCR
- **Dependency:** `pip install paddleocr paddlepaddle` (or `paddlepaddle-gpu` for CUDA) — another multi-GB install, heaviest of the local engines. Not PyTorch — PaddlePaddle is Baidu's own independent deep learning framework.
- **License/cost:** free, Apache 2.0, offline. As of the PP-OCRv5/PaddleOCR-VL generation, the reference implementation is generally regarded as the single most accurate open local engine on messy real-world photos and multilingual/CJK text, at the cost of being the heaviest to install and, without a GPU, the slowest per receipt.
- **Technique:** the reference PP-OCR implementation — RapidOCR's ONNX export is trained from the same model family, but the reference PaddlePaddle build stays ahead of RapidOCR's ONNX export in practice (newer model generations, e.g. PP-OCRv5 and the PaddleOCR-VL layout-aware variant, land in PaddleOCR first and only reach RapidOCR's ONNX conversions later, if at all). Produces per-region output natively (§4.3's decision applies here too).
- **Relationship to RapidOCR — resolved:** every engine in this API is an independently selectable Provider Registry entry, full stop; nothing here special-cases "these two are redundant so don't allow both." A user or run config can enable RapidOCR alone (fast, light), PaddleOCR alone (heavier, often more accurate), both as corroborating voters, or any other combination — that's the whole point of the Provider Registry pattern, and OCR API doesn't second-guess which combinations are "worth it." Whether the two actually diverge enough on real receipts to be useful corroborators together is a genuine empirical question, but it's answered by looking at bench data after the fact, not by hardcoding an assumption into the engine registry before anyone's measured it.
- **Failure mode:** `ImportError` on missing dependency → `OcrEngineUnavailable`; runtime exceptions during inference → `OcrEngineCrashed`, same pattern as RapidOCR.

### 4.5 Tier 2 — Windows OCR
- **Dependency:** `pip install winsdk` — wraps the OS-native `Windows.Media.Ocr` WinRT API.
- **License/cost:** free, offline, but **Windows-only** — genuinely unavailable (not degraded, structurally absent) on Linux/macOS.
- **Technique:** async WinRT call chain — decode image to a `SoftwareBitmap` via `BitmapDecoder`, run `OcrEngine.recognize_async`. This is the same engine behind Snipping Tool's "Text Actions" and PowerToys' Text Extractor — genuinely accurate on real-world photos for a zero-additional-install option on Windows.
- **Platform gate:** the engine registry must check `platform.system() == "Windows"` at registry-init time and mark the engine as structurally unavailable (not just "dependency missing") on other platforms — this is a different failure category from a missing pip package and worth its own `OcrError` subtype (`OcrEnginePlatformUnsupported`) so the Interface API can show "not available on this OS" rather than "not installed, run pip install."
- **Failure mode:** `winsdk` import failure → unavailable; `OcrEngine.try_create_from_user_profile_languages()` returning `None` (no language pack installed) → a distinct, actionable error the Interface API should be able to surface with a concrete fix ("install an OCR language pack in Windows Settings").

### 4.6 Tier 2 — Apple Vision (new — macOS's platform equivalent to Windows OCR)
- **Dependency:** `pyobjc-framework-Vision` (`pip install pyobjc-framework-Vision pyobjc-framework-Quartz`) — wraps Apple's native `VNRecognizeTextRequest` API.
- **License/cost:** free, offline, but **macOS-only** — same structural-unavailability category as Windows OCR on other platforms, not a degraded/missing-dependency case.
- **Technique:** `VNImageRequestHandler` + `VNRecognizeTextRequest` with `recognitionLevel = .accurate`; results come back as `VNRecognizedTextObservation` objects with per-region bounding boxes and confidence natively (§4.3's decision applies here too). This is the same engine behind macOS's own Preview/Photos "copy text from image" feature, and on Apple Silicon it transparently runs on the Neural Engine — no separate hardware-acceleration configuration needed on OCR API's side, unlike other locally-run engines (§5).
- **Why add it:** Windows OCR gives Windows users a free, accurate, zero-extra-install engine; macOS users currently have no equivalent in this design, only the heavier pip-installed options. Apple Vision closes that gap for the same reason Windows OCR exists — a genuinely good on-device engine that costs nothing extra on the platform it runs on.
- **Failure mode:** import/bridge failure (pyobjc not installed, or running on non-macOS) → `OcrEnginePlatformUnsupported`, same category as Windows OCR's platform gate.

### 4.7 Tier 3 — Cloud OCR services (Google Cloud Vision, Azure Document Intelligence, AWS Textract)
All three are the same *kind* of engine — paid, network-bound, high-accuracy fallback — and belong in one Provider Registry group sharing common plumbing (`cloud_engines/base_cloud_engine.py`: budget enforcement, timeout handling, the network/auth/rate-limit error taxonomy) rather than three independent one-off implementations.

- **Google Cloud Vision** — `pip install google-cloud-vision` **or** plain REST+API-key. **Decision: plain REST + API key (`httpx`/`aiohttp`)**, not the official SDK. Reasoning: the SDK's default auth path assumes a service-account JSON and pulls in `google-auth`'s full dependency chain for what this project's config surface already treats as a single pasted API key — REST keeps the dependency footprint minimal and matches the existing `cloud_vision_api_key`-shaped config exactly. If a future need for service-account-scoped auth (e.g. a hosted multi-tenant deployment wanting per-org quota) ever arises, that's a reason to add the SDK path *then*, not a reason to default to it now.
- **Azure Document Intelligence** (formerly Form Recognizer) — REST + API key, same reasoning as above. Notable difference from the other two: it's not just OCR, it has a prebuilt "receipt" model (`prebuilt-receipt`) that already attempts field-level extraction (vendor, total, date) as part of its own response — genuinely tempting, but out of scope for OCR API to consume that structured part, since field extraction is explicitly Matching/Inference territory (§1). OCR API only pulls the raw text/region output back out of the response and discards the vendor-specific structured fields, to keep this engine's contract identical in shape to every other engine's.
- **AWS Textract** — REST via `boto3` (AWS's own SDK is the practical choice here, unlike Google's — `boto3` is a much lighter, more general-purpose dependency already likely needed elsewhere if this project ever touches other AWS services, e.g. S3-compatible blob backup targets already in the Persistence API design). Also has its own structured "AnalyzeExpense" mode, same out-of-scope treatment as Azure's prebuilt-receipt model.
- **License/cost:** all three **paid**, per-image, real money. All three are network-bound — "Async I/O" concurrency bucket, same as Cloud Vision's existing classification.
- **Cost governance — applies uniformly to all three, not just Cloud Vision:** a per-run call budget per cloud engine, enforced inside `engine_registry.py` (a call past budget returns `OcrError.BudgetExceeded` before the network call happens), config-driven rather than hardcoded.
- **Never auto-enabled:** any cloud engine requires an explicit per-call request from the caller, never silently included in a "run all enabled engines" default set, given the cost — this was already the rule for Cloud Vision alone and now applies to the whole tier.
- **Failure mode:** network errors, auth errors (bad/missing key), and rate-limit responses are three distinct `OcrError` subtypes per engine — a bad key should surface differently in the Interface API than a transient network blip.
- **Why include three instead of one:** the same corroboration logic that benefits from multiple *local* engines applies here too — three independent commercial OCR vendors are a genuinely stronger corroboration signal than one, for the (presumably rare, EXTREME-mode-style) case where a receipt is bad enough to justify paying for cloud OCR at all. Nothing stops a user from enabling only one, or none.

### 4.8 Explicitly excluded engines (and why)
Worth naming these so the exclusion reads as a deliberate decision, not an oversight:
- **docTR** — technically doesn't *require* PyTorch (it supports either a TensorFlow or PyTorch backend, picked at install time), but that's exactly the problem: it forces this project to take on and maintain a full secondary deep-learning framework (TensorFlow, still a multi-GB dependency with its own CUDA/cuDNN version-matching headaches) just to avoid the framework we're already refusing. Simpler to drop it outright than to manage a second heavy DL runtime — PaddleOCR already covers the "heavier, more accurate local deep-learning engine" role this project wants, without the extra framework.
- **EasyOCR** — PyTorch-based, heavy (~1.5GB install pulling full PyTorch), and current independent comparisons put it behind Tesseract and PaddleOCR on printed-receipt-style accuracy anyway. No upside left once PyTorch is off the table.
- **Surya** — also PyTorch-based, and separately GPL-3.0 licensed (code) with a restrictive model license for larger commercial use — two independent reasons to exclude, either one would be sufficient alone.
- **Qwen2.5-VL / MiniCPM-o / Mistral OCR / GOT-OCR2 / olmOCR / DeepSeek-OCR and similar vision-language-model OCR** — genuinely strong on messy/complex documents, but these are full multimodal LLMs, not OCR engines in the sense this API deals with, and this project already has a defined home for exactly this capability: the Inference API's planned native ONNX Runtime GenAI vision/multimodal support (file 01, Inference API entry — "a vision-language model reading the receipt image directly... independent of OCR text"). Building a second, separate VLM-OCR pathway inside OCR API itself would duplicate that capability under a different name. If a receipt genuinely needs VLM-level reading, that's the Inference API's vision corroboration path, not another OCR engine here.
- **Kraken / OCRopus family** — older, narrower community/maintenance footprint than the engines already selected; no clear capability gap they'd fill that isn't already covered.

---

## 5. Hardware acceleration

Only two engines have a hardware-acceleration story worth designing for: RapidOCR (pure ONNX Runtime) and PaddleOCR (PaddlePaddle's own runtime). Everything else is either fixed by the OS (Windows OCR, Apple Vision — already GPU/NPU-accelerated transparently and not configurable from here), inherently CPU-only (Tesseract — no GPU path exists in mainline Tesseract for the LSTM engine), or server-side (the cloud tier, §4.7 — acceleration is the vendor's problem).

### 5.1 RapidOCR — ONNX Runtime execution providers
RapidOCR is just ONNX Runtime under the hood, so it inherits the same EP list already established for the Inference API's own hardware-selection design (file 02's ONNX inventory) — this reuses that existing selection mechanism rather than growing a second one:
- **CPU (MLAS)** — default, always available.
- **CUDA** — NVIDIA GPUs.
- **TensorRT** — NVIDIA GPUs, more aggressive optimization than plain CUDA, needs engine/session caching (same caveat already noted for the Inference API).
- **DirectML** — Windows-only, vendor-agnostic (AMD/Intel/NVIDIA all work through one DirectX 12 path) — a genuinely convenient default for a Windows install with an unknown GPU vendor.
- **OpenVINO EP** — Intel CPU, integrated GPU, and — where present — NPU, all through one EP.
- **CoreML EP** — Apple Silicon, routes through the Neural Engine automatically.
- **MIGraphX (AMD)** — AMD's current path; the ROCm execution provider itself was removed from ONNX Runtime as of the 1.23 release, so this isn't "ROCm or MIGraphX," it's MIGraphX now (built on top of ROCm as the underlying platform layer, the AMD analog to TensorRT-on-CUDA). Linux-first (file 02 already found Windows GPU support isn't there yet for this path, even on AMD's own flagship hardware).
- **QNN EP** — Qualcomm Hexagon NPU, relevant for Snapdragon X ARM laptops.

Fallback is per-node, not per-model (the same mechanism file 02 documented for the Inference API) — worth confirming at implementation time that RapidOCR's own wrapper actually exposes the underlying `providers=[...]` list rather than hardcoding CPU, since not every high-level OCR wrapper surfaces this.

### 5.2 PaddleOCR — a separate acceleration stack, not ONNX Runtime
PaddlePaddle has its own GPU path (`paddlepaddle-gpu`, CUDA-based) entirely independent of the ONNX Runtime EP list above — installing the GPU build is a different pip package, not a runtime flag. No DirectML/OpenVINO/CoreML equivalent exists for PaddlePaddle's own runtime (Intel maintains some Paddle-to-OpenVINO conversion tooling, but that means running a *converted* model through OpenVINO — a different engine in this design's terms, not a hardware option for the "PaddleOCR" provider itself). So PaddleOCR's hardware story is CPU or NVIDIA-GPU-via-`paddlepaddle-gpu`, full stop.

### 5.3 IPU — not a fit for this project's target hardware
"IPU" most likely means Graphcore's Intelligence Processing Unit — a real accelerator, but a datacenter/cloud product (Graphcore's own Poplar SDK, accessed via cloud instances or specialized on-prem racks), not something a self-hosted single-user or small-office install would plausibly have. There's no actively-maintained, mainstream ONNX Runtime IPU execution provider suited to a consumer/small-business deployment the way CUDA/DirectML/OpenVINO are. Worth explicitly not designing for it — it doesn't match this project's actual target hardware (the NUC-class/consumer-workstation boxes already referenced elsewhere in this plan).

### 5.4 GNA — a dead end, confirmed
Intel's Gaussian & Neural Accelerator (the thing referenced in the original Core APIs list's "GNA/IPU/GPU" note for Preprocessing hardware) is being actively discontinued by Intel: the GNA plugin is deprecated in OpenVINO, Intel's own guidance is to use the newer NPU instead, and Intel® Core™ Ultra (Meteor Lake) is documented as the last generation to include GNA hardware at all. Separately, even where GNA hardware exists, it was purpose-built for small real-time workloads like audio/speech noise suppression — Intel's own documentation is explicit that it doesn't support the 2D convolution operations computer vision models (i.e. any OCR detector/recognizer) actually need. Not viable for this API now or going forward — worth striking GNA from consideration wherever else it's mentioned in the plan, not just here.

### 5.5 NPU — the real modern successor to GNA
Where GNA was headed, NPUs are what actually arrived: low-power, always-on AI accelerators now standard on recent hardware, already reachable for RapidOCR's ONNX path through the EPs listed in §5.1 — Intel Core Ultra's NPU via the OpenVINO EP, Apple's Neural Engine via the CoreML EP (or transparently, for Apple Vision itself), and Qualcomm's Hexagon NPU via the QNN EP on Snapdragon X ARM laptops. Nothing new to build here — NPU support falls directly out of already supporting the OpenVINO/CoreML/QNN execution providers, not a fourth thing.

### 5.6 Shared hardware detection & ONNX Runtime plumbing — resolved, including the Setup API deep-dive's refinement

**A question worth answering explicitly: since RapidOCR runs on ONNX Runtime, shouldn't OCR just call the Inference API and let it serve RapidOCR as one of its own models?** At the pure runtime level, RapidOCR genuinely is ONNX inference — no technical distinction from an LLM forward pass at the `InferenceSession` layer. But "runs on the same runtime" isn't the same question as "belongs in the same API," and the two APIs are shaped for genuinely different workloads:
- **Inference API's actual contract** (file 01) is built entirely around *generative* serving: prompts, KV cache, streaming/structured-output parsing, tool-calling loops, a non-reentrant generation lock that needed a real fix in V3's design (root-caused from V2's `LLM_CALL_LOCK` stall). It's async-caller / isolated-process-generation for exactly that reason — a shared, expensive-to-load model with serialized generation.
- **OCR's engines** (RapidOCR included) are small, cheap, stateless detector/recognizer forward passes with no prompt/token concept — file 02's Concurrency Model table already puts OCR in "Native + async," a different bucket for a reason: real parallelism here comes from running many small model instances side by side, not from queuing through a generation lock built for one expensive shared model.

Folding RapidOCR into Inference API's actual RPC contract would mean every OCR read queues through machinery built to serialize LLM generation — the wrong shape for "run several small engines on one image in parallel." It would also re-blur the scope line §1 already drew (OCR ends at raw text; Inference starts after), since "Inference API literally contains the OCR engines" and "Inference API structurally comes after OCR" can't both be true cleanly.

**The resolved direction: neither API owns the other; both are clients of a shared ONNX Runtime substrate underneath both of them — now fully confirmed, including the piece that was still pending here.** Concretely:
1. **Static hardware detection** — one source of truth, owned by Setup API, confirmed in its own deep-dive (`v3-deepdive-11-setup-api.md` §5-§6): a `HardwareProfile` produced once (or on explicit re-detection), published, not re-probed per-API.
2. **A shared session/EP-selection utility** (not a domain API — generic ONNX Runtime plumbing, "how do I turn a hardware profile + a model + a caller's request into a running session with the right `providers=[...]` list") that both `core/ocr/engines/rapidocr_engine.py` and the Inference API's model-loading code call into.
3. **Live resource commitment tracking (which sessions are loaded, on which device, using how much VRAM right now) — resolved as Health API's responsibility, not Setup API's**, per Setup's own deep-dive §6: this is a continuously-queried runtime concern (checked on effectively every GPU-backed session creation), a poor fit for Setup API's one-time/rarely-invoked nature, and the same *kind* of ongoing-runtime-signal responsibility Health API already exists to host. Health's ledger reads its device list from Setup's published `HardwareProfile` rather than re-probing hardware itself — the dependency is directional, not circular.
4. **Domain logic stays fully separate regardless.** OCR API's `engine_registry.py`, `corroboration.py`, and RapidOCR-specific pre/post-processing (image input, `TextRegion` output, text normalization) stay entirely inside OCR API. The Inference API's prompt construction, tool-calling loop, and generation logic stay entirely inside Inference API. The shared substrate only ever hands back "here's a session on this device," it has no opinion about what either API does with it.

This is now fully resolved — the "merge OCR into Inference API" alternative was considered and declined, the detection/EP-plumbing piece was confirmed as originally proposed, and the live-tracking piece landed on Health API instead of Setup API after Setup's own deep-dive worked through which API's nature actually fits a continuously-queried runtime ledger. Health API's own deep-dive has since designed the ledger itself (TTL-based reservations refreshed via Watchdog's heartbeat, resolving the crash-without-releasing failure mode) — nothing left pending here.

### 5.7 Config surface
```
ocr:
  hardware:
    rapidocr_providers: [cpu]     # ordered list, e.g. [openvino, cpu] or [cuda, cpu] — fallback per-node
    paddleocr_device: cpu          # cpu | cuda
```
Device selection is per-engine, not global — a machine might reasonably want RapidOCR on an iGPU via OpenVINO while PaddleOCR (a separate runtime entirely) stays CPU-only if no CUDA GPU is present. `EngineReading.device` (§3) reports which backend actually served a given reading, for the bench suite's hardware classification. Per §5.6, the actual *values* available to pick from here (which providers exist to choose) should be populated from Setup API's shared hardware detection, not re-detected by this config layer.

---

## 6. Provider Registry & config shape

```python
# core/ocr/engine_registry.py — sketch
class OcrEngineRegistry:
    def __init__(self, cfg: OcrConfig):
        self._providers: dict[EngineName, OcrEngineProvider] = {}
        # each provider self-registers as available/unavailable at construction —
        # never a runtime crash mid-run because a dependency vanished after startup

    def available_engines(self) -> frozenset[EngineName]: ...
    def enabled_engines(self, cfg: OcrConfig) -> frozenset[EngineName]: ...  # available ∩ user-enabled
    async def run(self, request: OcrRequest) -> OcrResult: ...
```

Config surface (owned by this API, versioned like every other config per the cross-cutting "one schema, one source of truth" rule):

```
ocr:
  engines_enabled: [tesseract, rapidocr]     # PaddleOCR/Windows OCR/Apple Vision/cloud tier all opt-in, off by default (heavy/paid/platform-limited)
  tesseract:
    binary_path: "tesseract"                  # or absolute path override
    lang: "eng"
    psm: 6                                    # tunable — see §4.2, resolved via bench sweep (§11)
    omp_thread_limit: 1                        # tunable — see §4.2's OpenMP explanation
  cloud_engines:                               # shared group, see §4.7
    google_vision:
      api_key: ""                               # empty = disabled regardless of engines_enabled
      max_calls_per_run: 50
    azure_document_intelligence:
      api_key: ""
      endpoint: ""
      max_calls_per_run: 50
    aws_textract:
      access_key_id: ""
      secret_access_key: ""
      region: ""
      max_calls_per_run: 50
  per_engine_timeout_ms: 15000
```

Each engine's own sub-block lives under `ocr:` in this API's config file, not scattered — consistent with the "one schema" rule and the file-per-concern package layout.

---

## 7. Corroboration layer (`corroboration.py`)

This is the one piece file 04's wishlist explicitly left open: *"does V3 want LLM-arbitrated corroboration, real deterministic voting, or a hybrid?"* Reasoned fresh here:

### 7.1 Why not pure LLM arbitration as the default
Handing every multi-engine disagreement straight to the Inference API on every call would mean **every OCR call with 2+ engines enabled blocks on an LLM round-trip**, even for the overwhelming majority of receipts where two engines already agree byte-for-byte. That's real added latency and real added inference load for a case (unanimous agreement) that needs no arbitration at all. It also puts policy logic (Inference API's defined role in this project is explicitly "parser/corroborator," not "decide what OCR says") inside what should be a fast, cheap, deterministic path.

### 7.2 Why not pure deterministic voting either
Two OCR engines rarely disagree by producing two *different clean readings* of the same field — they disagree by garbling different characters in mostly-similar text, or one engine finding a table row the other flattened into noise. A naive "does string A equal string B" vote fails almost immediately on real receipts; even a fuzzy-match vote (`rapidfuzz` similarity threshold) can't resolve a genuine three-way split, or tell "engine A dropped a decimal point" from "engine A read a different, more correct number."

### 7.3 Decision: tiered — deterministic first, LLM escalation only on real disagreement
```
1. Normalize each reading (whitespace collapse, common OCR-noise char fixes — NOT semantic parsing, just text-level cleanup).
2. Compute pairwise similarity (rapidfuzz token_sort_ratio) across all readings.
   - All pairs above a similarity threshold → AgreementLevel.UNANIMOUS.
     merged_text = the reading from the highest-historical-accuracy engine among the agreeing set
     (a per-engine trailing accuracy score, tracked by the bench suite / Health API metrics —
     NOT a hardcoded engine ranking; this needs real measurement before any engine gets
     treated as "more trustworthy" by default).
   confidence = mean pairwise similarity.
   - Majority of pairs agree, one outlier → AgreementLevel.MAJORITY. merged_text = majority reading.
     confidence = majority-pair similarity, penalized for the outlier.
   - No majority, genuine split, OR any engine's normalized reading fails basic sanity checks
     (empty, below a minimum length, no alphanumeric content) → AgreementLevel.SPLIT.
     confidence = low, fixed floor value.
   - Single engine requested/succeeded → AgreementLevel.SINGLE_SOURCE. confidence = that
     engine's own trailing accuracy score, not a flat number — a single Tesseract reading and
     a single Cloud Vision reading shouldn't report identical confidence by default.
   - All requested engines failed → AgreementLevel.NONE. merged_text = "".
3. OCR API returns this — it does NOT call the Inference API itself. Escalating a SPLIT
   result to Inference-API-arbitrated corroboration is the CALLER's decision (matches
   §1's scope boundary: OCR API provides the primitive and the confidence signal;
   deciding what to do about low confidence is orchestration policy, same as the
   "should I ask for a second opinion at all" decision already living outside this API).
```

This keeps OCR API itself fast, dependency-light (no Inference API call in the hot path), and honest about uncertainty rather than manufacturing false certainty — directly answering the "honest confidence score beats pretending otherwise" principle this project already holds elsewhere (Inference API's corroboration-loop design), applied here at the OCR layer specifically.

**Open sub-question, not resolved here:** the per-engine trailing accuracy score needs a real home — likely a small persistent counter in Persistence, updated by whatever downstream step eventually learns ground truth (a human correction, a reconciliation match). This is a cross-API dependency (OCR API *consumes* the score, doesn't own how it's learned) worth confirming at the Reconciliation or Architect deep-dive rather than inventing a second learning mechanism here, per the standing rule that all learned/typed data belongs to Architect API.

---

## 8. gRPC surface (`.proto` sketch)

```protobuf
service OcrService {
  rpc Read(OcrReadRequest) returns (OcrReadResponse);
  rpc ListEngines(ListEnginesRequest) returns (ListEnginesResponse);  // for Interface API's settings menu — reflects actual availability, not static config
}

message OcrReadRequest {
  string run_id = 1;
  string user_id = 2;
  string blob_ref = 3;           // content-addressable hash, per Persistence API design
  repeated string engines = 4;   // EngineName values
  int32 timeout_ms = 5;
}

message OcrReadResponse {
  repeated EngineReading readings = 1;
  string merged_text = 2;
  string agreement = 3;   // enum-as-string over the wire, matches EngineReading.agreement
  float confidence = 4;
}

message EngineReading {
  string engine = 1;
  string text = 2;
  int32 duration_ms = 3;
  string error_code = 4;   // empty string = no error
  string error_detail = 5;
  repeated TextRegion regions = 6;   // empty for engines that don't support region-level output
  string device = 7;                 // "cpu", "cuda", "openvino:npu", etc. — see §5
}

message TextRegion {
  string text = 1;
  float confidence = 2;
  float box_x = 3;
  float box_y = 4;
  float box_w = 5;
  float box_h = 6;
}
```

No streaming needed for a single `Read` call (it's fast relative to Inference); the run-level "N/M receipts done" progress streaming lives at the orchestration layer, not inside OCR API's own contract.

---

## 9. Open questions for this deep-dive (logged, not guessed at)

Resolved this round: RapidOCR-vs-PaddleOCR "overlap" (§4.4 — both are independent Provider Registry entries, no special-casing), RapidOCR's per-region output (§4.3/§3 — standardized as a first-class `regions` field on every engine that supports it), Cloud Vision's auth approach (§4.7 — REST+API-key, locked), local-engine GPU acceleration (§5 — a real per-engine hardware config surface now exists), the docTR/PyTorch situation (§4.8 — dropped entirely rather than managed via a TensorFlow backend swap), Tesseract's PSM handling (§4.2 — a config knob resolved by a dedicated bench sweep, not argued to a single value here), and Tesseract's OpenMP behavior (§4.2 — capped to 1 thread per subprocess by default, overridable via config).

**Resolved, not deferred — reasoned default given, not a bench-blocked placeholder:**
- **Tesseract PSM default: `6`, confirmed reasoned rather than arbitrary.** Tesseract's own documentation names PSM 6 ("assume a single uniform block of text") as the general-purpose recommendation, and it's the closest match among the tested candidates ({3, 4, 6, 11}) to a receipt's actual layout — a genuine reason to pick it as the shipping default now, not an arbitrary placeholder. The bench sweep (§4.2/§11) still runs and can override this once real data exists; until then, this is a defensible, reasoned choice, not a blocking gap.

**Resolved — already has a real owner/mechanism, was mislabeled as open:**
- **Per-engine trailing accuracy score, owner assigned: Architect API.** Architect already owns provider/engine-adjacent reputation and taxonomy data (`v3-deepdive-26-architect-api.md`); this is the same category of "how trustworthy has this source proven to be over time" data, just for an OCR engine rather than a vendor. OCR API remains a pure consumer.
- **RapidOCR's own ONNX model currency and free-threading compatibility status of this API's native dependencies — both resolved as ongoing operational processes, not design gaps.** Both already have a real, standing mechanism: Telemetrees' own continuous tracked-dependency discipline (`v3-deepdive-28-telemetrees-api.md`), which exists specifically to catch exactly this kind of "has the upstream moved without us noticing" drift. Nothing further to design here — the mechanism doing the ongoing work already exists and owns this.

**Explicitly deferred scope, not a blocking gap:**
- **Azure/AWS receipt-specific prebuilt models** (§4.7) — whether their structured field-level output is ever worth capturing as a separate, richer signal is a real future discussion at the Matching/Reconciliation level, deliberately out of this document's own scope rather than unresolved within it.

**Implementation detail, not a design decision — moved out of open questions:**
- Tesseract's OpenMP env-var scoping mechanism (§4.2): the decision (cap to 1, configurable) is made; the exact code-level mechanism for scoping a modified environment to only the Tesseract subprocess is ordinary implementation work for the engine module, not a design fork this document needs to resolve.

Fully resolved, nothing pending: **Shared ONNX Runtime substrate across OCR and Inference APIs** (§5.6) — the ledger's actual implementation (Health API's own deep-dive: TTL-based reservations, refreshed via Watchdog's heartbeat) closed this out completely.

---

## 10. Python runtime: asyncio, free-threading, and profiling

A checklist section specifically so this doesn't get lost in implementation: where this API actually needs `asyncio`, where free-threading (no-GIL) actually matters, and how to verify either empirically rather than assume from documentation.

### 10.1 Where asyncio is load-bearing here
- `engine_registry.run()` (§6) is the async entrypoint — it fans out to every requested engine concurrently and awaits the results.
- The cloud tier (§4.8 — Google/Azure/AWS) is genuinely async I/O: real network calls, real benefit from `asyncio`/`await` instead of a blocking thread per call.
- **Every local engine (Tesseract, RapidOCR, PaddleOCR, Windows OCR, Apple Vision) is NOT internally async** — Tesseract is a subprocess call, the others are blocking C/C++-backed library calls. These get dispatched from the async `run()` entrypoint via `loop.run_in_executor(...)`, the same technique originally shared with the Inference deep-dive's `PresetWorker` — worth noting that comparison changed since: Inference's own generation was later corrected to genuine `multiprocessing.Process` workers for crash-isolation reasons (that document's §6.1), so OCR's own thread-pool dispatch here is now closer kin to Preprocessing's process-pool dispatch (its deep-dive §8.3) in *shape* (async entrypoint → blocking work dispatched off the event loop) than to Inference's own current design in *mechanism* (thread vs. process) — the underlying pattern is still the same one, just worth being precise that OCR and Inference no longer share the identical executor-thread implementation they once did.

### 10.2 Free-threading (no-GIL) — where it actually helps this API, and where it doesn't
File 02's three-bucket concurrency model already classifies OCR API's local engines as **Native/GIL-released**: Tesseract runs as a separate OS process (the parent's GIL status is irrelevant to it entirely), and RapidOCR/PaddleOCR's actual detector/recognizer compute already releases the GIL during the C/C++ work, so plain threading already achieves real parallelism for these *today*, on a standard GIL build. **This means Python 3.14t/3.15's free-threading matters less for these specific hot paths than it might seem** — the engines were never GIL-bound in the first place.

The one place OCR API has genuine CPU-bound *pure Python* work — file 02's third bucket, "No-GIL candidate" — is `corroboration.py`'s pairwise-similarity aggregation and normalization logic (§7). At this API's actual data volumes that's flagged as "negligible either way" in file 02's table, but it's still worth building `corroboration.py` to be free-threading-safe from day one (no code relying on the GIL's incidental atomicity for shared mutable state, no unguarded shared dicts/lists mutated from multiple engine-result callbacks) rather than retrofitting that discipline later — free-threaded 3.14t is now officially-supported infrastructure (PEP 779), not a research experiment, so there's no reason to write this module as if the GIL will always be there.

**A real caveat this document shouldn't let go unstated: free-threaded CPython silently re-enables the GIL for the whole process if it loads a C extension that hasn't explicitly declared free-threading safety.** Every one of OCR API's native dependencies (`onnxruntime` via RapidOCR, `paddlepaddle` via PaddleOCR, `rapidfuzz` via corroboration, `numpy`) is exactly the kind of C-extension-backed dependency this applies to. So "run this on 3.14t" doesn't automatically mean "this API now gets real free-threaded parallelism" — it depends entirely on which of those specific dependencies, at whichever specific versions are actually installed, have opted in. That's checkable at runtime (`sys._is_gil_enabled()`), but it's not a fact this document can responsibly assert as fixed, since dependency free-threading support is actively changing release to release.

**This is exactly the kind of fact Telemetrees should own, not this document.** Extend Dependencies Warden's tracked-dependency list (file 02, rule #8 — already responsible for surfacing pre-release/beta activity for tracked dependencies) to include free-threading-support status specifically, per OCR engine dependency, cross-referenced against the community compatibility tracker — surfaced to developers the same way new dependency releases already are, so this API's actual free-threading behavior is monitored continuously instead of asserted once here and left to go stale.

**Interpreter target**: this project should target Python 3.14t (free-threaded) or later for the execution core process this API runs in, as a day-0-support commitment (file 02, rule #8) applied to the interpreter itself, not just libraries. Python 3.15 (final release October 1, 2026) is worth treating as the real confidence milestone rather than 3.14 alone, since it adds a stable ABI for free-threaded builds (PEP 803) — the thing that actually lets a C-extension-heavy dependency ship one compatible wheel across free-threaded minor versions instead of needing a rebuild per version, which matters a great deal for a dependency list this reliant on native OCR engines.

### 10.3 Profiling — Tachyon and py-spy, not just reasoning from documentation
Everything in §10.2 and in §4.2's Tesseract/OpenMP discussion is architectural reasoning about where GIL contention *should* be a problem — it should be backed by actual measurement, not left as a plausible-sounding argument. Two concrete tools, both worth wiring into the bench suite (§11) rather than treated as one-off manual debugging aids:
- **py-spy** — a third-party sampling profiler that attaches to a running process by PID with no code changes needed, works across current Python versions (added explicit Python 3.14 support in its 0.4.2 release), and has a purpose-built `--gil`/`%GIL` mode for answering exactly the "which thread is actually holding the GIL right now" question the OpenMP-capping decision in §4.2 is reasoned about but never empirically confirmed. This is the practical tool to use now, pre-3.15.
- **Tachyon** (Python 3.15, PEP 799, the new `profiling.sampling` stdlib-adjacent package) — once the project is on 3.15+, this becomes the primary profiling tool for this API's bench timing work: near-zero overhead even at high sampling rates (up to 1MHz), attaches to the actual long-running execution-core process by PID without needing a restart, understands threads and async code natively, and has its own GIL-holding sampling mode. Worth treating as py-spy's eventual successor for this project rather than a parallel tool to maintain forever — but not a reason to skip wiring up py-spy now, since 3.15 isn't released yet as of this writing.

### 10.4 Lazy imports (Python 3.15, PEP 810) — a real fit for this API's heaviest optional engines, not yet applied anywhere in this project
A genuinely missed opportunity in the original version of this document, worth correcting now: PEP 810's lazy-import mechanism (`import` statements that only actually execute the import the first time a name is *used*, not at module-load time) is a strong match for this API's own dependency shape. `paddlepaddle` and `rapidocr-onnxruntime` are both multi-GB, non-trivial-import-cost dependencies — under the current design, `engine_registry.py` already checks whether each engine is enabled before dispatching to it, but nothing stops the *module-level* `import paddleocr` at the top of `paddleocr_engine.py` from paying that import cost even when PaddleOCR is disabled in config and never actually called. Lazy imports close this gap directly: the same `try: import X / except ImportError:` availability-check pattern this API already uses for graceful degradation (§4.4-4.6) stays correct, but the actual cost of a disabled engine's heavy dependency is paid only if and when that engine is genuinely invoked, not at process startup regardless of config. Worth applying to every optional engine module in `engines/`, not just PaddleOCR/RapidOCR specifically — the pattern is generic. Feature-detected the same way as every other version-sensitive capability in this project (`docs/PRINCIPLES.md` §3.3's Forward-Compatibility Pattern): on pre-3.15 Python, imports happen eagerly at module load exactly as they do today, a strictly-no-worse fallback, never a hard requirement on 3.15+. **Recommended validation once adopted: confirm on a real 3.15/3.16 interpreter that the lazy path actually defers the import, not just that the code runs without error** (`docs/PRINCIPLES.md` §3.3.1) — a feature-detection branch that never actually gets exercised locally isn't the same guarantee as one that's been run for real.

---

## 11. Testing hooks

- `tests/unit/core/ocr/` — one test module per engine, each engine's dependency mocked so the suite runs without every heavy library installed; a separate `test_corroboration.py` covering the tiered-agreement logic in isolation from any real engine.
- **PSM sweep bench case** (resolves §4.2/§9's open PSM question): a dedicated bench case, run against a small labeled sample of real receipts (ground-truth vendor/amount/date transcribed by hand), that runs Tesseract at each `psm` ∈ {3, 4, 6, 11} and scores raw-text accuracy per mode (e.g. edit-distance or keyword-recall against the labeled ground truth). Produces a simple per-mode accuracy table as bench output, feeding the `tesseract.psm` config default — not a one-time throwaway script, since it should re-run whenever the labeled sample grows or Tesseract itself is upgraded, per the bench suite's existing regression-check pattern.
- Bench suite (`tests/bench/`): OCR API is exactly the kind of real-pipeline-only, never-mocked, per-test-process-isolated case the bench suite architecture was built for — a segfault in PaddleOCR's native code should log as CRASHED for that one bench case, not take the run down, per the architecture doc's crash-isolation requirement. Empirical per-engine timing feeds the CPU/GPU/RAM classification the bench suite already produces for every setting.
- **Profiling integration** (see §10.3): the bench suite should run its OCR phases under py-spy today (GIL-holding time per thread, per engine) and switch to Tachyon once the project is on Python 3.15+, rather than leaving the OpenMP-capping and free-threading reasoning in §4.2/§10.2 as untested architectural claims.
- Failure-injection mode: a bench case that deliberately kills one engine process mid-read, confirming `corroboration.py` correctly falls back to `AgreementLevel.SINGLE_SOURCE`/`NONE` rather than the whole `Read` call failing.
