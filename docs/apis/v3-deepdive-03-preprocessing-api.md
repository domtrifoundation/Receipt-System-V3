# V3 Deep Dive: Preprocessing API

**Companion files:** `v3-plan-00-index.md` · `v3-plan-01-core-apis.md` · `v3-plan-02-architecture.md` · `v3-plan-03-decisions.md` · `v3-plan-04-v2-audit-findings.md` · `v3-deepdive-01-ocr-api.md` · `v3-deepdive-02-inference-api.md`

**Status:** Third deep-dive session. Same ground rules as the prior two: everything below is a fresh V3 decision, reasoned independently even where it lands near a V2 behavior. This deep-dive also closes a gap the OCR deep-dive left implicit (§1) and resolves the original "transcoding engine / GNA / IPU / GPU" open question from file 03 with real research rather than leaving it open indefinitely (§6).

---

## 1. Scope & boundary

Preprocessing API's job: given a single ingested file (a PDF page or an image), produce a **rasterized base image**, and on request, one or more **processed variants** of it for OCR API to read. It does not:
- **decide which variants a weak OCR reading needs** — same boundary OCR API drew for "should this receipt get a second opinion." That policy (is the standard variant good enough, or does this receipt need the full sweep) lives in the orchestrator, not in Preprocessing API.
- **read or interpret image content** — that's entirely OCR API's job; Preprocessing only transforms pixels, never looks at what they say.
- **decide OCR accuracy** — Preprocessing doesn't know or care whether a variant it produced actually helped a downstream OCR reading; that feedback loop (which variant kinds are worth generating by default) is a bench-measured, config-driven decision fed back from outside this API, not something Preprocessing evaluates itself.

Same shape as the prior two APIs: a **pure transformation capability provider**. Caller picks which variants it wants; Preprocessing produces them and reports what it did, nothing more.

**A gap this closes rather than a correction**: the OCR deep-dive's `OcrRequest` contract takes an `image_ref` — already-rasterized image data — without ever naming who actually turns a PDF page into that image. That was left implicit there. **Preprocessing API is the explicit, natural owner of rasterization** — it's the very first transformation step in the pipeline, structurally identical in kind to every other transformation this API does (turn one image representation into another), so folding PDF→image rendering in here rather than inventing a separate concern for it is the cleaner design, not an afterthought.

---

## 2. Package layout

```
core/preprocessing/
  __init__.py
  contracts.py           # RasterRequest, RasterResult, VariantRequest, VariantResult, VariantKind enum, error types
  service.py               # thin gRPC service implementation, delegates everything
  raster.py                 # PDF/image ingestion → base raster image, adaptive re-render, see §5
  variant_registry.py       # Provider Registry: which variant kinds exist, which are enabled
  variants/
    __init__.py
    base.py                  # VariantGenerator protocol
    tonal_variants.py         # grayscale/autocontrast, B&W threshold, low/high contrast — see §4.1-4.3
    channel_variants.py       # per-channel (R/G/B) boost — see §4.4
    geometry_variants.py      # deskew/rotation correction — see §4.5, new for V3
    denoise_variants.py       # denoise — see §4.6, candidate/opt-in
  generation.py              # ProcessPoolExecutor dispatch, batching, see §8
  hardware.py                # OpenCL/UMat device selection, see §6
  errors.py                  # RasterFailed, VariantGenerationFailed, UnsupportedFormat, etc.
  metrics.py                  # per-variant timing, feeds Health API and the bench suite
```

Same discipline as the prior two deep-dives: `contracts.py` is the only file other APIs import from.

---

## 3. Data contracts (`contracts.py`)

```python
class VariantKind(str, Enum):
    STANDARD = "standard"                 # grayscale + autocontrast — the safe default, see §4.1
    BW_THRESHOLD = "bw_threshold"          # Otsu binarization, see §4.2
    LOW_CONTRAST = "low_contrast"
    HIGH_CONTRAST = "high_contrast"        # CLAHE, see §4.3
    CHANNEL_BOOST_RED = "channel_boost_red"
    CHANNEL_BOOST_GREEN = "channel_boost_green"
    CHANNEL_BOOST_BLUE = "channel_boost_blue"
    COLOR = "color"                        # unmodified color pass-through, kept as a named kind for uniform handling
    DESKEW = "deskew"                      # new for V3, see §4.5
    DENOISE = "denoise"                    # candidate/opt-in, see §4.6

@dataclass(frozen=True)
class RasterRequest:
    run_id: str
    user_id: str
    source_ref: BlobRef          # the original ingested file — PDF or image, content-addressable
    page_index: int = 0           # ignored for non-PDF sources
    scale: float = 2.5             # render scale/DPI-equivalent — see §5.2

@dataclass(frozen=True)
class RasterResult:
    image_ref: BlobRef            # the rendered/decoded base image — feeds VariantRequest and OCR API directly
    width: int
    height: int
    duration_ms: int
    device: str                   # "cpu" — rasterization itself isn't GPU-accelerated in this design, see §6.3
    error: PreprocessingError | None = None

@dataclass(frozen=True)
class VariantRequest:
    run_id: str
    user_id: str
    image_ref: BlobRef            # a RasterResult's image_ref, or any other already-rasterized image
    kinds: frozenset[VariantKind]  # caller's choice, not policy — same convention as OCR API's `engines` field
    device_preference: str = "auto"  # "auto" | "cpu" | "opencl" — see §6

@dataclass(frozen=True)
class Variant:
    kind: VariantKind
    image_ref: BlobRef
    duration_ms: int
    device: str
    error: PreprocessingError | None = None   # populated + image_ref unset on failure — same "errors are data" convention as OCR/Inference

@dataclass(frozen=True)
class VariantResult:
    variants: tuple[Variant, ...]   # one entry per requested kind, success or failure, always present — same non-silent-drop convention as OCR API's OcrResult.readings
```

