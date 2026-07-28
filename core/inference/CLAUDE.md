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

`a03.00.00`

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
