# The Day-0 Compatibility Promise

**This document is source material for the eventual README and GitHub Wiki** (`docs/MAKING_README.md`, `docs/WIKI_MIGRATION_PLAN.md`) — not itself the final public-facing copy, but the real, comprehensive, verified inventory that copy should be written from. Every item below is a genuine, currently-designed-or-tracked capability, cross-referenced to where it actually lives — not aspirational marketing language invented for this document.

**The actual promise, stated precisely, not softened**: when the Python ecosystem or this project's own dependencies ship something that could genuinely make the scanner faster, more accurate, or more capable, this project is positioned to have that support built and validated *during the upstream feature's own beta/pre-release phase* — ready and working before that feature even reaches its own stable release, not on the day it does. Concretely: `FrozenDict`, Tachyon, and this corpus's other Python 3.15-era capabilities are planned to be supported by the time this project's own x03.00.00 (Stable/LTSC) ships — and x03.00.00 is itself planned to ship before Python 3.15's own stable release. That's not a claim made in the abstract; it's the direct, designed consequence of the Forward-Compatibility Pattern (`docs/PRINCIPLES.md` §3.3-3.3.1) combined with Dependencies Warden's own explicit tracking of pre-release activity (§3 below has the full mechanism), applied consistently rather than asserted once and left to go stale.

---

## 1. The core mechanism, briefly (full detail: `docs/PRINCIPLES.md` §3.3)
Every version-sensitive piece of code follows the same five-point pattern: conditional installation via environment markers, feature-detection over hard version checks, one centralized shim per capability, graceful degradation to existing safe behavior, and lazy imports where a dependency is genuinely optional. **Telemetrees' own Dependencies Warden sub-API tracks every instance of this continuously** (`v3-deepdive-28-telemetrees-api.md`), not as a one-time audit but as a standing, ongoing process — a new PEP landing, an upstream issue resolving, a model generation shipping are all things this project finds out about and evaluates promptly, not eventually.

---

## 2. The real, current inventory — every genuinely tracked forward-looking capability

### 2.1 Python language features
- **PEP 734 (subinterpreters, stabilized in 3.14)** — a real, promising future replacement for Preprocessing's own multiprocessing-based worker pool, giving process-like isolation without IPC/pickling overhead. Not yet adopted, blocked specifically on OpenCV's own subinterpreter compatibility (tracked below), logged as a real design candidate rather than spectulative musing (`v3-deepdive-03-preprocessing-api.md` §8.5).
- **PEP 810 (lazy imports, Python 3.15)** — already applied in design to OCR API's heaviest optional engines (`paddlepaddle`, `rapidocr-onnxruntime`) and Inference API's own generation library (`onnxruntime-genai`), so a disabled engine's multi-gigabyte dependency never pays its import cost on a self-hosted install that doesn't use it (`v3-deepdive-01-ocr-api.md` §10.4, `v3-deepdive-02-inference-api.md` §6.7).
- **PEP 799 (Tachyon, the new stdlib-adjacent sampling profiler, Python 3.15)** — identified as `py-spy`'s eventual successor for this project's own bench-timing work: near-zero overhead even at high sampling rates, attaches to a running process by PID without a restart, native thread/async awareness. Wired up alongside `py-spy` now rather than waiting, since 3.15 wasn't released at time of writing (`v3-deepdive-01-ocr-api.md` §10.3).
- **Free-threading (no-GIL) itself** — the single most cross-cutting item on this list, tracked per-dependency rather than as one blanket status (§2.2 below), since a project-wide "are we free-threading-ready" question is really dozens of independent per-dependency questions.

### 2.2 Per-dependency free-threading status, tracked individually (not as one blanket fact)
- `onnxruntime` / `onnxruntime-genai` — shared between OCR and Inference APIs, one tracked entry, not two.
- `opencv-python` — Preprocessing's own dependency, with a specific, named upstream blocker: `opencv/opencv#27933` and `opencv-python#1051`, tracked as the actual trigger condition for revisiting Preprocessing's own multiprocessing design, not a vague "check back later."
- `rapidfuzz` / `numpy` — shared between OCR and Matching APIs.
- `pymupdf` / `pillow-heif` — Ingestion's own dependencies. **`pillow-heif` already has declared free-threading support** — a genuinely positive data point worth tracking as such, not just watched for a gap.
- `authlib` / `cryptography` — Auth's own dependencies.
- **A real community resource, verified current rather than assumed**: `py-free-threading.github.io`, confirmed via direct research as the actual, well-established tracker the ecosystem itself relies on (`v3-deepdive-37-dependencies-warden.md` §9) — this project's own tracking cross-references that resource rather than duplicating its own research from scratch.