---

## 4. Variant techniques — dependency, technique, and the fixed-vs-parametric decision

### 4.0 Dependency and library choice — OpenCV over PIL, reconfirmed with real evidence, not just asserted
File 02's own concurrency classification already treats this API's operations as OpenCV-based ("OpenCV ops are native..."), which this deep-dive adopts and now backs with concrete reasoning rather than leaving implicit: **`opencv-python` (`pip install opencv-python`) is the primary library, not PIL/Pillow.**

**Is this still the right call? Checked, not just assumed — yes, for three independent reasons plus one confirmed fact worth stating explicitly:**
1. **A real hardware-acceleration story** (§6) PIL doesn't have at all.
2. **A more sophisticated technique set** this design actually wants: Otsu thresholding, CLAHE, contour-based deskew (§4.2, §4.3, §4.5) — PIL either lacks these outright or only crudely approximates them.
3. **Shared `numpy`-array interop** with RapidOCR/PaddleOCR on the OCR side, reducing conversion overhead at the OCR API boundary.
4. **A confirmed, easy-to-miss fact that strengthens the case further**: the standard `opencv-python` pip wheel ships with **Intel's IPP-ICV** — a free, redistributable subset of Intel's Integrated Performance Primitives — **enabled by default on supported platforms**, no configuration or separate install needed. This gives real SIMD-accelerated (AVX2/SSE4.x) CPU speedups on roughly 700+ common OpenCV functions out of the box (Intel's own published figures cite ~40% overall improvement on affected functions vs. a non-IPP build) — meaning a plain `pip install opencv-python` already carries a real, free CPU performance advantage most people don't realize they're getting, well before UMat/OpenCL (§6.1) ever enters the picture. Worth knowing this exists rather than assuming all the acceleration story requires explicit GPU configuration.

**Alternatives genuinely considered and why they lose:**
- **`libvips`** — legitimately faster than OpenCV for simple, large-image throughput (streaming/tile-based architecture, very low memory footprint), but its operation set is thinner for the specific techniques this design wants (no CLAHE, weaker thresholding/contour support), and it would mean maintaining two image libraries instead of one for marginal gain at receipt-photo sizes (a few megapixels, not the large-scale batch thumbnailing workloads where `libvips`'s architecture really pays off).
- **`pillow-simd`** — a drop-in accelerated fork of Pillow, but it's PIL-shaped (same operation set limitations as §4.0's original PIL objection) and, more practically, has a history of lagging behind mainline Pillow releases and limited platform wheel coverage — a real maintenance-risk trade against OpenCV's broader, more actively-maintained wheel matrix.
- **`scikit-image`** — excellent for algorithm *research* (many techniques available as clear, readable reference implementations) but not built for production throughput the way OpenCV is; worth keeping in mind as a place to prototype a new technique before porting it to OpenCV, not as the production dependency.

Nothing here overturns the OpenCV decision — if anything, the confirmed IPP-by-default finding makes it a stronger call than it looked before checking. PIL/`Pillow` remains available as a lightweight fallback for trivial format handling where OpenCV's format support is thin (see `pillow-heif` note, §5.3), not as the primary transformation engine.

### 4.1 STANDARD — grayscale + autocontrast
```python
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
# OpenCV has no direct PIL-autocontrast equivalent; a percentile clip + normalize
# is the standard technique for the same effect (stretch the histogram to use
# the full 0-255 range, clipping extreme outlier pixels rather than the true min/max)
lo, hi = np.percentile(gray, (1, 99))
stretched = np.clip((gray.astype(np.float32) - lo) * 255.0 / max(hi - lo, 1e-6), 0, 255).astype(np.uint8)
```
This is the safe default input handed to OCR engines that don't do their own adaptive binarization (§4 of the OCR deep-dive already notes Tesseract's own Otsu step handles uneven lighting better than aggressive preprocessing done *before* it sees the image — this variant stays deliberately mild for exactly that reason, matching the restraint the OCR deep-dive already argued for).

### 4.2 BW_THRESHOLD — Otsu binarization, not a fixed magic number
```python
_, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
```
A genuine improvement worth naming as such: Otsu's method computes the optimal binarization threshold *per image* from its own histogram, rather than using a single fixed threshold value picked once and applied to every receipt regardless of lighting — a real, principled difference from a hardcoded cutoff, not a stylistic preference. **This isn't redundant with Tesseract's own internal Otsu step** (OCR deep-dive §4.2) — this variant exists as an independent estimate computed *before* any OCR engine runs, useful for the engines in the enabled set that don't do their own adaptive thresholding (RapidOCR/PaddleOCR's detector models expect a more standard input range and don't binarize internally the way Tesseract does).

