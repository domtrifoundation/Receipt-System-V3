# Process Topology

This document exists because "process separation via gRPC" (`docs/PRINCIPLES.md` §1.7) was stated as a principle without ever mapping out concretely *which* APIs run *where*. Several individual deep-dive documents use "the main process" as loose shorthand — this document is the correction and the authoritative map. Where another document's phrasing conflicts with this one, this one is right.

---

## 1. The actual model: one process per Core API, not one shared "main process"

**There is no single "main process."** Update API's own Boot Sequence design (originally documented at `v3-deepdive-24-update-deployment-api.md` §5, since moved to Supervisor's own dedicated document, `v3-deepdive-38-supervisor.md`, during a later double-check pass) is the proof: Supervisor "launches each service in dependency order (Persistence before Execution Core, which depends on it)" — services launched individually, in a real dependency order, is not consistent with one bundled process. The underlying reason is stated even earlier in the same original source: Supervisor launches "each service from the correct per-user-channel release's own **per-service venv**" — a venv is a single Python environment; a service with its own venv is, structurally, its own OS process. This isn't incidental. Every Core API in this project has a genuinely different, sometimes conflicting dependency footprint (OCR's OpenCV/Tesseract/PaddleOCR stack has nothing to do with Auth's Authlib, and bundling them into one shared environment would be a real version-pinning conflict risk) — one venv per service is what avoids that, and one process per venv is what falls out of it naturally.

**Supervisor itself is neither Layer 1 nor Layer 2 — worth naming as its own, structurally distinct category.** Every Layer 1 process lives inside a versioned release clone; every Layer 2 process (Interface, Gateway) is a detachable client of Layer 1. Supervisor lives **outside every release clone, permanently** — it's the thing that decides which clone is even active and launches Layer 1 from it in the first place, so it structurally can't be part of what it launches. Its own full design, including why it can't update itself the same way it updates everything else, lives in `v3-deepdive-38-supervisor.md`.

