# Phase 2 Kickoff — Local Claude Code Session (Full Application Development)

Hand this document directly to the Phase 2 Claude Code session. **This session also runs locally**, not remotely — the same session type as Phase 1, but a different job: this is where the actual application gets built, following the full deep-dive corpus. Read `PHASE_1_COMPLETE.md` (or whatever Phase 1 actually left behind) before starting anything here.

---

## 1. Why this session is local, and a real consideration worth flagging before it starts

**The stated reason for running this locally is running the real OCR engines properly** — something a remote sandboxed session can't do the way a genuine local environment can (real Tesseract/RapidOCR/PaddleOCR installs, real system-level dependencies, real hardware). **Worth flagging explicitly, since it wasn't named but the same reasoning applies**: Preprocessing and Inference have the identical local-hardware dependency OCR does, for the same underlying reason — Preprocessing's own OpenCL-accelerated variant generation and Inference's own ONNX Runtime model execution both benefit from, and in Inference's case may specifically need, real local GPU/NPU hardware that a remote sandbox won't have meaningful access to. If the reasoning for keeping this session local is "we need real hardware for OCR," that same reasoning almost certainly extends to validating Preprocessing and Inference too, not just OCR narrowly — worth keeping in mind when deciding what "properly validated before moving to remote" actually means, rather than treating OCR as the only piece that needed local hardware.

This also directly connects to `docs/PRE_STABLE_BENCH_VALIDATION.md`'s own real-receipt-scans requirement — that whole document assumes local access to real files and real hardware, and this session is where that validation work actually happens, not a separate concern from the main development effort.

---

## 2. Scope

Follow the full deep-dive corpus (`v3-deepdive-01` through `v3-deepdive-55`, plus every sub-API) to implement the real application — every Core API's own real logic, not just the scaffolding Phase 1 created. This session should treat each deep-dive as authoritative for its own API's design, and `v3-plan-03-decisions.md` as the record of why things ended up the way they did when a design choice isn't self-explanatory from the deep-dive alone.

---

## 3. Before treating anything as "done"

- Run `docs/PRE_STABLE_BENCH_VALIDATION.md` in full before this project tags x03.00.00 Stable/LTSC — this session is very likely where that validation work actually happens, given it's the session with real local hardware and file access. **Its own rule about real receipt scans, never synthetic, applies here directly** — don't let "we're just testing the pipeline works" become an excuse to generate fake receipts instead of asking for real ones.
- Confirm the Agent Control API round trip Phase 1 already validated (`PHASE_1_KICKOFF.md` §1.5) still works after real application code is built around it — a working MCP server in an otherwise-empty scaffold isn't the same guarantee as one still working once the real system exists underneath it.

---

## 4. Transitioning to remote sessions after x03.00.00 — a real checklist, not just a plan to revisit later

Once x03.00.00 ships and future work is expected to move to remote Claude Code sessions, confirm each of these before making that switch — not discovered as a problem after the fact:

- [ ] Is there any remaining development task that still genuinely needs local hardware (a new OCR engine being added, a new Inference preset needing real GPU validation)? If so, that specific task needs to stay local even after the general default moves to remote — the switch doesn't have to be all-or-nothing.
- [ ] Does the remote session's own environment (per Claude Code's actual current documentation at the time — verify, don't assume it's unchanged from whatever's true today) have adequate `gh` access for whatever repo actions ongoing work will need, or does the `domtrifoundation`-scoped `GH_TOKEN` pattern from Phase 1 need to be re-confirmed in that environment specifically?
- [ ] Is `docs/PRE_STABLE_BENCH_VALIDATION.md` itself fully checked off, or does some part of it still depend on local access that a remote session won't have going forward?