### 4.3 LOW_CONTRAST / HIGH_CONTRAST — CLAHE over a flat multiplier
```python
# HIGH_CONTRAST: Contrast Limited Adaptive Histogram Equalization — operates on
# local neighborhoods rather than the whole image at once, so it doesn't blow
# out already-bright regions while boosting genuinely dim ones. A meaningfully
# better fit than a single flat contrast multiplier for a photographed receipt
# with uneven lighting across its length (a common, real failure mode for phone
# photos, distinct from a flatbed scan).
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
high_contrast = clahe.apply(gray)

# LOW_CONTRAST stays a simple linear scale (cv2.convertScaleAbs with alpha < 1)
# — deliberately the "opposite direction" variant, not CLAHE-tuned-down, since
# its purpose is different: recovering text on receipts that are already
# over-exposed/blown-out, where CLAHE's local adaptivity doesn't help.
low_contrast = cv2.convertScaleAbs(gray, alpha=0.6, beta=0)
```

### 4.4 CHANNEL_BOOST_RED/GREEN/BLUE
```python
b, g, r = cv2.split(img)          # OpenCV's native channel order is BGR, not RGB — an easy, real mistake to make porting from PIL, worth flagging explicitly
boosted_r = cv2.convertScaleAbs(r, alpha=1.6, beta=0)
# ...same for g, b — each produces its own single-channel variant image
```

### 4.5 DESKEW — new for V3, a real gap V2's fixed set never addressed
V2's 8-variant sweep (color, standard, B&W threshold, low/high contrast, boosted R/G/B — file 04's audit findings) never included any rotation correction at all. Worth naming as a genuine, well-reasoned addition rather than scope creep: this project's actual input medium is predominantly **phone photos of receipts**, not flatbed scans — a tilted receipt in-frame is an extremely common, real failure mode a fixed contrast/color sweep does nothing to address, and skew measurably hurts OCR accuracy independent of any tonal issue.
```python
# Contour-based skew estimation: threshold, find the largest contour
# (the receipt itself against the background), fit a minimum-area
# bounding rectangle, use its angle to correct rotation.
_, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
largest = max(contours, key=cv2.contourArea)
angle = cv2.minAreaRect(largest)[-1]
# minAreaRect's angle convention needs normalizing to a -45..45 range
# before use — a well-known OpenCV gotcha, not a trivial pass-through
if angle < -45:
    angle = 90 + angle
h, w = gray.shape
M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
deskewed = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
```
An alternative technique — Hough-line-based skew detection (find dominant near-horizontal text lines via `cv2.HoughLinesP`, use their average angle) — is worth bench-comparing rather than assumed superior (§12); contour-based is the simpler default to start from since receipts photographed against a contrasting background/table surface give a clean outer contour to work from, but this assumption should be checked against real photos, not just reasoned about.

### 4.6 DENOISE — a candidate, not a default
```python
denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
```
Genuinely useful for grainy/low-light phone photos, but `fastNlMeansDenoising` is one of the more expensive classical CV operations in this set — worth keeping off by default and opt-in via config, with a real cost figure from the bench suite (§12) before ever defaulting it on, rather than assuming it's worth its cost.