### 2.3 The `FrozenDict` built-in question specifically
Python 3.15 introduces a genuine built-in frozen-dict-shaped type. This project's own `frozendict` package dependency is conditionally installed via an environment marker (`frozendict; python_version < '3.15'`) so the external package is never even installed on 3.15+ — and **recommended validation on real 3.15/3.16 interpreters specifically confirms the code path actually takes the built-in branch**, not just that the external package didn't get installed (`docs/PRINCIPLES.md` §3.3.1 — the concrete difference between "the dependency resolver did the right thing" and "the running code actually behaves the way that implies").

### 2.4 Model and dataset currency — a different tracked-fact shape, same underlying discipline
- **RapidOCR's own bundled ONNX models** potentially lagging PaddleOCR's newer model generations (PP-OCRv5, PaddleOCR-VL) — "is our vendored copy stale relative to upstream" is a genuinely different question than a software version bump, tracked as its own fact kind (`v3-deepdive-01-ocr-api.md` §9).
- **ClamAV's virus-definition database freshness** — the same "is our copy stale" shape applied to a security-critical dataset rather than a model; a stale definitions database is a silent security gap distinct from the `pyclamd` package itself being outdated (`v3-deepdive-27-content-security-api.md` §5.1, tracked via `v3-deepdive-28-telemetrees-api.md` §3.1).
- **BIR's own SLSP threshold values** — a government-set numeric fact that can change independent of anything in this project's own control, tracked the same way (`v3-deepdive-31-export-framework.md` §4.1).

### 2.5 The Python interpreter itself
3.13 as the current default/pinned baseline (moved from 3.14, confirmed directly against PyPI: `rapidocr-onnxruntime` has no build for 3.13 or newer in any released version, so 3.14 bought nothing over 3.13 for that one dependency while everything else — `grpcio` included — already works on 3.13); 3.14, 3.15, and 3.16 tracked as real, ongoing adoption-readiness questions, not a one-time migration decision made once and considered closed.

---

## 3. Why this is a real product claim, not just an engineering nicety
A receipt scanner's own accuracy and speed are directly downstream of the OCR/preprocessing/inference stack underneath it — when that stack's own dependencies ship something genuinely better (a faster free-threaded build, a new lightweight model architecture, a faster profiling tool that catches a regression sooner), **the gap between "the industry has this" and "this project's scanner benefits from it" is the actual, measurable value of the discipline in §1 above.** A project that treats forward-compatibility as an afterthought re-derives this readiness reactively, under time pressure, after a user-visible problem or a missed opportunity; this project tracks it continuously, as a standing process, specifically so the gap stays small by design rather than by accident.

**The specific, concrete claim, stated precisely rather than softened into vague "we adopt things fast" language**: this project's own plan is to support `FrozenDict`, Tachyon, and the other Python 3.15-era capabilities in §2 *by the time x03.00.00 (Stable/LTSC) ships — which is itself planned to happen before Python 3.15's own stable release.* This isn't "the day it's stable, not months later" — it's earlier than that: **built and validated against 3.15's own beta releases**, ready and working *before* 3.15 itself reaches general availability. This is a genuinely stronger claim than "fast adoption," and it's directly supported by the actual tracking mechanism already in place, not aspirational: Dependencies Warden (`v3-deepdive-37-dependencies-warden.md`) explicitly monitors **pre-release activity, not just stable releases** (its own parent document, `v3-deepdive-28-telemetrees-api.md` §1, states this plainly — "tracking every registered dependency's release activity, stable *and* pre-release"), and Proving Grounds (`v3-deepdive-36-proving-grounds.md`) is the real execution mechanism that tests a flagged beta feature against actual bench workloads before it's adopted — meaning a 3.15 beta's own `FrozenDict` behavior, or an early Tachyon build, can genuinely be validated and shipped in this project's own code well before 3.15 itself goes stable, exactly the sequence this claim describes.

---

## 4. For whoever writes the actual README/Wiki copy from this
- Don't just copy the technical detail in §2 verbatim — that's the *evidence*, not the pitch. The pitch is §3.
- Keep this document itself updated as the real, single source of truth for what's actually tracked — the same "update in the same PR as the change it describes" discipline every other document in this corpus follows (`docs/MAINTENANCE.md` §6). If the README/Wiki copy and this document drift apart, this document is the one that's actually current.