**So: every one of the 32 Core APIs runs as its own independently-launched process**, tied together entirely by internal gRPC calls. Wherever another document in this corpus says "the main process" (Logs, Health, and Interface's own deep-dives all do this, as loose shorthand written before this document existed), read it as **"the core service cluster"** — a set of independent, cooperating processes, not a literal singular process. None of the *conclusions* those documents draw change (Logs API is still fully independent of Interface either way) — only the precision of how it's described.

---

## 2. The three layers

### Layer 1 — Core service processes (the backend, collectively)
All 32 Core APIs (OCR, Preprocessing, Inference, Persistence, Execution Core, Auth, Audit, Logs, Health, Architect, Content Security, Telemetrees, Agent Control, and the rest), each its own process, each its own venv, launched and health-gated individually by Supervisor at Boot Sequence, communicating exclusively via internal gRPC. This layer runs continuously and does not care whether anything in Layer 2 is connected.

### Layer 2 — Client processes (detachable, per `docs/PRINCIPLES.md` §1.7)
**Interface's TUI** and **Gateway** — both genuinely separate processes from Layer 1, both consuming Layer 1 exclusively through gRPC, both can be closed, crash, or simply never be launched for a given install without Layer 1 noticing or caring. Neither is "part of" any Core API's own process; both are clients of the whole cluster.

### Layer 3 — The browser (external, not managed by this system at all)
The webapp's actual **runtime** — the React application executing — runs entirely on the end user's own machine, inside their own browser. This project doesn't run, host, or manage this process in any sense; it's genuinely external, the same way any web application's client-side code runs on a machine the server operator doesn't control.

---

## 3. Where the webapp actually lives — the two different senses of "hosted"

Worth answering precisely, since "where is the webapp hosted" is ambiguous between two genuinely different things:

- **Where the webapp's code is *served from***: Gateway's own process (Layer 2). Gateway API's deep-dive already established this — "Gateway serves the webapp's static build in every deployment mode" — a corrected decision from an earlier plan that had a separate static-hosting service (Cloudflare Pages) independently versioned from the backend, which risked a real, nasty bug class (a Beta-channel backend paired with a Stable-channel frontend). Gateway serving both closes that gap by construction.
- **Where the webapp actually *runs***: Layer 3, the end user's browser, on their own machine. Not this system's process at all.

**The actual data flow, precisely**: browser (Layer 3) → HTTP/WebSocket request → Gateway (Layer 2, an external network hop) → Gateway translates the request into an internal gRPC call → whichever Core API process (Layer 1) actually owns the data → response flows back the same path in reverse. The browser never talks to a Core API process directly, ever — Gateway is the only Layer 2↔Layer 1 bridge the browser-facing side has.

---

## 4. A second, smaller-scoped kind of process separation: workers *within* one service

Distinct from the Layer 1/2/3 model above — some individual Core APIs spawn their *own* child worker processes for their own internal reasons, nested one level deeper. These are not peers of the 32 Layer-1 processes; they're private to whichever API spawned them, invisible to gRPC entirely (no other Core API ever talks to them directly).

- **Preprocessing's `ProcessPoolExecutor` workers** (its deep-dive §8) — child processes of Preprocessing's own process specifically, spawned for genuine CPU-bound variant-generation parallelism and crash isolation (a segfault in one variant-generation task doesn't take down Preprocessing's own service process).
- **Background Workers' `CPU_PROCESS`-class jobs** (its deep-dive §3) — dispatched via whichever API registered the job, through Background Workers' own routing logic.
- **Inference API's generation workers** (its deep-dive §6.1) — see §5 below; this is the one that had a real, corrected bug.

---

## 5. Inference API's generation workers — the "separated ONNX process," corrected

This is where writing this document surfaced a genuine inconsistency, not just a gap. File 02's own concurrency table always described Inference API as "async caller + native/**isolated-process** generation" — but Inference API's own deep-dive, as originally written, implemented that with a *thread*-pool `run_in_executor` dispatch, not a real separate process. Isolated in name only.

**Corrected** (Inference deep-dive §6.1): `PresetWorker` is now a handle to a genuine `multiprocessing.Process`, one per loaded preset, spawned by and private to Inference API's own service process — the actual `og.Model`/`og.Generator` objects are constructed and live entirely inside that child process, never in Inference API's own process space at all. The parent process doesn't even import `onnxruntime_genai`'s heavy native bindings into itself.

**Why this correction matters, concretely**: `onnxruntime-genai`'s native code is a real, non-hypothetical crash surface (GPU driver issues, a malformed model, an out-of-memory kill). Under the original thread-based design, a crash there would have taken down Inference API's *entire service process* — every other loaded preset, and its own ability to answer Health API's status checks. Under the corrected design, a crash is contained to exactly one preset's worker process; Inference API's own process, and every other preset's own worker, are structurally unaffected. This is the same crash-containment property Preprocessing's own `ProcessPoolExecutor` design already had (§4 above) — there was never a principled reason Inference's generation should have a weaker isolation guarantee than Preprocessing's variant generation, especially given generation is the more expensive, more crash-prone call of the two.

---

## 6. Boot Sequence — launch and dependency order

Consolidated in `v3-deepdive-38-supervisor.md` §3.2 (originally scattered across Update API's and Setup API's own deep-dives): Supervisor determines which release to run, then launches every Layer 1 process **in dependency order** — Persistence before Execution Core, since Execution Core depends on it — waiting for Watchdog to confirm each service's first successful health check before proceeding to the next. Only once every Layer 1 process is confirmed healthy does Interface API's loading screen hand off to the main TUI. A service that fails to come up within a timeout surfaces clearly via Review/Flagging or Telemetrees, never silently hangs. Layer 2 processes (Interface, Gateway) start only after Layer 1 is confirmed healthy — a client has nothing useful to connect to before then.

---

## 7. Quick-reference map

| Process | Layer | Owns its own venv | Spawns its own child workers |
|---|---|---|---|
| **Supervisor** | Its own category — outside every clone, launches Layer 1, permanent | Yes, its own minimal one, never replaced by a normal clone/update | No — but manages sleep/wake for idle Layer 1 processes (`v3-deepdive-38-supervisor.md` §5) |
| Each of the 32 Core APIs (OCR, Preprocessing, Persistence, Execution Core, Auth, Audit, Logs, Health, Architect, etc.) | 1 — core service | Yes, individually | Only Preprocessing, Background Workers, and Inference (see §4-§5) |
| **Agent Control** (`v3-deepdive-55-agent-control-api.md`) | 1 — core service, but with an externally-reachable MCP listener | Yes | Its Test Orchestration sub-API (`v3-deepdive-56-test-orchestration.md`) genuinely *signals* other services' worker processes during crash-isolation testing — the only component in this system that deliberately does so, and only ever against a process Supervisor itself identified, never a blind `pkill` |
| Interface (TUI) | 2 — detachable client | Yes | No |
| Gateway | 2 — detachable client | Yes | No |
| Webapp (React) | 3 — external, end-user's own browser | N/A, not this system's process | N/A |

---

## 8. What this corrects elsewhere, and what it doesn't

**Corrected as part of writing this document**: Inference API's `PresetWorker` implementation (§5 above, applied directly to `v3-deepdive-02-inference-api.md` §6.1-6.6) — a real bug, not just an imprecision.

**Not corrected, deliberately**: the loose "main process" phrasing in Logs, Health, and Interface's own deep-dives is left as-is in those documents rather than hunted down and edited everywhere it appears — every conclusion those documents draw is still accurate (Logs really is independent of Interface, Health really does run continuously regardless of clients), only the singular-process framing was imprecise. This document is the correction to point to; a purely cosmetic wording pass across every prior document isn't worth the churn it would cause to already-reviewed content.