### 4.7 The fixed-vs-parametric question, resolved
File 04's wishlist explicitly left this open: "does V3 want a similarly bounded fixed variant set, a different fixed set, or a generated/parametric approach?" **Decision: a fixed, named set (§4.1-4.6, mirroring V2's proven categories where they were genuinely useful, dropping none, adding deskew as a real gap) plus a documented extension point, not an unbounded parametric sweep.** Reasoning: a named, fixed set has a clear Provider-Registry-shaped config surface (each kind independently enableable, each kind's actual win-rate bench-measurable in isolation — §12), while a fully parametric approach (continuously sweeping threshold/contrast/CLAHE-clip-limit values) has an unbounded cost surface with no current evidence it's needed over well-chosen fixed presets. If bench data ever shows a specific fixed variant's parameters are meaningfully wrong for this project's actual receipts, the fix is tuning that variant's constants (already config-exposed, §7), not building a general parametric search engine speculatively.

---

## 5. Ingestion & rasterization (`raster.py`)

### 5.1 PDF rendering
```python
import fitz  # PyMuPDF, pip install pymupdf
doc = fitz.open(source_path)
page = doc[page_index]
pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
```
Owns what was previously left unassigned in the OCR deep-dive (§1) — every OCR engine now receives an already-rasterized `image_ref` and never touches PDF rendering itself, closing the real risk of N OCR engines each independently re-rasterizing the same PDF page at slightly different scales as redundant, duplicated work.

### 5.2 Adaptive scale — moved here from being implicit in OCR's own extractor logic
The "render fast at a lower scale first, only re-render at full scale if the fast pass looks weak" technique belongs here as a `RasterRequest` retry primitive (a second `Rasterize` call at a higher `scale` value), parameterized and callable by whatever orchestrator decided a fast pass wasn't good enough — not duplicated per-OCR-engine logic. This is a direct, explicit consequence of §1's scope-gap closure: since Preprocessing now owns rasterization exclusively, the scale-retry decision naturally centralizes here too instead of needing to live inside each OCR engine that used to do its own rendering.

### 5.3 Raw image inputs
- Standard formats (JPEG, PNG, BMP, WebP): `cv2.imread`/`cv2.imdecode` — OpenCV's built-in codec support, backed by `libjpeg-turbo` for JPEG (SIMD-accelerated CPU decode, already fast enough that hardware transcode acceleration isn't worth pursuing at this workload's volume — see §6.3).
- **HEIC/HEIF — a real, easily-forgotten gap**: OpenCV does **not** support HEIC out of the box. Given this project's actual target medium is phone photos of receipts, and iPhones default to saving photos as HEIC, this isn't an edge case — worth an explicit dependency: `pip install pillow-heif`, registered as a Pillow plugin (`pillow_heif.register_heif_opener()`) so `PIL.Image.open()` handles `.heic`/`.heif` files, then converted to a numpy array for the rest of the OpenCV-based pipeline to consume. This is exactly the kind of concrete, specific dependency that's easy to miss when reasoning about "image preprocessing" in the abstract and only remembered once someone actually tries to process an iPhone photo.

---

## 6. Hardware acceleration — resolving the original open question

File 03's Open Questions Log states this plainly: *"Preprocessing hardware acceleration path: transcoding engine vs. GNA vs. IPU vs. GPU — needs research pass on what's actually available/practical."* Resolved here, concretely, rather than left open another session.

### 6.1 GPU — OpenCV's Transparent API (UMat/OpenCL), the practical default
OpenCV has had built-in OpenCL acceleration since version 3.0 via the **Transparent API (T-API)**: convert a `cv2.Mat`-equivalent numpy array to `cv2.UMat`, and the *same* function calls (`cv2.threshold`, `cv2.cvtColor`, `cv2.warpAffine`, etc.) automatically dispatch to an OpenCL-capable device when one's present, falling back to the CPU path transparently when it's not or when a given op has no OpenCL implementation — no separate GPU-specific code path to maintain, no per-op fallback logic to write. Critically, **this ships in the standard `opencv-python` pip wheel** — no custom build required — and it's vendor-agnostic (works on Intel/AMD/NVIDIA integrated or discrete GPUs alike, anything with an OpenCL driver), which is exactly the profile this project's actual target hardware (NUC-class boxes, laptops with varied iGPUs) needs. **Decision: UMat/OpenCL is the default GPU path.**
```python
img_u = cv2.UMat(img)          # subsequent cv2 calls on img_u transparently use OpenCL when available
result = cv2.threshold(img_u, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
```

### 6.2 CUDA — available, deliberately not the default
OpenCV also has a dedicated CUDA module (`cv2.cuda_GpuMat` and a parallel set of `cv2.cuda.*` functions), NVIDIA-only. **It requires a custom-compiled OpenCV build** (`opencv-contrib-python` compiled with `WITH_CUDA=ON`) — this is **not** available in the standard pip wheel, a real, meaningful extra-install cost. Consistent with this project's existing bias toward options that work without a special/heavy build (the same reasoning that chose REST-over-SDK for OCR API's cloud engines), **UMat/OpenCL stays the default and CUDA stays an explicit opt-in** for anyone willing to take on a custom OpenCV build for the extra edge on NVIDIA hardware specifically — not something this API assumes or auto-detects into.

### 6.3 "Transcoding engine" — Intel's actual media stack, named specifically and checked properly
**Scope note first**: this section is about accelerating *this API's own* image decode (§5.3) — it is not about archival storage codec re-encoding (WebP/AVIF for the long-term blob store), which file 01 explicitly assigns to **Ingestion's Format Normalization**, a different pipeline stage. That question has its own real answer (AV1 hardware encode, gated to fairly recent hardware across Intel/AMD/NVIDIA; no vendor has a WebP hardware encoder; a content-addressing design that hashes the original bytes rather than the current stored encoding is what makes safe opportunistic re-compression possible) — worth a dedicated Ingestion API deep-dive rather than folding into this document's scope.

