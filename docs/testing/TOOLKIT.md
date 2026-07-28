# Developer Toolkit

The per-addition-category checks in `docs/templates/` run automatically and are mandatory for the PRs they apply to. Everything below is **optional but recommended** — tools worth knowing about and reaching for deliberately, not things CI forces on you.

## Pipeline & accuracy tools

**Bench suite** (`tests/bench/`) — real-pipeline, never-mocked, per-test-process-isolated benchmarking for OCR, Preprocessing, and Inference. A native crash in one engine is logged as CRASHED for that case, not taken down with the whole run. This is also the mechanism behind every "reasoned, then measured" default across the project (Tesseract's PSM mode, Preprocessing's variant-kind membership, Matching's scorer choice) — if you're changing a default that was originally bench-derived, re-run the relevant bench case, don't just change the number.

**Failure-injection mode** (part of the bench suite) — deliberately kills a worker process/engine mid-operation to confirm the surrounding scheduler survives it cleanly. Every major async orchestration point in this project (OCR's engine dispatch, Preprocessing's process pool, Execution Core's per-stage checkpointing, Health's Watchdog) has its own failure-injection test case in its own deep-dive's testing-hooks section — worth running the relevant one after touching any of that code, not just the code you think you changed.

**Interface walker** (`tests/interface/`) — auto-generated from live menu data, covered under `new_menu_item.md`'s CI check. Worth running manually (`pytest tests/interface/`) after any refactor that touches how menu data gets loaded, even if you didn't add a new item.

## Profiling

**py-spy** — attach to a running process by PID with no code changes, works across current Python versions. Has a `--gil`/`%GIL` mode specifically for answering "which thread is actually holding the GIL right now" — the practical tool for confirming whether an `asyncio`/executor-dispatch pattern is actually delivering the concurrency it's designed for. Use this today; it works pre-3.15.

**Tachyon** (Python 3.15+, `profiling.sampling`, PEP 799) — near-zero-overhead, attaches by PID, understands async code and threads natively, has its own GIL-holding sampling mode. The eventual successor to py-spy for this project once the fleet is genuinely on 3.15+; not a reason to skip py-spy now.

## Security & dependency tools

**Format-decoding fuzz pass** — malformed/truncated input fuzzing against every library that parses untrusted uploaded bytes (Pillow, `pillow-heif`, PyMuPDF) — a real requirement given at least one of these libraries has had a genuine CVE (integer overflow → heap OOB read) in its history. Run this after bumping any format-decoding dependency, not just when adding a new one.

**`pip-audit`** (or equivalent) — checks the current dependency tree against known vulnerability databases. Not currently wired into CI as a hard gate (worth reconsidering as the dependency surface grows), but worth running manually before any release, and definitely before any release that bumps a security-adjacent dependency (ClamAV, Authlib, `cryptography`).

**`bandit`** (or equivalent Python SAST tool) — static analysis for common security anti-patterns (hardcoded secrets, unsafe deserialization, SQL string concatenation). Worth running on any PR touching Auth, Billing, or Content Security specifically, given those are the highest-stakes packages in the codebase.

## GUI / webapp tools

**Playwright** (or equivalent) for webapp end-to-end testing — not yet wired into this project's test tree as of this writing, since the webapp itself doesn't exist yet. Flagged here as the recommended tool once it does, rather than left undecided when someone eventually needs it. Worth pairing with a visual-regression tool (Playwright's own screenshot comparison, or a dedicated tool) for the "My Files" browsing screen and the settings/menu surfaces specifically, since those are the highest-touch UI in the whole app.

**Textual's own testing utilities** (`textual.testing`, or the equivalent current API) for TUI-specific interaction tests — beyond what the interface walker covers (menu-data integrity), for testing the enumerated custom-screen exceptions' own actual interactive behavior (the run monitor, the OCR diff viewer).

## Load & concurrency tools

**A concurrent-load harness for hot-path APIs** — Auth's `ValidateSession`, Health's `ReserveResource`, Search/Query's structured lookups are all explicitly flagged in their own deep-dives as "reasoned to be a fast single indexed lookup, not yet measured under realistic concurrent load." No specific tool is mandated here — `locust`, a hand-rolled `asyncio`-based load generator, or anything that can hammer a gRPC endpoint concurrently and report latency percentiles works. Worth building this out for real once there's a realistic traffic pattern to test against, rather than picking a tool prematurely.

## A note on all of the above
None of this replaces the mandatory per-addition-category CI checks in `docs/templates/`. This is the toolkit for going beyond "does this pass the required checks" into "have I actually verified this behaves the way I designed it to" — the same "reasoned, then measured" discipline (`docs/PRINCIPLES.md` §5) applied at the tooling level, not just the default-value level.