File 03's original entry almost certainly meant a specific, real Intel technology, not a vague generic concept — worth naming it rather than gesturing at "hardware decode exists": **Intel Media SDK / oneVPL, now rebranded Intel® Video Processing Library (Intel® VPL)**, accessed via the `libmfx` C API. This is genuinely relevant-sounding at first glance — its VPP (video pre-processing) filter set includes **Denoise, Resize, and Rotate**, which directly overlap with variant kinds this API already wants (§4.5, §4.6), plus hardware-accelerated JPEG decode/encode. Checked properly rather than dismissed on vibes alone, here's why it's still not the right fit for this API, for three concrete reasons:
1. **No Python bindings.** `libmfx` is a plain C API — using it from this project means writing a C extension or a `cffi`/`ctypes` wrapper from scratch, a real, ongoing maintenance cost for a single-vendor benefit.
2. **Intel-only, with real platform/driver requirements.** The modern oneVPL GPU runtime needs Iris Xe-generation graphics or newer (older Gen graphics fall back to the legacy, no-longer-actively-developed Media SDK runtime); Linux needs the VAAPI + Intel media-driver stack installed and configured, Windows needs the matching Intel graphics driver version. None of this is a problem for a dedicated Intel-hardware deployment, but it's a real, asymmetric integration cost against AMD/NVIDIA/Apple Silicon machines this project also needs to run on.
3. **Built for video frame-rate throughput, not a handful of receipt photos.** oneVPL's own sample tooling reports performance in frames-per-second for continuous video streams — the entire API surface (session/frame-surface lifecycle, async frame processing, dispatcher/runtime selection) is machinery sized for that workload. Decoding and lightly processing a handful of receipt images per run doesn't approach the volume where that machinery's overhead pays for itself; `libjpeg-turbo`'s SIMD CPU decode (§5.3, already what OpenCV's `imread` uses) is already comfortably fast enough at this scale.

**Resolved: real technology, correctly understood, deliberately not adopted** — worth remembering as a genuine escape hatch specifically for its VPP Denoise/Resize/Rotate filters if a future *bulk* reprocessing scenario (re-running a large historical archive) ever makes raw per-image processing throughput a measured bottleneck on Intel-only fleets specifically, but not a default-path dependency now.

### 6.4 GNA — a dead end, same reasoning as OCR/Inference, not re-derived here
Already fully argued in the OCR deep-dive (§5.4-5.5): Intel is actively discontinuing GNA in favor of NPU, and GNA was purpose-built for small real-time audio workloads, never supporting the 2D convolution operations any image-processing pipeline needs. Same dead end, same reasoning, not repeated here.

### 6.5 IPU — this needed a correction, and it's worth explaining why
The OCR deep-dive's own IPU treatment (§5.4 there) discussed **Graphcore's** Intelligence Processing Unit — a datacenter accelerator, correctly ruled out for that API. But re-examining file 03's original phrasing here — *"transcoding engine / GNA / IPU / GPU"*, four items listed together — makes a different reading far more likely for **this** API specifically: those are plausibly all **Intel on-die accelerator blocks**, listed as a set precisely because Intel's own processor datasheets group them together this way (the same datasheet table-of-contents literally lists "Intel® GMM and Neural Network Accelerator (Intel® GNA)" directly alongside "Intel® Image Processing Unit (Intel® IPU6)," alongside the media/transcode engine and the integrated GPU, as the SoC's fixed-function block family). Under that reading, "IPU" here means **Intel's own Image Processing Unit (current generation: IPU6)** — a real, distinct piece of hardware from Graphcore's IPU, and worth its own honest treatment rather than reusing the Graphcore answer by assumption.

**What Intel's IPU actually is**: a camera image-signal-processor (ISP) block that sits between a physically-attached MIPI/CSI-2 camera sensor and the OS, doing the raw-sensor-data → finished-image pipeline (demosaicing, HDR, temporal denoising, exposure handling) *at capture time*, before an image ever becomes a JPEG/HEIC file. It's the hardware behind modern Intel laptops' built-in webcams specifically, requires proprietary firmware and a real driver stack (`intel-ipu6`, a userspace HAL, on Linux notoriously difficult to get working — still an active pain point in kernel/driver support as of recent kernel cycles), and is accessed through camera-capture APIs (V4L2 on Linux, the Windows camera stack), not a general-purpose image-processing library call.

**Why it's a dead end for this API specifically, and the reason is cleaner than GNA/Graphcore's-IPU's**: this API processes **already-captured, already-encoded image files** arriving via file ingestion (a phone photo, a PDF page) — there's no live camera sensor anywhere in this pipeline for Intel's IPU to sit between. It's not a matter of the hardware being deprecated or underpowered (unlike GNA) or datacenter-only (unlike Graphcore's IPU) — it's that Intel's IPU solves a *different problem* (processing a live sensor feed at capture time) than the one this API has (post-hoc processing of a finished file someone already captured, possibly on a completely different device days or weeks earlier). Worth stating this precisely rather than lumping it in with the other dead ends for the wrong reason.

### 6.6 NPU — an honest "doesn't apply," not a gap
Worth stating explicitly rather than silently skipping, since the pattern of checking every accelerator category was established for OCR/Inference: NPUs are built for neural-network inference (low-precision matrix multiply-accumulate at scale), not classical computer-vision filter operations (thresholding, contrast, color-space conversion, affine warps). Preprocessing API's techniques (§4) are all classical CV, not learned models — there's genuinely no NPU story here, and that's a correct, honest answer, not an unresolved gap.

### 6.7 Participation in the shared hardware substrate (OCR §5.6 / Inference §8.6) — resolved, including Setup API's detection/tracking split
Preprocessing's OpenCL/UMat resource domain is genuinely different from OCR/Inference's ONNX Runtime execution-provider world, so it doesn't need to share *their* session/EP-selection utility directly. It should, however, consume the **same underlying static hardware-detection facts** from Setup API's `HardwareProfile` (confirmed in Setup's own deep-dive, `v3-deepdive-11-setup-api.md` §5-§6) — extend that published profile to include OpenCL device availability alongside the ONNX-EP-relevant facts already planned there, rather than this API re-probing hardware independently a third time. Live resource coordination — resolved by Setup's own deep-dive as **Health API's job, not Setup API's**, since a live ledger is a continuously-queried runtime concern Setup's one-time/rarely-invoked nature doesn't fit — matters less urgently here regardless of which API hosts it: UMat's OpenCL buffers are small and short-lived per-image, not a persistent multi-GB model load, so **Preprocessing should register lightweight usage with Health API for visibility, but doesn't need to participate in the live reservation ledger with the same urgency** OCR/Inference's deep-dives flagged for themselves.

---

## 7. Provider Registry & config shape

```
preprocessing:
  raster:
    default_scale: 2.5
    adaptive_scale_enabled: false
    adaptive_fast_scale: 2.0        # moved here from the OCR deep-dive's implicit assumption, see §5.2
  variants_enabled: [standard, bw_threshold]   # low_contrast/high_contrast/channel_boost_*/deskew/denoise opt-in
  bw_threshold: {}                    # Otsu is parameter-free by design — no threshold value to configure
  high_contrast:
    clahe_clip_limit: 2.0
    clahe_tile_grid_size: [8, 8]
  low_contrast:
    alpha: 0.6
  channel_boost:
    alpha: 1.6
  deskew:
    method: contour                    # contour | hough — see §4.5, bench-decided which is default
  denoise:
    enabled: false
    h: 10
  hardware:
    device_preference: auto            # auto | cpu | opencl — see §6.1-6.2
  worker_pool_size: 0                   # 0 = auto-detect from Setup API's hardware profile, see §8.2
```

---

## 8. Concurrency — multiprocessing, and precisely why (not threading)

File 02 already settles this: Preprocessing's model is **Multiprocessing**, specifically because "OpenCV's free-threaded wheels aren't ready yet." Worth spelling out the full reasoning rather than treating that line as sufficient on its own, since OCR API's engines *do* get real parallelism from threading despite also being native/GIL-releasing code — the two APIs aren't actually inconsistent, but the reason deserves to be explicit:

### 8.1 Why threading doesn't cleanly work here the way it does for OCR
Tesseract (OCR API) is a **separate OS subprocess** — the calling thread just waits, GIL released for the *entire* call, nothing else to consider. RapidOCR/PaddleOCR are single blocking library calls per engine invocation, GIL released for their duration. **Preprocessing's variant generation is different in kind**: producing one variant is typically a short *chain* of several OpenCV calls (convert color space → compute stats → threshold/enhance → maybe warp) with real Python-level orchestration between each step (numpy array handling, metadata bookkeeping) — more opportunities for GIL-holding overhead to eat into the parallelism gap than a single big blocking call has. Multiprocessing sidesteps this cleanly by giving each variant-generation task a genuinely separate process, real parallelism regardless of exactly how much of any given step happens to hold the GIL.

### 8.2 Confirmed, current blocker for the free-threading alternative
Separately, and worth citing concretely rather than gesturing at "not ready yet": `opencv-python` **does not currently build or install at all** under Python's free-threaded (`3.14t`) build — a confirmed, actively-tracked upstream gap (`opencv/opencv#27933`, with a build-fix PR tracked in `opencv-python#1051`, still open as of this writing). So free-threading isn't just "not yet optimal" for this API — it's not currently a usable alternative to multiprocessing at all, on top of the threading-shape argument in §8.1. **Multiprocessing is the correct choice on every axis available today**, not a stopgap waiting on a single blocker to clear.

### 8.3 Concrete mechanism
```python
# core/preprocessing/generation.py — sketch
class VariantExecutor:
    def __init__(self, worker_count: int):
        self._pool = ProcessPoolExecutor(max_workers=worker_count)   # sized from Setup API's core-count profile, see §7

    async def generate(self, request: VariantRequest) -> VariantResult:
        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(self._pool, _generate_one_variant, request.image_ref, kind, request.device_preference)
            for kind in request.kinds
        ]
        variants = await asyncio.gather(*futures, return_exceptions=False)  # each worker function catches internally, returns a Variant with .error set — never raises across the executor boundary, same non-throwing convention as OCR/Inference
        return VariantResult(variants=tuple(variants))
```
Same `loop.run_in_executor(...)` technique as OCR API's engine dispatch — the second instance of the identical async-dispatch-to-blocking-work pattern, just backed by a process pool here instead of a thread pool, for the reasons in §8.1-8.2. (Inference API's own `PresetWorker` was originally a third instance of this same thread-pool pattern, but its own deep-dive later corrected that to genuine `multiprocessing.Process` workers for crash-isolation reasons — see that document's §6.1 — meaning Inference is actually a closer cousin to *this* API's process-pool approach than to OCR's thread-pool one at this point, not a peer example of the thread-pool case anymore.)

### 8.4 The real multiprocessing pitfall worth naming explicitly: don't pickle images across the process boundary
`ProcessPoolExecutor` pickles function arguments to send them to worker processes by default — passing a full-resolution image array directly would mean serializing/deserializing potentially several megabytes per variant request, a genuine and easy-to-miss performance trap. **Decision: pass `image_ref` (the content-addressable blob reference) across the process boundary, not image bytes** — each worker process loads the image itself from the blob store using the reference, exactly mirroring how `RasterRequest`/`VariantRequest` already pass `BlobRef`s rather than raw bytes everywhere else in this design (§3). This isn't a new convention invented for the process-pool case — it's the existing content-addressable-reference pattern already used throughout, which happens to also be exactly the right fix for multiprocessing's pickling cost.

### 8.5 A future alternative worth tracking, not building on yet: PEP 734 subinterpreters
Python 3.14 stabilized **PEP 734** (multiple interpreters within a single process, each with its own GIL — or no GIL, on a free-threaded build). This is a genuinely different axis from free-threading: a C extension doesn't need to declare *free-threading* safety to work inside a subinterpreter, it needs to declare *multi-interpreter* safety instead (a distinct compatibility flag) — meaning OpenCV could, in principle, work cleanly across subinterpreters well before it ever resolves its free-threaded-build blocker (§8.2). Subinterpreters would give process-like isolation without multiprocessing's IPC/pickling overhead (§8.4) — a real, promising future replacement for the `ProcessPoolExecutor` design above. **Not adopted now**: OpenCV's actual subinterpreter compatibility is unconfirmed as of this writing, and building on an unverified compatibility axis would repeat the exact mistake of assuming a dependency's threading story instead of checking it. Logged as an open question (§12) and a Telemetrees tracking candidate (§9), not a current design.

---

## 9. Asyncio, free-threading, and profiling

Matching the dedicated treatment both prior deep-dives gave this topic, tuned to what's actually true for this API.

### 9.1 Where asyncio is load-bearing
`VariantExecutor.generate()` (§8.3) and `raster.py`'s rasterization entrypoint are the async surface — both just fan out to blocking work via `run_in_executor`, backed by a process pool rather than a thread pool for the reasons in §8. Large-PDF rasterization is the one place genuine disk I/O waiting could matter, though at this API's actual receipt-scale inputs it's a minor concern, not a driving design constraint the way it is for, say, Persistence's SQLite wrapper.

### 9.2 Free-threading — narrower relevance here than for OCR or Inference
Since this API is already committed to multiprocessing for real, confirmed reasons (§8.1-8.2) rather than threading, Python's free-threaded build doesn't change this API's *current* design the way it might for a thread-based API — there's no thread pool here whose effectiveness depends on free-threading status. Where it *would* matter is if/when `opencv-python`'s free-threaded-build blocker (§8.2) clears and a future redesign wants to reconsider threading (or subinterpreters, §8.5) over multiprocessing to avoid IPC overhead — at that point, the same silent-GIL-re-enable caveat the OCR and Inference deep-dives both raised applies identically to OpenCV as a C-extension-backed dependency.

**Telemetrees ownership, consistent with the prior two deep-dives**: track `opencv-python`'s free-threaded-wheel status specifically via the open upstream issue (`opencv/opencv#27933`) as a Dependencies Warden entry (file 02, rule #8) — this is the concrete trigger condition for ever revisiting §8's multiprocessing decision, not a vague "check back later." Also track `pymupdf` and `pillow-heif`'s free-threading status, and OpenCV's subinterpreter (PEP 734) compatibility specifically as a separate tracked fact from its free-threading status (§8.5) — they're genuinely different compatibility axes and shouldn't be conflated into one tracked line item. **Once any of these actually clears, validate on the real 3.15/3.16 interpreters** (`docs/PRINCIPLES.md` §3.3.1) before treating the redesign as safe to build — the tracked fact clearing is the trigger to *check*, not a substitute for checking.

### 9.3 Profiling — the same tools, aimed at process-pool-specific questions
- **py-spy**: usable now, same as the prior two deep-dives — but worth noting its process-following behavior specifically matters here, since this API's actual parallelism lives in worker *processes*, not threads within one process the way OCR/Inference's profiling questions were framed. Confirm py-spy's child-process-following support against the currently-pinned py-spy version before relying on it for this API's bench work, rather than assuming feature parity with how it's used in the other two deep-dives' single-process thread-pool cases.
- **Tachyon** (Python 3.15, `profiling.sampling`, PEP 799): same eventual role as in the prior two deep-dives — attaches by PID, but again, this API's real work happens in separate worker processes, so profiling needs to target the worker processes specifically, not just the main execution-core process the other two APIs' hot paths run inside of.
- Both belong in the bench suite (§12), turning §8's multiprocessing-vs-threading reasoning into measured fact rather than an architectural argument alone — same principle stated in both prior deep-dives, repeated here because it's equally true.

---

## 10. gRPC surface (`.proto` sketch)

```protobuf
service PreprocessingService {
  rpc Rasterize(RasterizeRequest) returns (RasterizeResponse);
  rpc GenerateVariants(GenerateVariantsRequest) returns (GenerateVariantsResponse);
  rpc ListVariantKinds(ListVariantKindsRequest) returns (ListVariantKindsResponse);  // for Interface API's settings menu
}

message RasterizeRequest {
  string run_id = 1;
  string user_id = 2;
  string source_blob_ref = 3;
  int32 page_index = 4;
  float scale = 5;
}

message RasterizeResponse {
  string image_blob_ref = 1;
  int32 width = 2;
  int32 height = 3;
  int32 duration_ms = 4;
  string device = 5;
  string error_code = 6;
  string error_detail = 7;
}

message GenerateVariantsRequest {
  string run_id = 1;
  string user_id = 2;
  string image_blob_ref = 3;
  repeated string kinds = 4;        // VariantKind values
  string device_preference = 5;     // "auto" | "cpu" | "opencl"
}

message GenerateVariantsResponse {
  repeated Variant variants = 1;
}

message Variant {
  string kind = 1;
  string image_blob_ref = 2;
  int32 duration_ms = 3;
  string device = 4;
  string error_code = 5;
  string error_detail = 6;
}
```
No streaming needed — same reasoning as OCR API's `Read` call: variant generation for one image is fast relative to the run-level progress streaming that already exists at the orchestration layer.

---

## 11. Testing hooks

- `tests/unit/core/preprocessing/` — each variant generator tested against small synthetic images with known expected properties (e.g. a synthetic checkerboard confirms `BW_THRESHOLD`'s Otsu output actually binarizes at a sane split, a synthetically-rotated test image confirms `DESKEW` recovers a known angle within tolerance) — mocked/synthetic, no real receipt images needed for unit-level correctness checks.
- **OCR-accuracy-improvement bench case**: the same bench-driven-decision pattern the OCR deep-dive used for its PSM sweep, applied here — run a labeled real-receipt sample through each enabled variant kind, feed each variant into OCR API, and measure actual accuracy delta versus the `STANDARD` baseline. This is what actually resolves §4.7's fixed-set membership question with evidence: a variant kind that never measurably helps on this project's real receipts is a candidate to drop from the default-enabled set, regardless of how principled its technique sounds in isolation.
- **Deskew method bench case**: contour-based vs. Hough-line-based (§4.5), compared on real photographed (not scanned) receipts specifically, since that's the scenario deskew exists for.
- **Device throughput bench case**: variant generation timing per kind, CPU vs. UMat/OpenCL, feeding the bench suite's existing CPU/GPU/RAM classification per setting.
- **Profiling integration** (see §9.3): bench runs under py-spy today (confirming worker-process parallelism is actually being achieved, not just assumed from the multiprocessing design), switching to/adding Tachyon once on Python 3.15+.
- Failure-injection mode: a bench case that kills a worker process mid-variant-generation, confirming the `ProcessPoolExecutor`-backed `VariantExecutor` reports a clean per-variant error (via the `Variant.error` field, §3) rather than the whole `GenerateVariants` call hanging or crashing the caller — same failure-injection principle both prior deep-dives' bench suites already apply to their own worker/engine processes.

---

## 12. Open questions for this deep-dive (logged, not guessed at)

**Resolved, reasoned defaults given rather than left as bare placeholders — all explicitly revisable once real bench data exists, none blocking:**
- **CLAHE clip limit / tile grid size** (§4.3, §7): starting values kept as the shipping default — reasonable, literature-typical starting points for this kind of contrast-limited adaptive histogram equalization, not arbitrary. Bench validation against real receipts (§11) can tune these later; nothing here blocks shipping with the current values.
- **Deskew method: contour, locked in as the default.** Already the reasoned choice over Hough (simpler, faster, sufficient for the skew angles a phone-captured receipt actually produces); the bench case in §11 can still override this later, but there's no reason to withhold a default in the meantime.
- **Denoise: opt-in, not default-on — resolved, not merely deferred.** This is itself the correct, conservative resolution: without a measured cost figure, opt-in is the safe default (a user who wants the extra processing time can enable it), not a placeholder waiting for permission to decide either way.
- **Fixed variant set membership** (§4.7): today's `variants_enabled` default (§7) ships as a real, reasoned starting set — the bench sweep can refine it later, but the current membership isn't arbitrary, it's the sensible starting guess this document's own §7 already reasoned through.

**Fully resolved, nothing pending**: Bulk-reprocessing hardware decode (§6.3 — deliberately not adopted at normal workload volume, a real decision), Preprocessing's participation depth in the live resource ledger (§6.7 — a real, deliberate "lean toward lightweight registration" choice, not blocked on anything), Intel MFX/VPL as a bulk-reprocessing escape hatch (§6.3 — checked and deliberately not adopted).

**Resolved as ongoing operational processes, owned by Telemetrees' continuous tracking, not design gaps**: PEP 734 subinterpreters as a future multiprocessing replacement (§8.5 — blocked on OpenCV's own subinterpreter compatibility, which Telemetrees tracks), `opencv-python`'s free-threaded-wheel and subinterpreter-compatibility status (§9.2, §8.5 — its own new tracked entry, not shared with OCR/Inference's `onnxruntime` tracking).

**Resolved — the cross-referenced document now has a real answer, this note updated to point at it rather than describe it as still-open elsewhere:**
- **Archival storage codec re-encoding** — genuinely out of this document's own scope, correctly deferred to Ingestion's Format Normalization sub-API, which has since had its own full design pass (`v3-deepdive-42-format-normalization.md` §3): one owner-selected codec (WebP or AVIF) for the whole install, software encode by default given hardware AV1 encode support is still too hardware-dependent to rely on, hash computed over original bytes before re-encoding. Nothing left pending on this specific cross-reference.
